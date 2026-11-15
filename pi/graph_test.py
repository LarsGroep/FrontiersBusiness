"""GraphRAG test on our data: graph vs vector vs hybrid retrieval (pi/graph.py), women-only cardiovascular papers.

  python -m pi.graph_test run   --out eval/graphrag     # build the graph once, run both question sets, export the
                                                        # graph for the website, write a blind judging pool
  python -m pi.graph_test score --dir eval/graphrag     # P@10 and nDCG@10 per question set from judgments.json

Question sets: "dictionary" uses symptom words the dictionary knows; "free text" is how a GP would type it.
Judgments are keyed "question|paper" and reused across runs, so only new papers need judging.
v1 (15 Nov, abstracts only) is kept as runs_v1_abstracts.json for comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os

import numpy as np

from .graph import EvidenceGraph

AREA = "C14 Cardiovascular Diseases"
K = 10
QUESTIONS = {
    "dictionary": ["chest pain", "shortness of breath", "fatigue", "palpitations", "leg swelling",
                   "dizziness or fainting", "headache", "fatigue and shortness of breath", "chest pain and nausea",
                   "palpitations and dizziness"],
    "free text": ["52-year-old woman with pressure on her chest when climbing stairs",
                  "she gets out of breath easily and feels exhausted all the time",
                  "episodes of her heart racing at night",
                  "swollen ankles in late pregnancy",
                  "fainted twice this month, feels lightheaded when standing up",
                  "pain in the jaw and upper back during exertion",
                  "severe headaches and blurred vision after giving birth",
                  "unusual tiredness and nausea, no chest pain",
                  "cold sweats and indigestion-like discomfort",
                  "irregular heartbeat and dizziness during menopause"],
}


def run(out: str) -> dict:
    os.makedirs(out, exist_ok=True)
    g = EvidenceGraph(AREA, with_sections=True)
    export = g.export("web/graph/cv.json")
    runs, conds = {}, {}
    for qset, qs in QUESTIONS.items():
        for q in qs:
            r = g.search(q, K)
            runs[q] = {"set": qset, **r}
            conds[q] = g.conditions([l["symptom"] for l in r["links"]])
    judged = {}
    jf = os.path.join(out, "judgments.json")
    if os.path.exists(jf):
        judged = json.load(open(jf))
    pool = {}
    for q, r in runs.items():
        for m in ("vector", "graph", "hybrid"):
            for pid in r[m]:
                key = f"{q}|{pid}"
                if key not in judged:
                    p = g.papers[pid]
                    pool[key] = {"key": key, "query": q, "paper_id": pid, "title": p["title"],
                                 "abstract": p["abstract"][:1500]}
    items = sorted(pool.values(), key=lambda x: hashlib.sha1(x["key"].encode()).hexdigest())
    json.dump(runs, open(os.path.join(out, "runs.json"), "w"), indent=1)
    json.dump(conds, open(os.path.join(out, "conditions.json"), "w"), indent=1)
    json.dump(items, open(os.path.join(out, "pool_new.json"), "w"), indent=1, ensure_ascii=False)
    stats = {"papers": len(g.ids), "export": export, "to_judge": len(items),
             "links": {q: r["links"] for q, r in runs.items()}}
    json.dump(stats, open(os.path.join(out, "stats.json"), "w"), indent=1)
    return {k: v for k, v in stats.items() if k != "links"}


def score(d: str) -> dict:
    runs = json.load(open(os.path.join(d, "runs.json")))
    judg = json.load(open(os.path.join(d, "judgments.json")))
    out = {}
    for qset in QUESTIONS:
        out[qset] = {}
        for m in ("vector", "graph", "hybrid"):
            p10, nd = [], []
            for q, r in runs.items():
                if r["set"] != qset:
                    continue
                g = [judg.get(f"{q}|{p}", 0) for p in r[m]] + [0] * (K - len(r[m]))
                ideal = sorted([v for k, v in judg.items() if k.split("|")[0] == q], reverse=True)[:K]
                dcg = sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(g))
                idcg = sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(ideal)) or 1
                p10.append(sum(1 for x in g if x >= 1) / K)
                nd.append(dcg / idcg)
            out[qset][m] = {"p10": round(float(np.mean(p10)), 3), "ndcg10": round(float(np.mean(nd)), 3)}
    json.dump(out, open(os.path.join(d, "scores.json"), "w"), indent=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["run", "score"])
    ap.add_argument("--out", "--dir", dest="dir", default="eval/graphrag")
    a = ap.parse_args()
    print(json.dumps(run(a.dir) if a.step == "run" else score(a.dir), indent=1))


if __name__ == "__main__":
    main()
