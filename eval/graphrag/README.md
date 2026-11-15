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
