"""Evidence graph (light GraphRAG): the supporting retrieval layer under the search and the reasoning agent.

No language model builds it. Nodes are papers, MeSH conditions (paper_area) and symptoms (pi/symptoms.py
dictionary, matched in the abstract and in the results/conclusion sections, not negated). Edges:
  paper -has_symptom-> symptom      (with the sentence, section and whether it is a finding about the women)
  paper -has_condition-> condition  (the paper's own MeSH terms in the disease area)
  symptom -co-reported-> condition  (weight = number of papers with both; shown from 2, used from 3)

Retrieval for a free-text question (EvidenceGraph.search):
  1. link the question to symptom nodes: dictionary words first ("no chest pain" is dropped as negated), then
     embedding similarity to each symptom's terms for wording the dictionary does not know ("out of breath");
  2. graph ranking: papers that report more of those symptoms, more strongly (findings, results sections) first;
  3. hybrid: reciprocal-rank fusion with plain vector retrieval, so questions the graph cannot place still work.

  python -m pi.graph export --area "C14 Cardiovascular Diseases" --out web/graph/cv.json   # for the debug page
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import store, symptoms
from .analysis import MODEL, MODEL_DIR

LINK_THRESHOLD = 0.80        # cosine, query vs a symptom's terms; checked on the GP test questions
SECTION_WEIGHT = {"results": 2, "conclusion": 1, "abstract": 1}


def _sections(pmcid: str) -> list[tuple[str, str]]:
    from scraper import europepmc, fulltext
    try:
        xml = europepmc.fetch_fulltext_xml(pmcid)
    except Exception:  # noqa: BLE001 - a missing full text only means fewer edges
        return []
    if not xml:
        return []
    return [(k, t) for k, _title, t in fulltext.parse_sections(xml) if k in symptoms.SECTIONS]


class EvidenceGraph:
    def __init__(self, area: str | None, with_sections: bool = True, workers: int = 12):
        """area=None builds the graph over the whole collection (every disease area; no vectors, to save memory)."""
        conn = store.connect()
        if area:
            rows = conn.execute("""select p.id, p.title, coalesce(p.abstract, ''), p.pub_year, coalesce(p.commercial_use_ok, false),
                                          a.terms, v.embedding::text, array[a.area]
                                   from papers p join paper_area a on a.paper_id = p.id and a.area = %s
                                   left join paper_vec v on v.paper_id = p.id
                                   where p.label in ('female_only_verified', 'female_only_probable')
                                     and coalesce(p.abstract, '') <> ''""", (area,)).fetchall()
        else:
            rows = conn.execute("""select p.id, p.title, coalesce(p.abstract, ''), p.pub_year, coalesce(p.commercial_use_ok, false),
                                          coalesce((select array_agg(distinct t) from paper_area a, unnest(a.terms) t
                                                    where a.paper_id = p.id), '{}'),
                                          null::text,
                                          coalesce((select array_agg(a.area || '|' || cardinality(a.terms)) from paper_area a
                                                    where a.paper_id = p.id), '{}')
                                   from papers p
                                   where p.label in ('female_only_verified', 'female_only_probable')
                                     and coalesce(p.abstract, '') <> ''""").fetchall()
        conn.close()
        self.area = area or "All disease areas"
        self.ids = [r[0] for r in rows]
        self.papers = {r[0]: {"title": r[1], "abstract": r[2], "year": r[3], "open": r[4], "conditions": r[5] or [],
                              "areas": r[7] or []} for r in rows}
        vecs = [json.loads(r[6]) if r[6] else [0.0] * 384 for r in rows]
        self.mat = np.array(vecs, dtype=np.float32)
        self.mat /= np.maximum(np.linalg.norm(self.mat, axis=1, keepdims=True), 1e-9)
        self.index = {p: i for i, p in enumerate(self.ids)}
        self.terms = symptoms.lexicon()
        self.matcher = symptoms.compile_matcher(self.terms)
        # questions also understand everyday words (symptoms.QUERY_TERMS); paper text uses the clinical dictionary only
        self.qterms = dict(self.terms)
        for name, words in symptoms.QUERY_TERMS.items():
            for w in words:
                self.qterms.setdefault(w.lower(), name)
        self.qmatcher = symptoms.compile_matcher(self.qterms)
        secs: dict[str, list] = {}
        if with_sections:
            # results/conclusion text is cached next to the models (kept by the CI cache), so reruns only fetch new papers
            cache_file = os.path.join(MODEL_DIR, "sections_cache.json.gz")
            cache = json.load(gzip.open(cache_file, "rt")) if os.path.exists(cache_file) else {}
            todo = [p for p in self.ids if p not in cache]
            t0 = time.time()
            with ThreadPoolExecutor(workers) as ex:
                for pid, s in zip(todo, ex.map(_sections, todo)):
                    cache[pid] = s
            if todo:
                with gzip.open(cache_file, "wt") as f:
                    json.dump(cache, f)
            secs = {p: cache.get(p, []) for p in self.ids}
            print(f"  full-text sections for {sum(1 for s in secs.values() if s)}/{len(self.ids)} papers "
                  f"({len(todo)} fetched in {time.time() - t0:.0f}s)", flush=True)
        # symptom -> paper -> evidence
        self.sym: dict[str, dict[str, dict]] = defaultdict(dict)
        for pid in self.ids:
            p = self.papers[pid]
            parts = [("abstract", p["title"] + ". " + p["abstract"])] + secs.get(pid, [])
            for kind, text in parts:
                for name, _term, section, neg, sent, fnd in symptoms.extract(text, kind, self.matcher, self.terms):
                    if neg:
                        continue
                    e = self.sym[name].setdefault(pid, {"mentions": 0, "findings": 0, "weight": 0, "sentence": None,
                                                        "section": None})
                    e["mentions"] += 1
                    e["findings"] += int(bool(fnd))
                    e["weight"] += SECTION_WEIGHT.get(section, 1) * (2 if fnd else 1)
                    # keep one sentence to show: prefer a finding; results text only for papers whose licence allows reuse
                    if (e["sentence"] is None or (fnd and not e.get("_f"))) and (section == "abstract" or p["open"]):
                        e["sentence"], e["section"], e["_f"] = sent[:260], section, bool(fnd)
        self._model = None
        self._sym_vecs = None

    # ---------------- linking a question to symptom nodes
    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=MODEL, cache_dir=MODEL_DIR)
        return self._model

    def _symptom_vectors(self):
        if self._sym_vecs is None:
            names = sorted(self.sym)
            words = defaultdict(list)
            for t, n in self.terms.items():
                if n in self.sym:
                    words[n].append(t)
            texts = [f"{n}: " + ", ".join(sorted(words[n], key=len)[:8]) for n in names]
            v = np.array(list(self.model.embed(texts)), dtype=np.float32)
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            self._sym_vecs = (names, v)
        return self._sym_vecs

    def link(self, question: str) -> list[dict]:
        found, negated = {}, set()
        for m in self.qmatcher.finditer(question):
            name = self.qterms[m.group(1).lower()]
            before = question[max(0, m.start() - 40):m.start()]
            if symptoms.NEGATION.search(" ".join(before.split()[-4:])):
                negated.add(name)
            elif name in self.sym:
                found[name] = {"symptom": name, "via": "dictionary", "words": m.group(1), "score": 1.0}
        # embedding fallback, phrase by phrase, so "out of breath and exhausted" can link two symptoms
        names, sv = self._symptom_vectors()
        phrases = [p.strip() for p in re.split(r",|;|\band\b|\bwith\b|\bor\b|\bplus\b", question) if len(p.strip()) > 3]
        if phrases:
            pv = np.array(list(self.model.query_embed(phrases)), dtype=np.float32)
            pv /= np.linalg.norm(pv, axis=1, keepdims=True)
            sims = pv @ sv.T
            for i, ph in enumerate(phrases):
                if symptoms.NEGATION.search(" ".join(ph.split()[:3])):
                    continue
                j = int(np.argmax(sims[i]))
                if sims[i, j] >= LINK_THRESHOLD and names[j] not in found and names[j] not in negated:
                    found[names[j]] = {"symptom": names[j], "via": "embedding", "words": ph,
                                       "score": round(float(sims[i, j]), 3)}
        return list(found.values())

    # ---------------- retrieval
    def vector_rank(self, question: str, n: int = 100) -> tuple[list[str], np.ndarray]:
        qv = np.array(list(self.model.query_embed([f"women with {question}"]))[0], dtype=np.float32)
        qv /= np.linalg.norm(qv)
        sims = self.mat @ qv
        return [self.ids[i] for i in np.argsort(-sims)[:n]], sims

    def graph_rank(self, syms: list[str], sims: np.ndarray, n: int = 100) -> list[str]:
        cand = set().union(*(self.sym[s].keys() for s in syms)) if syms else set()
        def key(pid):
            hits = [self.sym[s][pid] for s in syms if pid in self.sym[s]]
            return (len(hits), sum(h["findings"] for h in hits), sum(h["weight"] for h in hits),
                    float(sims[self.index[pid]]))
        return sorted(cand, key=key, reverse=True)[:n]

    def search(self, question: str, k: int = 10) -> dict:
        links = self.link(question)
        syms = [l["symptom"] for l in links]
        vec, sims = self.vector_rank(question)
        graph = self.graph_rank(syms, sims)
        score = defaultdict(float)
        for lst in (vec, graph):
            for r, pid in enumerate(lst):
                score[pid] += 1 / (60 + r + 1)
        hybrid = [p for p, _ in sorted(score.items(), key=lambda x: -x[1])]
        return {"links": links, "vector": vec[:k], "graph": graph[:k], "hybrid": hybrid[:k]}

    # ---------------- symptom -> condition
    def conditions(self, syms: list[str], min_papers: int = 3, top: int = 8) -> list[list]:
        if not syms:
            return []
        both = [p for p in self.ids if all(p in self.sym.get(s, {}) for s in syms)]
        c = Counter(t for p in both for t in self.papers[p]["conditions"])
        return [[t, n] for t, n in c.most_common(top) if n >= min_papers]

    def export(self, path: str, min_edge: int = 2) -> dict:
        nodes, edges, papers = [], [], {}
        pair = defaultdict(list)
        for s, ps in self.sym.items():
            for pid in ps:
                for c in self.papers[pid]["conditions"]:
                    pair[(s, c)].append(pid)
        for (s, c), ps in pair.items():
            if len(ps) >= min_edge:
                edges.append({"source": "s:" + s, "target": "c:" + c, "papers": sorted(set(ps))})
        used_c = {e["target"][2:] for e in edges}
        for s, ps in self.sym.items():
            nodes.append({"id": "s:" + s, "label": s, "kind": "symptom", "papers": len(ps),
                          "evidence": {pid: {k: v for k, v in e.items() if not k.startswith("_")} for pid, e in ps.items()}})
        for c in used_c:
            ps = [p for p in self.ids if c in self.papers[p]["conditions"]]
            nodes.append({"id": "c:" + c, "label": c, "kind": "condition", "papers": len(ps)})
        for e in edges:
            for pid in e["papers"]:
                papers[pid] = {"title": self.papers[pid]["title"], "year": self.papers[pid]["year"]}
        for n in nodes:
            if n["kind"] == "symptom":
                for pid in n["evidence"]:
                    papers.setdefault(pid, {"title": self.papers[pid]["title"], "year": self.papers[pid]["year"]})
        lex = {t: n for t, n in self.qterms.items() if n in self.sym}
        out = {"area": self.area, "built": time.strftime("%Y-%m-%d"), "papers_in_area": len(self.ids),
               "nodes": nodes, "edges": edges, "papers": papers, "lexicon": lex}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        return {"symptoms": sum(1 for n in nodes if n["kind"] == "symptom"), "conditions": len(used_c),
                "edges": len(edges), "paper_symptom_links": sum(len(v) for v in self.sym.values()),
                "papers_linked": len(papers), "bytes": os.path.getsize(path)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["export"])
    ap.add_argument("--area", default="C14 Cardiovascular Diseases")
    ap.add_argument("--out", default="web/graph/cv.json")
    ap.add_argument("--no-sections", action="store_true")
    a = ap.parse_args()
    g = EvidenceGraph(a.area, with_sections=not a.no_sections)
    print(json.dumps(g.export(a.out), indent=1))


if __name__ == "__main__":
    main()
