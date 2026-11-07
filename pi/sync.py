"""Fill the Pi database.

  python -m pi.sync catalogue            # copy all papers (metadata, labels, abstracts) from Supabase
  python -m pi.sync fulltext --limit 0   # download + index full text for papers that don't have it (0 = all)
  python -m pi.sync status               # counts

Resumable: every step only does what is missing, so it can be stopped and restarted at any time.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from scraper import europepmc, fulltext
from . import store

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://jvlrbsusjvuxsgijgxpb.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_aA-czPmRvwj2QODVXOUS3A_-AHkUK7F")
CATALOGUE_COLS = ",".join(store.PAPER_FIELDS)


def catalogue_from_pi(url: str, token: str) -> dict:
    """Copy the catalogue from a Pi API (/catalogue), used by the GitHub analysis run: the Pi is the source of truth."""
    conn = store.connect()
    store.apply_schema(conn)
    total = 0
    for rows in _pi_pages(url, token, 200):
        store.upsert_papers(conn, rows, source="pi")
        total += len(rows)
        print(f"  catalogue (Pi): {total} papers", flush=True)
    conn.close()
    return {"catalogue_rows": total, "source": "pi"}


def _pi_pages(url: str, token: str, limit: int):
    """Yield pages from a keyset-paged Pi endpoint, retrying dropped tunnel connections."""
    after = ""
    while True:
        for attempt in range(8):
            try:
                r = requests.get(url, params={"after": after, "limit": limit}, headers={"x-api-key": token}, timeout=180)
                r.raise_for_status()
                page = r.json()
                break
            except Exception as e:   # incl. SSL EOF from the tunnel mid-transfer, which is not a RequestException
                if attempt == 7:
                    raise
                print(f"  retry ({e.__class__.__name__})", flush=True)
                time.sleep(5 * (attempt + 1))
        yield page["rows"]
        if not page["next"]:
            return
        after = page["next"]


def vectors_from_pi(url: str, token: str) -> dict:
    """Copy stored embeddings from the Pi (/vectors) for papers present here, so only new papers get embedded."""
    conn = store.connect()
    conn.execute((Path(__file__).resolve().parent / "schema_analysis.sql").read_text()); conn.commit()
    total = kept = 0
    for rows in _pi_pages(url, token, 500):
        with conn.cursor() as c:
            c.executemany("""insert into paper_vec (paper_id, model, embedding)
                             select %s, %s, %s::vector where exists (select 1 from papers where id = %s)
                             on conflict (paper_id) do nothing""",
                          [(r["id"], r["model"], r["embedding"], r["id"]) for r in rows])
        conn.commit()
        total += len(rows)
        print(f"  vectors (Pi): {total}", flush=True)
    kept = conn.execute("select count(*) from paper_vec").fetchone()[0]
    conn.close()
    return {"vectors_read": total, "vectors_kept": kept}


def catalogue(page_size: int = 1000) -> dict:
    """Copy every paper row from Supabase (read-only public key), keyset-paginated by id.

    With PI_CATALOGUE_URL + PI_API_TOKEN set (GitHub analysis run), the Pi's catalogue is copied instead.
    """
    if os.getenv("PI_CATALOGUE_URL") and os.getenv("PI_API_TOKEN"):
        return catalogue_from_pi(os.environ["PI_CATALOGUE_URL"], os.environ["PI_API_TOKEN"])
    conn = store.connect()
    store.apply_schema(conn)
    last, total = "", 0
    while True:
        params = {"select": CATALOGUE_COLS, "order": "id.asc", "limit": str(page_size)}
        if last:
            params["id"] = f"gt.{last}"
        for attempt in range(5):
            try:
                r = requests.get(f"{SUPABASE_URL}/rest/v1/papers", params=params,
                                 headers={"apikey": SUPABASE_KEY}, timeout=60)
                r.raise_for_status()
                rows = r.json()
                break
            except requests.RequestException as e:
                if attempt == 4:
                    raise
                print(f"  retry ({e.__class__.__name__})", flush=True)
                time.sleep(3 * (attempt + 1))
        if not rows:
            break
        store.upsert_papers(conn, rows, source="supabase")
        total += len(rows)
        last = rows[-1]["id"]
        print(f"  catalogue: {total} papers", flush=True)
    store.set_meta(conn, "catalogue_synced_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    conn.close()
    return {"catalogue_rows": total}


def _download(paper_id: str, pmcid: str):
    xml = europepmc.fetch_fulltext_xml(pmcid) if pmcid else None
    return paper_id, (fulltext.parse_sections(xml) if xml else [])


def fetch_fulltext(limit: int = 0, workers: int = 4) -> dict:
    """Download, parse and index full text for papers still marked 'pending' (best evidence first)."""
    conn = store.connect()
    rows = conn.execute(
        "select id, pmcid, coalesce(commercial_use_ok, false) from papers where fulltext_status='pending' "
        "order by case label when 'female_only_verified' then 0 when 'female_only_probable' then 1 else 2 end, id"
        + (" limit %s" % int(limit) if limit else "")).fetchall()
    open_by_id = {r[0]: r[2] for r in rows}
    stats = {"todo": len(rows), "ok": 0, "none": 0, "errors": 0, "chars": 0}
    started = time.time()
    # A few parallel downloads keep the load on Europe PMC polite (~2-4 requests/second).
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download, pid, pmcid): pid for pid, pmcid, _ in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            pid = futures[fut]
            try:
                _, sections = fut.result()
                n = store.save_fulltext(conn, pid, sections, open_by_id[pid])
                stats["ok" if n else "none"] += 1
                stats["chars"] += n
            except Exception as e:
                conn.rollback()
                store.mark_fulltext_error(conn, pid)
                stats["errors"] += 1
                print(f"  ! {pid}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            if i % 100 == 0:
                rate = i / max(1, time.time() - started)
                left = (len(rows) - i) / max(rate, 0.01) / 60
                print(f"  full text: {i}/{len(rows)}  ({rate:.1f}/s, ~{left:.0f} min left)", flush=True)
    store.set_meta(conn, "fulltext_synced_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    conn.close()
    return stats


def status() -> dict:
    conn = store.connect()
    row = conn.execute("""
        select count(*),
               count(*) filter (where label='female_only_verified'),
               count(*) filter (where fulltext_status='ok'),
               count(*) filter (where fulltext_status='pending'),
               count(*) filter (where fulltext_status in ('none','error')),
               (select count(*) from sections),
               pg_size_pretty(pg_database_size(current_database()))
        from papers""").fetchone()
    keys = ["papers", "verified", "fulltext_ok", "fulltext_pending", "fulltext_missing", "sections", "db_size"]
    out = dict(zip(keys, row))
    out["catalogue_synced_at"] = store.get_meta(conn, "catalogue_synced_at")
    conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["catalogue", "fulltext", "status", "vectors"])
    ap.add_argument("--limit", type=int, default=0, help="fulltext: max papers this run (0 = all pending)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.step == "catalogue":
        out = catalogue()
    elif a.step == "vectors":
        out = vectors_from_pi(os.environ["PI_VECTORS_URL"], os.environ["PI_API_TOKEN"])
    elif a.step == "fulltext":
        out = fetch_fulltext(a.limit, a.workers)
    else:
        out = status()
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
