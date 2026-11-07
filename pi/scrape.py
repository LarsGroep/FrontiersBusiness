"""Keep growing the Pi database beyond Supabase's size limit.

  python -m pi.scrape --max-papers 300
  python -m pi.scrape --topic cardio-mesh --max-papers 6000     # one focused topic (see europepmc.ALL_TOPICS)

Same pipeline as the GitHub scraper (women-only query, 14 topics x 4 publication-year bands,
rule-based labeller, optional Claude check when ANTHROPIC_API_KEY is set), but each paper is
stored on the Pi with its full text and word index. No vectors are computed.
"""
from __future__ import annotations

import argparse
import collections
import json
import time

from scraper import europepmc, fulltext, label
from . import store


def run(max_papers: int, since_year: int | None = None, topic: str | None = None) -> dict:
    conn = store.connect()
    store.apply_schema(conn)
    seen = {r[0] for r in conn.execute("select id from papers").fetchall()}
    topics = {topic: europepmc.ALL_TOPICS[topic]} if topic else europepmc.DEFAULT_TOPICS
    slices = [(name, tq, band, yr) for name, tq in topics.items()
              for band, yr in europepmc.YEAR_BANDS.items()]
    per_slice = max(1, -(-max_papers // len(slices)))
    stats, labels = collections.Counter(), collections.Counter()

    for name, tq, band, yr in slices:
        if stats["added"] >= max_papers:
            break
        key = f"pi:{name}:{band}"
        start, exhausted = store.get_cursor(conn, key)
        if exhausted:
            start = "*"   # wrapped around: rescan from the top for newly published papers
        q = europepmc.build_query(since_year, tq, year_range=yr)
        try:
            # Focused runs scan the whole slice (most hits are new); the rotation reads up to 30x its quota.
            _, records, state = europepmc.search(q, max_results=10**6 if topic else per_slice * 30, start_cursor=start)
        except Exception as e:
            print(f"  ! search {key}: {e}", flush=True)
            continue
        added_here = 0

        def safe(records=records, key=key):
            """Stop this slice (cursor is saved) instead of the whole run when a result page fails to load."""
            try:
                yield from records
            except Exception as e:
                stats["page_errors"] += 1
                print(f"  ! {key}: result page failed ({type(e).__name__}); moving to the next slice", flush=True)

        try:
            for rec in safe():
                if added_here >= per_slice or stats["added"] >= max_papers:
                    break
                paper = europepmc.parse_record(rec)
                if not paper["pmcid"] or paper["id"] in seen:
                    continue
                seen.add(paper["id"])
                paper["topic"] = name
                try:
                    xml = europepmc.fetch_fulltext_xml(paper["pmcid"])
                    sections = fulltext.parse_sections(xml) if xml else []
                    methods = " ".join(t for k, _, t in sections if k == "methods")
                    results = " ".join(t for k, _, t in sections if k in ("results", "conclusion"))
                    verdict = label.rule_label(paper, methods)
                    llm = label.llm_label(paper, methods, results) if verdict["label"] != "rejected" else None
                    paper.update(label.combine(verdict, llm))
                    store.upsert_papers(conn, [paper], source="pi")
                    store.save_fulltext(conn, paper["id"], sections, bool(paper.get("commercial_use_ok")))
                    labels[paper["label"]] += 1
                    stats["added"] += 1
                    added_here += 1
                except Exception as e:
                    conn.rollback()
                    stats["errors"] += 1
                    print(f"  ! {paper['id']}: {type(e).__name__}: {str(e)[:120]}", flush=True)
                time.sleep(0.2)
        finally:
            store.save_cursor(conn, key, state["cursor"], state["scanned"], state["exhausted"])
        print(f"  {key}: +{added_here}", flush=True)

    conn.close()
    return {"added": stats["added"], "errors": stats["errors"], "page_errors": stats["page_errors"], "labels": dict(labels)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-papers", type=int, default=300)
    ap.add_argument("--since-year", type=int, default=None)
    ap.add_argument("--topic", choices=sorted(europepmc.ALL_TOPICS), default=None,
                    help="scrape only this topic (all 4 year bands) instead of the 14-topic rotation")
    a = ap.parse_args()
    print(json.dumps(run(a.max_papers, a.since_year, a.topic), indent=2))


if __name__ == "__main__":
    main()
