"""Scrape -> label -> chunk -> embed -> load.

python -m scraper.run --max-papers 200 [--since-year 2010] [--topic "cardiovascular"] [--topic-index 3]
python -m scraper.run --mode setup     # apply schema + purge stale labels (run once before parallel jobs)
python -m scraper.run --mode report    # write reports/db_status.json
Writes reports/latest_run.json + reports/latest_sample.md always; loads Supabase when SUPABASE_DB_URL is set.
"""
from __future__ import annotations

import argparse
import os
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
    ap.add_argument("--topic", default=None, help="single Europe PMC topic query, e.g. 'cardiovascular'; default rotates DEFAULT_TOPICS")
    ap.add_argument("--topic-index", type=int, default=None, help="run only DEFAULT_TOPICS[i] (parallel matrix jobs)")
    ap.add_argument("--mode", choices=["all", "setup", "scrape", "report"], default="all",
                    help="all = setup + scrape; scrape skips schema changes (safe to run in parallel)")
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args()

    started = time.time()
    if args.topic:
        topics = [(args.topic, args.topic)]
    elif args.topic_index is not None:
        topics = [list(europepmc.DEFAULT_TOPICS.items())[args.topic_index]]
    else:
        topics = list(europepmc.DEFAULT_TOPICS.items())
    quota = max(1, -(-args.max_papers // len(topics)))  # ceil: papers per topic
    # Each topic is split over publication-year bands (unless a year filter was given).
    bands = [(None, None)] if args.since_year else list(europepmc.YEAR_BANDS.items())
    slice_quota = max(1, -(-quota // len(bands)))
    slices = [(name, tq, band, yr) for name, tq in topics for band, yr in bands]
    query = europepmc.build_query(args.since_year, None)
    print(f"Base query: {query}\n{len(topics)} topic(s), up to {quota} new papers each", flush=True)

    seen: set[str] = set()
    try:
        conn = db.connect()
        if conn and args.mode in ("all", "setup"):
            db.apply_schema(conn)
            m = db.maintenance(os.environ["SUPABASE_DB_URL"])
            print(f"Storage maintenance: {m}", flush=True)
            purged = db.purge_stale(conn, label.LABEL_VERSION)
            if purged:
                print(f"Purged {purged} papers labelled by an older labeller", flush=True)
        if conn and args.mode in ("setup", "report"):
            REPORTS.mkdir(exist_ok=True)
            status = db.db_status(conn)
            (REPORTS / "db_status.json").write_text(json.dumps(status, indent=2, default=str))
            print(json.dumps(status, indent=2, default=str))
            conn.close()
            return
        if conn:
            limit = int(os.getenv("DB_SIZE_LIMIT_MB", "400"))
            size = db.db_size_mb(conn)
            if size >= limit:
                print(f"Database is {size} MB (limit {limit} MB): not adding papers. "
                      f"Raise DB_SIZE_LIMIT_MB after upgrading the Supabase plan.", flush=True)
                conn.close()
                return
            seen = db.existing_ids(conn)
    except Exception as e:
        import re as _re
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

    hit_count = 0
    topic_done = collections.Counter()
    topic_hits: dict[str, int] = {}

    def records():
        """Yield (topic, record) per topic until that topic's quota of NEW papers is processed.

        Resumes each topic where the previous run stopped (scrape_cursors) and saves the new position.
        """
        nonlocal hit_count
        for name, tq, band, yr in slices:
            q = europepmc.build_query(args.since_year, tq, year_range=yr)
            key = f"{name}:{band}" if band else name
            start, exhausted = db.get_cursor(conn, key) if conn else ("*", False)
            if exhausted:
                start = "*"  # wrapped around: rescan from the top to pick up newly published papers
            n, it, state = europepmc.search(q, max_results=quota * 20, start_cursor=start)
            topic_hits[name] = n
            hit_count += n
            print(f"Topic [{key}]: {n} hits, resuming at {'start' if start == '*' else 'saved cursor'}", flush=True)
            band_quota = topic_done[name] + slice_quota
            try:
                for rec in it:
                    if topic_done[name] >= min(quota, band_quota):
                        break
                    yield name, rec
            finally:
                if conn:
                    db.save_cursor(conn, key, state["cursor"], state["scanned"], state["exhausted"])

    DATA.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    out_jsonl = (DATA / "papers_latest.jsonl").open("w")

    stats = collections.Counter()
    labels_count = collections.Counter()
    sections_count = collections.Counter()
    processed: list[dict] = []

    gen = records()
    for topic, rec in gen:
        if stats["processed"] >= args.max_papers:
            break
        paper = europepmc.parse_record(rec)
        paper["topic"] = topic
        if not paper["pmcid"] or paper["id"] in seen:
            stats["skipped_existing_or_no_pmcid"] += 1
            continue
        seen.add(paper["id"])

        try:
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
            if not paper.get("commercial_use_ok"):
                # Licence forbids commercial reuse (CC-BY-NC/ND or unknown): store the abstract only.
                chunks = [c for c in chunks if c["section"] == "abstract"]
            if chunks and not args.no_embed:
                from .embed import embed_passages
                vecs = embed_passages([f"{paper['title']} | {c['section']}: {c['content']}" for c in chunks])
                for c, v in zip(chunks, vecs):
                    c["embedding"] = v
            stats["chunks"] += len(chunks)

            if conn:
                db.upsert_paper(conn, paper, chunks)
                stats["loaded_to_db"] += 1

        except Exception as e:  # one bad paper (parse error, write race) must not stop the whole topic
            stats["errors"] += 1
            print(f"  ! skipped {paper['id']}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            if conn:
                conn.rollback()
            continue

        out_jsonl.write(json.dumps({**paper, "n_chunks": len(chunks), "has_methods": bool(methods_text),
                                    "sections": [n for n, _, _ in sections]}) + "\n")
        processed.append({**paper, "n_chunks": len(chunks), "has_methods": bool(methods_text)})
        stats["processed"] += 1
        topic_done[topic] += 1
        if stats["processed"] % 25 == 0:
            print(f"  {stats['processed']} papers | labels {dict(labels_count)}", flush=True)
        time.sleep(0.1)

    gen.close()  # runs the generator's finally: saves the cursor of the topic in progress
    out_jsonl.close()
    summary = {
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started),
        "query": query,
        "europepmc_hit_count": hit_count,
        "topics": {t: {"hits": topic_hits.get(t), "processed": topic_done[t],
                       "verified": sum(1 for p in processed if p.get("topic") == t and p["label"] == "female_only_verified")}
                   for t, _ in topics},
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
