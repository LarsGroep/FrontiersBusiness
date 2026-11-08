"""Apply newer labelling rules to papers already in the Pi database (no re-download needed).

  python -m pi.relabel            # dry run: prints how many papers would change, with examples
  python -m pi.relabel --apply    # write the changes

Current rule: "verified" papers whose subjects are infants, foetuses or birth tissue (perinatal studies tagged
"Female" because of the mother) become "probable" with reason "infant_or_fetal_subjects".
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from scraper.label import infant_subjects

from . import store


def run(apply: bool) -> dict:
    conn = store.connect()
    rows = conn.execute("""select p.id, p.title, p.mesh_terms, p.abstract, p.topic,
                                  (select string_agg(s.text, ' ') from sections s where s.paper_id = p.id and s.kind = 'methods')
                           from papers p where p.label = 'female_only_verified'""").fetchall()
    hits, by_topic = [], Counter()
    for pid, title, mesh, abstract, topic, methods in rows:
        if infant_subjects({"title": title, "mesh_terms": mesh, "abstract": abstract}, methods or ""):
            hits.append((pid, title))
            by_topic[topic] += 1
    if apply and hits:
        with conn.cursor() as c:
            c.executemany("""update papers set label = 'female_only_probable',
                                    label_reasons = array_append(coalesce(label_reasons, '{}'), 'infant_or_fetal_subjects')
                             where id = %s and label = 'female_only_verified'""", [(pid,) for pid, _ in hits])
        store.set_meta(conn, "relabel_infant_rule", json.dumps({"changed": len(hits)}))
        conn.commit()
    conn.close()
    return {"verified_checked": len(rows), "downgraded": len(hits), "applied": apply,
            "by_topic": dict(by_topic.most_common()), "examples": [t[:100] for _, t in hits[:12]]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    print(json.dumps(run(ap.parse_args().apply), indent=1))


if __name__ == "__main__":
    main()
