# Agent tools for the women-only evidence database

Base URL: `https://larsfrontiers2.vercel.app`. The tools are read-only and need no key. CORS is open.

The database is a lean catalogue of studies with only women/girls as participants. Each study has metadata, a women-only label with the supporting quote, a structured evidence record (once Claude extraction runs) and up to 4 passages. Full text is fetched on demand.

## Tools (Anthropic tool-use format)

```json
[
  {
    "name": "search_evidence",
    "description": "Search peer-reviewed studies in which every participant was a woman or girl. Use clinical terms and alternatives joined with OR, e.g. '\"hot flushes\" OR vasomotor'. Returns studies with design, number of women, population, best-matching passages and a structured evidence record when available.",
    "input_schema": {
      "type": "object",
      "properties": {
        "q": {"type": "string", "description": "Web-search syntax: words (AND), OR between alternatives, \"quoted phrases\", -exclude"},
        "k": {"type": "integer", "description": "Number of studies, 1-25 (default 10)"},
        "include_probable": {"type": "boolean", "description": "Also include probably-women-only studies"},
        "min_year": {"type": "integer"},
        "topics": {"type": "string", "description": "Comma list: cardiovascular, cancer, mental-health, metabolic, bone-exercise, medication, autoimmune, menopause, pregnancy, reproductive, infection, pain-sleep, social, ageing"},
        "population": {"type": "string", "description": "Comma list of life-stage terms to boost, e.g. postmenopaus, pregnan, adolescen"},
        "open_licence_only": {"type": "boolean", "description": "Only CC-BY/CC0 studies (reusable commercially)"}
      },
      "required": ["q"]
    }
  },
  {
    "name": "read_paper",
    "description": "Read one study in full by id (from search_evidence): metadata, women-only evidence, structured evidence record and, for openly licensed papers, the full text by section.",
    "input_schema": {
      "type": "object",
      "properties": {"id": {"type": "string", "description": "e.g. PMC1234567"}, "max_chars": {"type": "integer", "description": "Full-text length cap (default 60000)"}},
      "required": ["id"]
    }
  },
  {
    "name": "evidence_stats",
    "description": "Size and make-up of the database: papers, verified, by topic, by decade, records with evidence.",
    "input_schema": {"type": "object", "properties": {}}
  }
]
```

## HTTP mapping
| Tool | Request |
|---|---|
| search_evidence | `GET /api/search?q=...&k=10&population=postmenopaus` (or POST JSON) |
| read_paper | `GET /api/paper?id=PMC1234567` |
| evidence_stats | `GET /api/stats` |

## Notes for agent design
- **Plan:** search broadly with several OR-queries, read the 3–5 strongest papers (trials and large cohorts first), and then answer with citations (id + DOI).
- **Every study is women-only**, so you don't need "women" in queries. Use `population` to prefer a life stage.
- **Licences:** `open_licence: false` papers return abstract + link only, so don't reproduce their full text.
- **`evidence` fields:** population, age_range, country, study_type, intervention_or_exposure, comparator, outcomes, key_findings, effect_direction, limitations, n_female.
