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

## Running
- **GitHub Actions → "Scrape women-only papers" → Run workflow.** Inputs: max papers, since year, topic.
- **Weekly**: runs automatically every Monday and only adds new papers.
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
