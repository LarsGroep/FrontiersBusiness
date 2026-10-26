# FrontiersBusiness: women-only evidence dataset + RAG

This project collects peer-reviewed open-access studies whose **participants were women only**. It labels each study, splits it into sections, embeds the text and stores it in Supabase (pgvector) so it can be searched as a RAG.

## Pipeline
1. **Search**: Europe PMC (`scraper/europepmc.py`) for MeSH `Humans` + `Female`, NOT `Male`, open access with full text. Reviews, editorials and comments are excluded.
2. **Full text**: the JATS XML is split into sections (abstract / methods / results / discussion / conclusion) by `scraper/fulltext.py`.
3. **Label** (`scraper/label.py`):
   - `female_only_verified`: MeSH is clean and no male participant terms appear in the title, abstract or methods.
   - `female_only_probable`: MeSH is clean but male terms appear in the text. Check these by hand or with the LLM.
   - `female_only_unverified`: no methods section was found.
   - `rejected`: tagged Male or missing the Humans/Female tags.
   - Optional: if an `ANTHROPIC_API_KEY` secret is set, Claude reads the abstract and methods and confirms or rejects each paper.
4. **Embed**: BAAI/bge-small-en-v1.5 (384 dims) runs locally via fastembed, so no API key is needed.
5. **Load**: `papers` and `chunks` tables, plus a `match_chunks()` search function (`db/schema.sql`). The schema is applied automatically.

## Search app (web/)
The search page is a static page plus two optional Vercel functions. Live at https://larsfrontiers2.vercel.app
- **Keyword search** and **"Start from my symptoms"** (symptoms, age, life stage, conditions, medicines) both call `search_evidence()` in Supabase directly with the public read-only key.
- `search_evidence()` is a hybrid search. It combines full-text matching (stemmed, phrases, OR) with semantic neighbours of the best keyword hits, using reciprocal-rank fusion, a cap of 2 passages per paper, and a boost for studies that match the user's life stage.
- Everyday words are translated to clinical terms by a built-in word list (e.g. "period pain" → dysmenorrhea).
- With `ANTHROPIC_API_KEY` set in the Vercel project, `/api/expand` uses Claude for that translation and `/api/answer` writes a cited plain-language summary.
- Deploy: Vercel → Add New Project → import this repo → Root Directory `web` → Deploy.

## Running
- **Fill database (parallel by topic)**: runs every 6 hours and on pushes to `scraper/`/`db/`. A setup job applies the schema, then 14 topic jobs (6 at a time) each resume where the last run stopped. Filling pauses at `DB_SIZE_LIMIT_MB` (400 MB, Supabase free plan ≈ 2,500 papers). Raise it after upgrading the plan.
- **Scrape women-only papers (single run)**: manual one-off runs from the Actions tab.
- **Reports**: each run commits `reports/latest_run.json`, `reports/latest_sample.md` (a quality-check sample) and `reports/latest_papers.jsonl`.

### Required secret
`SUPABASE_DB_URL`: Supabase dashboard → Connect → **Session pooler** connection string, with your DB password filled in. Without this secret, runs are dry runs that produce reports only.

Optional: `ANTHROPIC_API_KEY` turns on the LLM verifier.

## Asking questions
```bash
pip install -r requirements.txt
export SUPABASE_URL=https://jvlrbsusjvuxsgijgxpb.supabase.co
export SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
python -m rag.ask "Does resistance training improve bone density in postmenopausal women?"
```

## Licensing
`commercial_use_ok` is true only for CC-BY / CC0 papers. Filter on it before serving full text in a commercial product.

## Quality check log (manual review, 26 Oct 2026)
| Labeller | Papers reviewed | "Verified" that are really women-only participant data | Notes |
|---|---|---|---|
| v1 (MeSH + male-word scan) | 60 | ~53% (18–19 of 35) | Essays, cell-line work, database builds and mixed-sex trials slipped through |
| v2 (+ methods must mention women, mixed-% detection, animal rejection) | 150 | ~91% (~115 of 127) | ~85% of papers were pregnancy/maternal (ranking bias) |
| v3 (+ 14-topic rotation, staff-interview flag, non-primary rejection) | 140 | ~95% (~98 of 103) | Balanced across topics; remaining misses: guidance papers, lab studies with small patient samples, child-outcome DHS analyses |

Known limits: `n_female` is regex-extracted and sometimes wrong. About half of the "probable" papers are actually fine (held back conservatively). Adding the `ANTHROPIC_API_KEY` secret turns on the LLM verifier, which fixes both.
