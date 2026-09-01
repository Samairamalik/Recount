# Hand-labeling guide (read before labeling a single sentence)

Ground truth is only as good as its consistency. Rules:

1. **One claim per checkable assertion.** "Revenue grew 12.4% and São Paulo overtook Rio" = TWO claims.
2. **Label every claim, even ones you expect to be UNVERIFIABLE.** Abstention correctness needs positives.
3. **Vague quantifiers** ("significantly", "nearly doubled"): label with the stated number if one exists;
   otherwise `value: null` + `expected_verdict: UNVERIFIABLE`. These become the abstention fixtures.
4. **Span** = the shortest contiguous substring containing the full assertion, copied verbatim.
5. **True value**: compute it yourself (DuckDB/notebook) and record it with the SQL you used.
   If the sentence is ambiguous (mean vs median? gross vs net?), record the ambiguity — it's a
   future abstention rule or a config field, not a labeling problem.
6. **When unsure how to label, write the dilemma down** in `RESULTS.md`. Every dilemma is either a
   schema improvement or an abstention rule.

Claim types for V1: `point_value` · `growth` · `comparison` · `ranking` · `share`.
If a real claim fits none of these, note it — that's schema feedback, don't force it.
