# GraphRAG test (15 Nov 2026)

Light GraphRAG (no LLM: papers + MeSH conditions + dictionary-extracted symptoms, abstracts only) vs plain vector
retrieval (bge-small) vs hybrid (RRF), on 3,967 women-only cardiovascular papers, 10 GP-style symptom queries.
Top 10 per method pooled (177 papers) and judged blind by an independent model judge (0/1/2).

| Method | P@10 (relevance ≥1) | nDCG@10 | Highly relevant (2) in top 10s |
|---|---|---|---|
| Vector | 0.46 | 0.57 | 13 |
| Graph | 0.74 | 0.88 | 18 |
| Hybrid | 0.72 | 0.83 | 18 |

Caveats: one model judge, no human check yet; queries use words the symptom dictionary knows (real GP wording
varies, which favours vector search); 10 queries; the graph is sparse (295 symptom links, abstracts only).
The judge found 2 pooled papers that include men (PMC9898364, PMC10607223): label errors to fix.
`conditions.json` compares the symptom→condition answer of the graph with what vector top-50 papers imply.

## Run 2 (15 Nov evening): full-text graph + free-text GP questions

The graph now also uses results/conclusion sections (Europe PMC full text, cached): 1,018 symptom links across 590
papers (was 295), 55 symptoms, 40 conditions, 211 edges. It is exported to `web/graph/cv.json` for the `/graph`
debug page. 10 dictionary-word questions + 10 free-text GP questions; 239 new papers judged blind (same rules).

| Questions | Vector P@10 / nDCG | Graph P@10 / nDCG | Hybrid P@10 / nDCG |
|---|---|---|---|
| Dictionary words | 0.46 / 0.53 | 0.58 / 0.64 | 0.60 / 0.68 |
| Free text (GP wording) | 0.17 / 0.41 | 0.20 / 0.34 | 0.30 / 0.60 |

- **Hybrid is the best default:** best or joint-best on both sets.
- **Free-text linking is the weak spot:** 4 of 10 free-text questions linked to no symptom ("pressure on her chest",
  "out of breath … exhausted", "swollen ankles", "fainted … lightheaded"); "irregular heartbeat" and "upper back pain"
  were missed. Fix: more lay terms in the dictionary and a calibrated embedding threshold, then test on NEW questions
  (these 10 are now seen and must not be used for tuning).
- **Graph precision fell from 0.74 (abstract graph) to 0.58** on the same questions. Part of this is a measurement
  bias: the judge sees only the abstract, so papers linked through a results-section sentence look irrelevant. The
  next judging round should show the linking sentence.
- Absolute free-text precision is low because few women-only cardiovascular papers study these symptoms: an evidence
  gap in itself.

## Run 3 (16 Nov): everyday-word linking + 20 fresh questions (written blind, locked before the changes)

Graph now 4,049 papers (full text, cached). 397 new pooled papers judged blind; the judge also saw the sentences that
link a paper to the question's symptoms. 813 judgments in total.

| Questions | Vector P@10 / nDCG | Graph P@10 / nDCG | Hybrid P@10 / nDCG |
|---|---|---|---|
| Dictionary words (10) | 0.46 / 0.53 | 0.58 / 0.64 | 0.60 / 0.68 |
| Free text, seen (10; lay terms partly drafted after seeing them) | 0.17 / 0.24 | 0.44 / 0.58 | 0.43 / 0.55 |
| **Fresh, unseen (20)** | **0.17 / 0.27** | **0.35 / 0.57** | **0.37 / 0.57** |

- Fresh questions: 15/20 link to at least one symptom. Linked: graph 0.47 vs vector 0.15. Not linked (5): graph finds
  nothing, hybrid falls back to vector (0.24). Hybrid is the robust default.
- Unlinked wording: "wiped out, gets puffed", "SOB lying flat", "tight feeling in her chest", "raised blood pressure
  readings", "hot flushes and pounding heartbeat". These are now seen; a later round needs new questions again.

## XGBoost tree (16 Nov build)
586 papers with symptoms, 11 condition groups. Held-out: top-1 34% (baseline 18%), top-3 64%, log-loss 2.00
(baseline 2.19), ECE 0.12. Distilled tree fidelity 59%. Strongest features: pregnancy, oedema, dyspnoea, cohort design,
chest pain.
