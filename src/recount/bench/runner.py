"""Benchmark runner (docs/benchmark.md C1–C6).

For every artifact (the clean report + every variant): extraction (recorded replay, or
live through a throttled, recording client) → verification of every accepted claim →
scoring (M1–M2) → the judge (replay or live). Recordings are keyed by the sha256 of what
the model saw, so an identical artifact is never requested twice and an interrupted
live run resumes at zero cost. Replay needs no key; a missing recording is an error,
never a silent skip.

Only the public `recount.extract` seam is imported here; which client runs is the
caller's choice (the CLI passes `GeminiClient` for `--live`).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from recount import __version__
from recount.bench.baseline_judge import Judgement, judge, judge_input
from recount.bench.corrupt import SEEDS, generate, inject
from recount.bench.metrics import Scored, class_rows, judge_score, percentiles, score
from recount.bench.summary import summarize
from recount.config import SemanticConfig, load_config
from recount.extract import Extraction, ExtractorClient, MockClient, RecordingClient, extract_claims
from recount.extract.eval import evaluate
from recount.io import Dataset, load_dataset
from recount.verify import Verdict, verify_claim

RETRY_MARKERS = ("429", "RESOURCE_EXHAUSTED", "rate limit", "quota")
BACKOFF_S = (30.0, 60.0, 120.0, 240.0, 480.0)


class BenchError(Exception):
    """The run cannot produce a result: a recording is missing and the run is not live."""


@dataclass(frozen=True)
class Paths:
    clean: Path = Path("spike/report_clean.md")
    labels: Path = Path("tests/fixtures/labeled_claims.json")
    # The verifier's config (what claims resolve against; `recount bench --config`).
    config: Path = Path("tests/fixtures/olist_metrics.yml")
    # The frozen snapshot the suite is generated from (I5): the fabricated_metric pool reads
    # config aliases, so the live vocabulary must never re-sample the suite (changelog 7).
    suite_config: Path = Path("bench/suite_config.yml")
    dataset: Path = Path("examples/olist/orders.parquet")
    recordings: Path = Path("bench/recordings")


class ThrottledClient:
    """Spaces live calls (C6), retries on rate-limit errors with backoff, and keeps the
    latency of every successful inner call (M9). Sleeps are excluded from latency."""

    def __init__(
        self,
        inner: ExtractorClient,
        min_interval_s: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self.model = inner.model
        self._interval = min_interval_s
        self._sleep = sleep
        self._last_start = 0.0
        self.latencies: list[float] = []

    def complete(self, prompt: str, artifact: str, schema: dict[str, Any]) -> str:
        for attempt in range(len(BACKOFF_S) + 1):
            wait = self._last_start + self._interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last_start = time.monotonic()
            t0 = time.perf_counter()
            try:
                text = self._inner.complete(prompt, artifact, schema)
            except Exception as e:
                if attempt < len(BACKOFF_S) and any(m in str(e) for m in RETRY_MARKERS):
                    self._sleep(BACKOFF_S[attempt])
                    continue
                raise
            self.latencies.append(time.perf_counter() - t0)
            return text
        raise AssertionError("unreachable")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class Recorder:
    """Resolves a client per artifact: replay if recorded, live if allowed, else error."""

    recordings: Path
    live: ThrottledClient | None
    log: Callable[[str], None]
    calls: int = 0
    replays: int = 0
    _seen: set[Path] = field(default_factory=set)

    def path(self, kind: str, text: str) -> Path:
        return self.recordings / kind / (_sha(text)[:16] + ".json")

    def run(
        self, kind: str, text: str, label: str, call: Callable[[ExtractorClient], Any]
    ) -> tuple[Any, list[float]]:
        path = self.path(kind, text)
        if path.exists():
            self.replays += 1
            data = json.loads(path.read_text())
            # a shared artifact's latency counts once (class 7 replays its sibling's recording)
            latencies = [] if path in self._seen else [float(x) for x in data.get("latency_s", [])]
            self._seen.add(path)
            return call(MockClient(path)), latencies
        if self.live is None:
            raise BenchError(f"no {kind} recording for {label} ({path}); run with --live")
        self.log(f"live {kind}: {label}")
        n0 = len(self.live.latencies)
        rec = RecordingClient(self.live)
        result = call(rec)
        rec.save(path)
        latencies = [round(x, 3) for x in self.live.latencies[n0:]]
        payload = json.loads(path.read_text())
        payload["latency_s"] = latencies  # what a replay will report, so live == replay
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        self.calls += 1
        self._seen.add(path)
        return result, latencies


@dataclass
class ArtifactRun:
    extraction: Extraction
    verdicts: tuple[Verdict, ...]
    extract_latency: list[float]
    judgement: Judgement | None
    judge_latency: list[float]


def _verify_all(
    ds: Dataset, extraction: Extraction, cfg: SemanticConfig, timings: list[float]
) -> tuple[Verdict, ...]:
    out: list[Verdict] = []
    for claim in extraction.claims:
        t0 = time.perf_counter()
        out.append(verify_claim(ds, claim, cfg))
        timings.append((time.perf_counter() - t0) * 1000.0)
    return tuple(out)


DEFAULT_PATHS = Paths()


def run_bench(
    paths: Paths = DEFAULT_PATHS,
    *,
    seeds: tuple[int, ...] = SEEDS,
    live: ExtractorClient | None = None,
    rpm: float = 10.0,
    with_judge: bool = True,
    previous: dict[str, Any] | None = None,
    log: Callable[[str], None] = lambda s: None,
) -> dict[str, Any]:
    cfg = load_config(paths.config)
    labels = json.loads(paths.labels.read_text())["claims"]
    clean_text = paths.clean.read_text()
    suite = generate(clean_text, labels, load_config(paths.suite_config), paths.dataset, seeds)
    clean_ds = load_dataset(paths.dataset, cfg)
    clean_summary = summarize(clean_ds, cfg)
    throttled = None if live is None else ThrottledClient(live, 60.0 / rpm)
    rec = Recorder(paths.recordings, throttled, log)
    verify_ms: list[float] = []

    def run_artifact(text: str, label: str, ds: Dataset, summary: str) -> ArtifactRun:
        extraction, ext_lat = rec.run("extract", text, label, lambda c: extract_claims(text, c))
        verdicts = _verify_all(ds, extraction, cfg, verify_ms)
        judgement: Judgement | None = None
        judge_lat: list[float] = []
        if with_judge:
            judgement, judge_lat = rec.run(
                "judge", judge_input(text, summary), label, lambda c: judge(text, summary, c)
            )
        return ArtifactRun(extraction, verdicts, ext_lat, judgement, judge_lat)

    log("clean report")
    clean_run = run_artifact(clean_text, "clean", clean_ds, clean_summary)
    runs: dict[str, ArtifactRun] = {}
    for v in suite.variants:
        ds, summary = clean_ds, clean_summary
        if v.injection is not None:
            ds = inject(paths.dataset, cfg, v.injection)
            summary = summarize(ds, cfg)
        runs[v.variant_id] = run_artifact(v.artifact, v.variant_id, ds, summary)

    scored: list[Scored] = []
    for v in suite.variants:
        r = runs[v.variant_id]
        sib = runs.get(v.sibling) if v.sibling else None
        scored.append(
            score(
                v,
                r.extraction,
                r.verdicts,
                cfg,
                judgement=r.judgement,
                sibling_verdicts=None if sib is None else sib.verdicts,
                sibling_judgement=None if sib is None else sib.judgement,
            )  # fmt: skip
        )

    clean_labels = [
        {**lb, "claim": {**lb["claim"], "span": str(lb.get("clean_span") or lb["claim"]["span"])}}
        for lb in labels
    ]
    ev = evaluate(clean_text, clean_labels, clean_run.extraction, cfg)
    clean_judge: dict[str, Any] = {}
    if clean_run.judgement is not None:
        _, flags = judge_score(clean_text, None, clean_run.judgement)
        clean_judge = {"faithful": clean_run.judgement.faithful, "false_flags": flags}
    clean_block: dict[str, Any] = {
        "claims": len(clean_run.extraction.claims),
        "rejected": len(clean_run.extraction.rejected),
        "PASS": sum(x.verdict == "PASS" for x in clean_run.verdicts),
        "FAIL": sum(x.verdict == "FAIL" for x in clean_run.verdicts),
        "UNVERIFIABLE": sum(x.verdict == "UNVERIFIABLE" for x in clean_run.verdicts),
        "false_flag_rate": round(
            sum(x.verdict == "FAIL" for x in clean_run.verdicts)
            / max(1, sum(x.verdict != "UNVERIFIABLE" for x in clean_run.verdicts)),
            4,
        ),
        "label_recall": ev.recall,
        "label_precision": ev.precision,
        "unextracted_numeric": [t.context for t in clean_run.extraction.unextracted_numeric],
        "judge": clean_judge,
    }

    all_runs = [clean_run, *runs.values()]
    ext_lat = [x for r in all_runs for x in r.extract_latency]
    jud_lat = [x for r in all_runs for x in r.judge_latency]
    latency: dict[str, Any] = {
        "extraction_s": {**percentiles(ext_lat), "source": "recordings of the live run"},
        "judge_s": {**percentiles(jud_lat), "source": "recordings of the live run"},
        "verification_ms_per_claim": {
            **percentiles(verify_ms),
            "source": "live run" if live is not None else "this replay",
        },
    }
    if live is None and previous and "latency" in previous:
        # Replay keeps the live run's verification numbers so the committed JSON stays
        # byte-identical (C4); the fresh measurement goes to the log.
        log(f"verification latency measured on this replay: {latency['verification_ms_per_claim']}")
        latency["verification_ms_per_claim"] = previous["latency"]["verification_ms_per_claim"]

    variants = list(suite.variants)
    return {
        "version": __version__,
        "model": clean_run.extraction.model,
        "seeds": list(seeds),
        "suite_sha256": suite.sha256,
        "clean_sha256": suite.clean_sha256,
        "n_artifacts": 1 + len(variants),
        "n_distinct_artifacts": len({v.artifact_sha256 for v in variants} | {suite.clean_sha256}),
        "live_calls": rec.calls,
        "replays": rec.replays,
        "clean": clean_block,
        "classes": class_rows(scored, variants),
        "variants": [s.as_dict() for s in scored],
        "latency": latency,
    }


# ------------------------------------------------------------------ call planning (C6)


def plan_calls(paths: Paths = DEFAULT_PATHS, seeds: tuple[int, ...] = SEEDS) -> dict[str, int]:
    """How many live calls a full run needs, net of existing recordings."""
    cfg = load_config(paths.config)
    labels = json.loads(paths.labels.read_text())["claims"]
    clean_text = paths.clean.read_text()
    suite = generate(clean_text, labels, load_config(paths.suite_config), paths.dataset, seeds)
    extract_keys = {suite.clean_sha256} | {v.artifact_sha256 for v in suite.variants}
    clean_summary = summarize(load_dataset(paths.dataset, cfg), cfg)
    judge_keys = {_sha(judge_input(clean_text, clean_summary))}
    for v in suite.variants:
        summary = (
            clean_summary
            if v.injection is None
            else summarize(inject(paths.dataset, cfg, v.injection), cfg)
        )
        judge_keys.add(_sha(judge_input(v.artifact, summary)))
    missing_e = sum(
        not (paths.recordings / "extract" / (k[:16] + ".json")).exists() for k in extract_keys
    )
    missing_j = sum(
        not (paths.recordings / "judge" / (k[:16] + ".json")).exists() for k in judge_keys
    )
    return {
        "artifacts": 1 + len(suite.variants),
        "extract_calls": len(extract_keys),
        "judge_calls": len(judge_keys),
        "extract_missing": missing_e,
        "judge_missing": missing_j,
    }


# ------------------------------------------------------------------ README table (C4, M11)

BENCH_START = "<!-- BENCH:START -->"
BENCH_END = "<!-- BENCH:END -->"
CLASS_ORDER = (
    "wrong_figure",
    "flipped_direction",
    "wrong_ranking",
    "swapped_entity",
    "fabricated_metric",
    "rounding_drift",
    "instruction_in_data",
)


def _pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{100 * rate:.0f}%"


def _frac(num: int, den: int, rate: float | None) -> str:
    return f"{num}/{den} ({_pct(rate)})"


def render_table(results: dict[str, Any]) -> str:
    rows = results["classes"]
    header = [
        "class", "n", "claims", "detection", "by abstention", "false accept", "coverage",
        "abstention", "sweep flagged", "collateral flags", "judge detection", "judge false accept",
        "judge localized",
    ]  # fmt: skip
    lines = [
        f"Recount {results['version']} · {results['n_artifacts']} artifacts "
        f"({results['n_distinct_artifacts']} distinct) · "
        f"seeds {', '.join(map(str, results['seeds']))} · "
        f"extractor and judge: `{results['model']}` · suite `{results['suite_sha256'][:12]}` · "
        "methodology and per-class analysis in [docs/benchmark.md](docs/benchmark.md).",
        "",
        "| " + " | ".join(header) + " |",
        "|" + "---|" * len(header),
    ]
    for name in [*CLASS_ORDER, "exact_match", "overall"]:
        if name not in rows:
            continue
        r = rows[name]
        n = r["n"]
        label = {"exact_match": "**exact-match classes**", "overall": "**overall**"}.get(name, name)
        lines.append(
            "| " + " | ".join([
                label, str(n), str(r["distinct_claims"]),
                _frac(r["detected"], n, r["detection_rate"]),
                _frac(r["detected_by_abstention"], n, r["abstention_detection_rate"]),
                _frac(r["false_accept"], n, r["false_accept_rate"]),
                _frac(n - r["unextracted_total"], n, r["coverage"]),
                _pct(r["abstention_rate"]),
                str(r["unextracted_sweep_flagged"]),
                str(r["collateral_false_flags"]),
                _frac(r["judge_detected"], r["judge_n"], r["judge_detection_rate"]),
                _frac(r["judge_false_accept"], r["judge_n"], r["judge_false_accept_rate"]),
                _frac(r["judge_localized"], r["judge_n"], r["judge_localization_rate"]),
            ]) + " |"
        )  # fmt: skip
    c = results["clean"]
    lines += [
        "",
        f"Clean report: {c['claims']} claims, {c['PASS']} PASS / {c['FAIL']} FAIL / "
        f"{c['UNVERIFIABLE']} UNVERIFIABLE "
        f"(false-flag rate {_pct(c['false_flag_rate'])}); label recall {c['label_recall']:.4f}, "
        f"precision {c['label_precision']:.4f}; unextracted numerics: "
        f"{', '.join(c['unextracted_numeric']) or 'none'}"
        + (
            f"; judge: {'faithful' if c['judge'].get('faithful') else 'unfaithful'}, "
            f"{c['judge'].get('false_flags', 0)} false flags."
            if c["judge"]
            else "."
        ),
    ]
    if "instruction_in_data" in rows:
        r = rows["instruction_in_data"]
        lines.append(
            "instruction_in_data: Recount verdicts identical to the sibling variant in "
            f"{r['invariant']}/{r['n']} "
            "(invariant by construction); judge detections suppressed by the injected cell: "
            f"{r['judge_suppressed']}/{r['judge_n']}."
        )
    lat = results["latency"]
    lines += [
        "",
        "| latency | p50 | p95 | n | source |",
        "|---|---|---|---|---|",
    ]
    for key, unit in (("extraction_s", "s"), ("judge_s", "s"), ("verification_ms_per_claim", "ms")):
        x = lat[key]
        lines.append(
            f"| {key.replace('_', ' ')} | {x['p50']} {unit} | {x['p95']} {unit} | "
            f"{x['n']} | {x['source']} |"
        )
    return "\n".join(lines) + "\n"


def write_readme(readme: Path, table: str) -> None:
    text = readme.read_text()
    a, b = text.index(BENCH_START) + len(BENCH_START), text.index(BENCH_END)
    readme.write_text(text[:a] + "\n" + table + text[b:])
