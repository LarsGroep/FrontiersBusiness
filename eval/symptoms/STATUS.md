
## 9 Nov midday: locked symptom test set
- **Research outcome (Lars chose points 1+2):** compare our rules against two free precomputed taggers, NCBI **PubTator 3.0** (MeSH-normalised disease tags) and **Europe PMC annotations**, on a locked, human-labelled test set before changing anything. Next candidates after that: SemMedDB symptom→condition predications (needs licence check), then participant-count extraction for women-only.
- **Workflow "Symptom test set"** (`.github/workflows/symptom-eval.yml`, `pi/symptom_eval.py`, folder `eval/symptoms/`):
  - The lock `papers.json` holds 1,309 women-only CV abstracts with a PMID, in a fixed hashed order; later runs reuse exactly these.
  - 1,259 candidates in total. 953 are auto-"no" because the term isn't a patient symptom (MeSH Signs & Symptoms includes obesity/overweight/weight gain, proteinuria, labour pain…). **306 need a human.**
  - Hits per extractor (raw / after our filters): ours 266 / 108, PubTator 1,096 / 66, Europe PMC 93 / 15.
  - Who found the 306: ours only 118, ours+PubTator 90, PubTator only 39, ours+EPMC 38, all three 20, EPMC+PubTator 1. Europe PMC adds almost nothing new for abstracts: 752 of its tags were in titles/full text and couldn't be placed in the abstract.
- **Labelling page (blind, two annotators):** https://claude.ai/artifact/LKMYzyhDTm3TqpYMBhgqSx. Each person's labels live in their own `labels/<id>` doc; contributors can't write anyone else's (checked). The second annotator needs contributor access via Share.
- **Scoring:** export the labels to `eval/symptoms/labels.json`; the push runs `score`, which writes `scores.json` (precision, pooled recall with 95% intervals, Cohen's kappa).

## 9 Nov 13:30: first scores ("studied in these women")
- Labels: Lars 48, agent 1 all 306, agent 2 the other 258. Two Claude agents agree 250/258 (kappa 0.91, inflated because they're the same model). Lars and agent 1 agree 37/48 (kappa 0.24); 8 of the 11 differences are Lars "unsure", and only 3 are real yes/no conflicts. 19 items are still unsettled.
- Under this question our plain word match does best: precision 84%, pooled recall 89%. Our "finding" filter (97% / 43%) was built for the stricter question and is too strict here. PubTator patient-symptom tags: 80% / 42%. Ours + PubTator: 82% / 92%. Europe PMC: recall 17% (drop it).
- The negation filter costs recall (89% to 82%) because "with and without X" comparisons count as yes.
