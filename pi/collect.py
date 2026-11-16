"""Continuous women-only collection on the Pi (herevidence-collect.service).

Works through the topic list below, a batch per topic at a time, so every area keeps growing instead of one
topic finishing first. Each topic resumes from its saved Europe PMC cursor (pi/scrape.py); a finished topic is
rescanned from the top for newly published papers. When a whole round adds nothing, it waits ROUND_PAUSE before
the next round. Stopping and starting the service at any moment is safe (the guard does this on heat or memory).

  python -m pi.collect            # forever
  python -m pi.collect --once     # one round, then exit
"""
from __future__ import annotations

import argparse
import json
import time

from . import scrape

# Order = priority. Cardiovascular first (the pilot), then the thin areas from the 7 Nov analysis.
TOPICS = ["cardio-wide", "neuro-mesh", "autoimmune-mesh", "respiratory-mesh", "digestive-mesh", "cardio-mesh"]
BATCH = 400                 # papers per topic per round (100 per publication-year band)
ROUND_PAUSE = 6 * 3600      # seconds to wait after a round that found nothing new


def one_round() -> dict:
    out = {}
    for t in TOPICS:
        t0 = time.time()
        try:
            r = scrape.run(BATCH, topic=t)
        except Exception as e:  # noqa: BLE001 - one failing topic must not stop the others
            r = {"added": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        r["seconds"] = round(time.time() - t0)
        out[t] = r
        print(json.dumps({"topic": t, **r}), flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        res = one_round()
        added = sum(r.get("added", 0) for r in res.values())
        print(json.dumps({"round_added": added, "at": time.strftime("%F %T")}), flush=True)
        if a.once:
            break
        if added == 0:
            time.sleep(ROUND_PAUSE)


if __name__ == "__main__":
    main()
