"""GraphRAG test: graph retrieval vs vector retrieval vs hybrid, on women-only cardiovascular papers.

  python -m pi.graph_test run   --out eval/graphrag     # retrieve, write runs + a blind judging pool
  python -m pi.graph_test score --dir eval/graphrag     # P@10, nDCG@10 from judgments.json

The "light GraphRAG" graph has no language model in it: nodes are papers, MeSH conditions (paper_area) and symptoms
(pi/symptoms.py dictionary, not negated); edges are paper-has-symptom and paper-has-condition.
  vector  cosine similarity of the bge-small query embedding to each paper's stored vector (plain RAG retrieval)
  graph   query -> symptom nodes -> papers; ranked by how many query symptoms a paper reports, then how strongly
          (finding mentions), then vector similarity as a tie-break
  hybrid  reciprocal-rank fusion of the two lists
The top 10 of each method are pooled and judged blind (the judge sees query, title and abstract only).
A second output compares the symptom -> condition answer the graph gives with what vector top-50 papers imply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
from collections import Counter, defaultdict

import numpy as np

from . import store, symptoms
from .analysis import MODEL, MODEL_DIR

AREA = "C14 Cardiovascular Diseases"
QUERIES = ["chest pain", "shortness of breath", "fatigue", "palpitations", "leg swelling", "dizziness or fainting",
           "headache", "fatigue and shortness of breath", "chest pain and nausea", "palpitations and dizziness"]
K = 10


def load(conn):
    rows = conn.execute("""select p.id, p.title, coalesce(p.abstract, ''), v.embedding::text, a.terms
                           from papers p join paper_area a on a.paper_id = p.id and a.area = %s
                           join paper_vec v on v.paper_id = p.id
                           where p.label in ('female_only_verified', 'female_only_probable')
                             and coalesce(p.abstract, '') <> ''""", (AREA,)).fetchall()
    ids = [r[0] for r in rows]
    meta = {r[0]: {"title": r[1], "abstract": r[2], "conditions": r[4] or []} for r in rows}
    mat = np.array([json.loads(r[3]) for r in rows], dtype=np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True)
    return ids, meta, mat


def build_graph(ids, meta):
    terms = symptoms.lexicon()
    matcher = symptoms.compile_matcher(terms)
    sym_papers: dict[str, dict[str, list[int]]] = defaultdict(dict)    # symptom -> paper -> [mentions, findings]
    for pid in ids:
        text = meta[pid]["title"] + ". " + meta[pid]["abstract"]
        for sym, _term, _sec, neg, _sent, fnd in symptoms.extract(text, "abstract", matcher, terms):
            if neg:
                continue
            m = sym_papers[sym].setdefault(pid, [0, 0])
            m[0] += 1
            m[1] += int(bool(fnd))
    return terms, matcher, sym_papers


def query_symptoms(q, matcher, terms):
    return sorted({terms[m.group(1).lower()] for m in matcher.finditer(q)})


def rrf(*lists, k=60):
    score = defaultdict(float)
    for lst in lists:
        for r, pid in enumerate(lst):
            score[pid] += 1 / (k + r + 1)
    return [p for p, _ in sorted(score.items(), key=lambda x: -x[1])]


def run(out: str) -> dict:
    from fastembed import TextEmbedding
    os.makedirs(out, exist_ok=True)
    conn = store.connect()
    ids, meta, mat = load(conn)
    conn.close()
    terms, matcher, sym_papers = build_graph(ids, meta)
    model = TextEmbedding(model_name=MODEL, cache_dir=MODEL_DIR)
    index = {p: i for i, p in enumerate(ids)}
    runs, conditions = {}, {}
    for q in QUERIES:
        qv = np.array(list(model.query_embed([f"women with {q}"]))[0], dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = mat @ qv
        order = np.argsort(-sims)
        vec = [ids[i] for i in order[:100]]
        syms = query_symptoms(q, matcher, terms)
        cand = set().union(*(sym_papers.get(s, {}).keys() for s in syms)) if syms else set()
        def gscore(pid):
            hit = [sym_papers[s][pid] for s in syms if pid in sym_papers.get(s, {})]
            return (len(hit), sum(h[1] for h in hit), sum(h[0] for h in hit), float(sims[index[pid]]))
        graph = sorted(cand, key=gscore, reverse=True)
        hybrid = rrf(vec, graph[:100])
        runs[q] = {"symptoms": syms, "graph_candidates": len(cand),
                   "vector": vec[:K], "graph": graph[:K], "hybrid": hybrid[:K]}
        # symptom -> condition: the graph answer (conditions of papers reporting all query symptoms, >= 3 papers)
        # vs what plain retrieval implies (conditions of the vector top-50)
        both = [p for p in cand if all(p in sym_papers.get(s, {}) for s in syms)]
        g = Counter(c for p in both for c in meta[p]["conditions"])
        v = Counter(c for p in vec[:50] for c in meta[p]["conditions"])
        conditions[q] = {"graph_papers": len(both),
                         "graph": [[c, n] for c, n in g.most_common(8) if n >= 3],
                         "vector_top50": [[c, n] for c, n in v.most_common(8)]}
    pool = {}
    for q, r in runs.items():
        for m in ("vector", "graph", "hybrid"):
            for pid in r[m]:
                pool[f"{q}|{pid}"] = {"key": f"{q}|{pid}", "query": q, "paper_id": pid, "title": meta[pid]["title"],
                                      "abstract": meta[pid]["abstract"][:1500]}
    items = sorted(pool.values(), key=lambda x: hashlib.sha1(x["key"].encode()).hexdigest())   # method-blind order
    json.dump(runs, open(os.path.join(out, "runs.json"), "w"), indent=1)
    json.dump(conditions, open(os.path.join(out, "conditions.json"), "w"), indent=1)
    json.dump(items, open(os.path.join(out, "pool.json"), "w"), indent=1, ensure_ascii=False)
    stats = {"papers": len(ids), "symptom_nodes": len(sym_papers),
             "paper_symptom_edges": sum(len(v) for v in sym_papers.values()), "pool": len(items),
             "graph_candidates": {q: r["graph_candidates"] for q, r in runs.items()}}
    json.dump(stats, open(os.path.join(out, "stats.json"), "w"), indent=1)
    return stats


def score(d: str) -> dict:
    runs = json.load(open(os.path.join(d, "runs.json")))
    judg = json.load(open(os.path.join(d, "judgments.json")))      # {"query|paper": 0 | 1 | 2}
    out = {}
    for m in ("vector", "graph", "hybrid"):
        p10, ndcg, per = [], [], {}
        for q, r in runs.items():
            g = [judg.get(f"{q}|{p}", 0) for p in r[m]] + [0] * (K - len(r[m]))
            ideal = sorted([v for k, v in judg.items() if k.startswith(q + "|")], reverse=True)[:K]
            dcg = sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(g))
            idcg = sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(ideal)) or 1
            p10.append(sum(1 for x in g if x >= 1) / K); ndcg.append(dcg / idcg)
            per[q] = {"p10": round(p10[-1], 2), "ndcg10": round(ndcg[-1], 3), "returned": len(r[m])}
        out[m] = {"p10": round(float(np.mean(p10)), 3), "ndcg10": round(float(np.mean(ndcg)), 3), "per_query": per}
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
