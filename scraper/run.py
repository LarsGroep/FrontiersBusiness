"""Scrape -> label -> chunk -> embed -> load.

python -m scraper.run --max-papers 200 [--since-year 2010] [--topic "cardiovascular"]
Writes reports/latest_run.json + reports/latest_sample.md always; loads Supabase when SUPABASE_DB_URL is set.
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db, europepmc, fulltext, label

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
DATA = ROOT / "data"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-papers", type=int, default=200, help="max NEW papers to process this run")
    ap.add_argument("--since-year", type=int, default=None)
    ap.add_argument("--topic", default=None, help="optional extra Europe PMC query, e.g. 'cardiovascular'")
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()

    started = time.time()
    query = europepmc.build_query(args.since_year, args.topic)
    print(f"Query: {query}", flush=True)

    seen: set[str] = set()
    try:
        conn = db.connect()
        if conn:
            db.apply_schema(conn)
            seen = db.existing_ids(conn)
    except Exception as e:
        import os, re as _re
        msg = str(e)
        pw = _re.search(r"://[^:]+:([^@]+)@", os.getenv("SUPABASE_DB_URL", ""))
        if pw:
            msg = msg.replace(pw.group(1), "***")
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / "latest_run.json").write_text(json.dumps({
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "db_error": f"{type(e).__name__}: {msg[:800]}",
        }, indent=2))
        print(f"DATABASE CONNECTION FAILED: {type(e).__name__}: {msg[:800]}", flush=True)
        raise SystemExit(1)
    if conn:
        print(f"Connected to Supabase, {len(seen)} papers already stored", flush=True)
    else:
        print("SUPABASE_DB_URL not set: dry run (reports + local JSONL only)", flush=True)

    # Scan up to 5x the target so re-runs move past papers we already have.
    hit_count, records = europepmc.search(query, max_results=args.max_papers * 5 + len(seen))
    print(f"Europe PMC hits for query: {hit_count}", flush=True)

    DATA.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    out_jsonl = (DATA / "papers_latest.jsonl").open("w")

    stats = collections.Counter()
    labels_count = collections.Counter()
    sections_count = collections.Counter()
    processed: list[dict] = []

    for rec in records:
        if stats["processed"] >= args.max_papers:
            break
        paper = europepmc.parse_record(rec)
        if not paper["pmcid"] or paper["id"] in seen:
            stats["skipped_existing_or_no_pmcid"] += 1
            continue
        seen.add(paper["id"])

        xml = europepmc.fetch_fulltext_xml(paper["pmcid"])
        sections = fulltext.parse_sections(xml) if xml else []
        if not xml:
            stats["no_fulltext"] += 1
        methods_text = " ".join(t for n, _, t in sections if n == "methods")
        for n, _, _ in sections:
            sections_count[n] += 1

        verdict = label.rule_label(paper, methods_text)
        llm = label.llm_label(paper, methods_text) if verdict["label"] != "rejected" else None
        verdict = label.combine(verdict, llm)
        paper.update(verdict)
        labels_count[paper["label"]] += 1

        chunks = fulltext.build_chunks(paper, sections) if paper["label"] != "rejected" else []
        if chunks and not args.no_embed:
            from .embed import embed_passages
            vecs = embed_passages([f"{paper['title']} | {c['section']}: {c['content']}" for c in chunks])
            for c, v in zip(chunks, vecs):
                c["embedding"] = v
        stats["chunks"] += len(chunks)

        if conn:
            db.upsert_paper(conn, paper, chunks)
            stats["loaded_to_db"] += 1

        out_jsonl.write(json.dumps({**paper, "n_chunks": len(chunks), "has_methods": bool(methods_text),
                                    "sections": [n for n, _, _ in sections]}) + "\n")
        processed.append({**paper, "n_chunks": len(chunks), "has_methods": bool(methods_text)})
        stats["processed"] += 1
        if stats["processed"] % 25 == 0:
            print(f"  {stats['processed']} papers | labels {dict(labels_count)}", flush=True)
        time.sleep(0.1)

    out_jsonl.close()
    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started),
        "query": query,
        "europepmc_hit_count": hit_count,
        "db_connected": bool(conn),
        "llm_verifier": any(p.get("llm_label") for p in processed),
        "stats": dict(stats),
        "labels": dict(labels_count),
        "sections_found": dict(sections_count),
        "commercial_use_ok": sum(1 for p in processed if p.get("commercial_use_ok")),
        "with_n_female": sum(1 for p in processed if p.get("n_female")),
        "study_types": dict(collections.Counter(p.get("study_type") or "unknown" for p in processed)),
        "top_journals": collections.Counter(p.get("journal") for p in processed).most_common(10),
        "years": dict(sorted(collections.Counter(p.get("pub_year") for p in processed if p.get("pub_year")).items())),
    }
    if conn:
        db.log_run(conn, query, hit_count, summary)
        summary["db_totals"] = db.db_summary(conn)
        conn.close()

    (REPORTS / "latest_run.json").write_text(json.dumps(summary, indent=2, default=str))
    write_sample(processed)
    print(json.dumps(summary, indent=2, default=str))


def write_sample(processed: list[dict]) -> None:
    """Human-readable sample for quality checking: random picks per label."""
    rnd = random.Random(42)
    by_label = collections.defaultdict(list)
    for p in processed:
        by_label[p["label"]].append(p)
    lines = ["# Quality-check sample (latest run)\n"]
    for lab, items in sorted(by_label.items()):
        lines.append(f"\n## {lab} ({len(items)} papers)\n")
        for p in rnd.sample(items, min(12, len(items))):
            lines.append(f"### {p['title']}\n")
            lines.append(f"- {p.get('journal')} ({p.get('pub_year')}) | {p.get('pmcid')} | doi:{p.get('doi')} | license: {p.get('license')}")
            lines.append(f"- study type: {p.get('study_type')} | population: {p.get('population')} | n_female: {p.get('n_female')} | chunks: {p.get('n_chunks')} | methods found: {p.get('has_methods')}")
            lines.append(f"- reasons: {p.get('label_reasons')}")
            if p.get("female_evidence"):
                lines.append(f"- evidence: \"{p['female_evidence']}\"")
            for s in (p.get("male_snippets") or [])[:3]:
                lines.append(f"- male mention: \"{s}\"")
            lines.append(f"- abstract: {(p.get('abstract') or '')[:600]}\n")
    (REPORTS / "latest_sample.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
