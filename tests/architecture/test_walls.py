"""Architecture wall tests. These encode the project thesis. NEVER edit them to make a change pass.

Wall 1: no LLM client imports outside the allowed probabilistic zone.
Wall 2: no dynamically built SQL, no eval/exec, anywhere in src/.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "recount"

LLM_MODULES = {"anthropic", "openai", "litellm", "google.genai", "google.generativeai", "cohere", "mistralai"}
ALLOWED_LLM_ZONE = ("extract/", "bench/baseline_judge.py")


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py"))


def _rel(p: Path) -> str:
    return p.relative_to(SRC).as_posix()


def test_wall_1_no_llm_imports_outside_extract() -> None:
    offenders: list[str] = []
    for path in _py_files():
        rel = _rel(path)
        if rel.startswith(ALLOWED_LLM_ZONE[0]) or rel == ALLOWED_LLM_ZONE[1]:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                if any(n == m or n.startswith(m + ".") for m in LLM_MODULES):
                    offenders.append(f"{rel}: import {n}")
    assert not offenders, "LLM client imported outside the probabilistic zone:\n" + "\n".join(offenders)


_DYNAMIC_SQL = re.compile(r"""f["'](?:[^"']*\b(?:SELECT|FROM|WHERE|GROUP BY|ORDER BY)\b)""", re.I)


def test_wall_2_no_dynamic_sql_or_eval() -> None:
    offenders: list[str] = []
    for path in _py_files():
        text = path.read_text()
        rel = _rel(path)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                offenders.append(f"{rel}:{node.lineno}: {node.func.id}() call")
        for i, line in enumerate(text.splitlines(), 1):
            if _DYNAMIC_SQL.search(line):
                offenders.append(f"{rel}:{i}: f-string SQL")
    assert not offenders, "Dynamic SQL / eval / exec found:\n" + "\n".join(offenders)
