# Symptom test set (locked)

Fixed sample of women-only cardiovascular abstracts used to measure symptom extraction. Built by the
"Symptom test set" workflow (`pi/symptom_eval.py`).

- `papers.json` — the lock: which papers are in the set. Never regenerate; later rule versions are scored on these.
- `candidates.json` — every hit from our rules, PubTator 3.0 and Europe PMC, merged per sentence.
- `labels.json` — `{annotator: {candidate_id: "yes" | "no" | "unsure"}}`, labelled independently.
- `gold.json` — optional `{candidate_id: "yes" | "no"}` settling disagreements.
- `scores.json` — precision, pooled recall (with 95% Wilson intervals) and Cohen's kappa. Written on every label push.

**Label "yes"** when the sentence reports that the women studied had or reported this symptom. **"no"** for background,
aims, definitions, outcome names, negated mentions, other people (infants, partners) or a word that isn't a symptom.
