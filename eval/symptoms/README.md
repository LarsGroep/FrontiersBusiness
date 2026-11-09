# Symptom test set (locked)

Fixed sample of women-only cardiovascular abstracts used to measure symptom extraction. Built by the
"Symptom test set" workflow (`pi/symptom_eval.py`).

- `papers.json` — the lock: which papers are in the set. Never regenerate; later rule versions are scored on these.
- `candidates.json` — every hit from our rules, PubTator 3.0 and Europe PMC, merged per sentence.
- `labels.json` — `{annotator: {candidate_id: "yes" | "no" | "unsure"}}`, labelled independently.
- `gold.json` — optional `{candidate_id: "yes" | "no"}` settling disagreements.
- `scores.json` — precision, pooled recall (with 95% Wilson intervals) and Cohen's kappa. Written on every label push.

**Labelling rules:** see `GUIDE.md`. Question (Lars, 9 Nov): *does this study measure, study or describe this symptom in its own women?* No-effect results count as yes. This replaced the earlier, stricter "reported as present" wording.
