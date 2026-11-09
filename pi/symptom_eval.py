"""Locked test set for symptom extraction, and a head-to-head of three extractors on it.

  python -m pi.symptom_eval build  --out eval/symptoms     # sample papers (locked once written), run all extractors
  python -m pi.symptom_eval score  --dir eval/symptoms     # precision / pooled recall / agreement from the labels

Extractors, all on the same abstracts of women-only cardiovascular papers:
  ours      pi/symptoms.py (MeSH C23.888 word list + heart terms, negation, is_finding filter)
  pubtator  NCBI PubTator 3.0 disease tags (MeSH IDs) that fall in MeSH "Signs and Symptoms" (C23.888)
  epmc      Europe PMC text-mined "Diseases" annotations whose words are a MeSH C23.888 term
Each extractor is scored twice: "raw" (any hit) and "final" (patient symptom, not negated, sentence is a finding,
i.e. our filters applied on top), so we can see whether a better tagger helps once the same filters are used.

Hits from all extractors are pooled: overlapping hits in the same sentence become one candidate, which two people
label independently (yes = the women studied had/reported this symptom). Recall is therefore "pooled recall": a
symptom none of the three found is not counted. The paper sample is written once and then reused (locked), so
later versions of our rules are measured on exactly the same text.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import time
from collections import defaultdict

import requests

from . import store, symptoms
from .analysis import MODEL_DIR

AREA = "C14 Cardiovascular Diseases"
SALT = "anarcha-symptom-test-v1"        # fixed: the sample order never changes
TARGET_CANDIDATES = 300
PUBTATOR = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
EPMC = "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds"
UA = {"User-Agent": "anarcha-evidence-eval/1.0"}


# ---------- MeSH: descriptor ID -> (name, in signs-and-symptoms tree)

def mesh_index() -> dict[str, tuple[str, bool]]:
    src = next((os.path.join(MODEL_DIR, f) for f in sorted(os.listdir(MODEL_DIR), reverse=True)
                if f.startswith("desc") and f.endswith(".gz")), None)
    if not src:
        raise RuntimeError("MeSH descriptor file not found; run  python -m pi.analysis mesh  first")
    from lxml import etree
    with open(src, "rb") as probe:
        packed = probe.read(2) == b"\x1f\x8b"
    out = {}
    with (gzip.open(src, "rb") if packed else open(src, "rb")) as fh:
        for _, el in etree.iterparse(fh, events=("end",), tag="DescriptorRecord"):
            trees = [t.text for t in el.findall("TreeNumberList/TreeNumber")]
            out[el.findtext("DescriptorUI")] = (el.findtext("DescriptorName/String"),
                                                any(t.startswith(symptoms.SYMPTOM_TREE) for t in trees))
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    return out


# ---------- sample

def order_key(paper_id: str) -> str:
    return hashlib.sha1(f"{SALT}:{paper_id}".encode()).hexdigest()


def sentences(text: str) -> list[str]:
    return [s.strip() for s in symptoms.SENT.split(text or "") if s.strip()]


def locate(sents: list[str], needle: str, rel_pos: float | None = None):
    """(sentence index, start, end) of needle in the sentences; ties broken by relative position in the abstract."""
    hits = []
    rx = re.compile(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", re.I)
    for i, s in enumerate(sents):
        for m in rx.finditer(s):
            hits.append((i, m.start(), m.end()))
    if not hits:
        return None
    if rel_pos is None or len(hits) == 1:
        return hits[0]
    return min(hits, key=lambda h: abs(h[0] / max(1, len(sents)) - rel_pos))


# ---------- extractors

def run_ours(sents, matcher, terms):
    for i, s in enumerate(sents):
        skip = len(s) > 1200 or symptoms.NOT_A_FINDING.search(s)
        for m in matcher.finditer(s):
            before = s[max(0, m.start() - 60):m.start()]
            neg = bool(symptoms.NEGATION.search(" ".join(before.split()[-6:])))
            final = not skip and not neg and symptoms.is_finding(s, "abstract")
            yield {"sent": i, "start": m.start(), "end": m.end(), "symptom": terms[m.group(1).lower()],
                   "raw": True, "final": final}


def filters_ok(sent: str, start: int, symptom: str) -> bool:
    """Our patient-symptom, negation and finding filters, applied to another extractor's hit."""
    if symptom not in symptoms.PATIENT_SYMPTOMS or len(sent) > 1200 or symptoms.NOT_A_FINDING.search(sent):
        return False
    before = sent[max(0, start - 60):start]
    if symptoms.NEGATION.search(" ".join(before.split()[-6:])):
        return False
    return symptoms.is_finding(sent, "abstract")


def fetch_pubtator(pmids: list[str]) -> dict[str, list[dict]]:
    """pmid -> [{text, mesh, rel_pos}] for Disease annotations."""
    out: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(pmids), 100):
        chunk = pmids[i:i + 100]
        for attempt in range(4):
            try:
                r = requests.get(PUBTATOR, params={"pmids": ",".join(chunk)}, headers=UA, timeout=60)
                r.raise_for_status()
                break
            except Exception as e:  # noqa: BLE001
                print(f"  pubtator retry {attempt + 1}: {e}", flush=True)
                time.sleep(3 * (attempt + 1))
        else:
            continue
        body = r.json()
        docs = body.get("PubTator3", body.get("documents", [])) if isinstance(body, dict) else body
        for d in docs:
            pmid = str(d.get("id") or d.get("pmid"))
            total = sum(len(p.get("text", "")) for p in d.get("passages", [])) or 1
            for p in d.get("passages", []):
                for a in p.get("annotations", []):
                    inf = a.get("infons", {})
                    if inf.get("type") != "Disease":
                        continue
                    ident = str(inf.get("identifier") or "")
                    loc = (a.get("locations") or [{}])[0]
                    out[pmid].append({"text": a.get("text", ""), "mesh": ident.replace("MESH:", ""),
                                      "rel_pos": (loc.get("offset", 0)) / total})
        time.sleep(0.4)   # PubTator asks for at most 3 requests per second
    return out


def fetch_epmc(pmids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for i in range(0, len(pmids), 8):
        chunk = pmids[i:i + 8]
        for attempt in range(4):
            try:
                r = requests.get(EPMC, params={"articleIds": ",".join(f"MED:{p}" for p in chunk),
                                               "type": "Diseases", "format": "JSON"}, headers=UA, timeout=60)
                r.raise_for_status()
                break
            except Exception as e:  # noqa: BLE001
                print(f"  europe pmc retry {attempt + 1}: {e}", flush=True)
                time.sleep(3 * (attempt + 1))
        else:
            continue
        for art in r.json():
            pmid = str(art.get("extId"))
            for a in art.get("annotations", []):
                out[pmid].append({"text": a.get("exact", ""), "section": a.get("section", ""),
                                  "prefix": a.get("prefix", "")})
        time.sleep(0.2)
    return out


# ---------- build

def merge(spans: list[dict]) -> list[dict]:
    """Overlapping hits in one sentence -> one candidate carrying every extractor's verdict."""
    spans.sort(key=lambda s: (s["sent"], s["start"]))
    groups: list[dict] = []
    for s in spans:
        g = groups[-1] if groups else None
        if g and g["sent"] == s["sent"] and s["start"] < g["end"]:
            g["end"] = max(g["end"], s["end"])
            g["start"] = min(g["start"], s["start"])
        else:
            g = {"sent": s["sent"], "start": s["start"], "end": s["end"], "systems": {}}
            groups.append(g)
        prev = g["systems"].get(s["system"], {"raw": False, "final": False, "symptom": s["symptom"]})
        g["systems"][s["system"]] = {"raw": prev["raw"] or s["raw"], "final": prev["final"] or s["final"],
                                     "symptom": prev["symptom"]}
    return groups


def build(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    papers_file = os.path.join(out_dir, "papers.json")
    conn = store.connect()
    rows = conn.execute("""select p.id, p.pmid, p.title, p.abstract, p.label from papers p
                           join paper_area a on a.paper_id = p.id and a.area = %s
                           where p.pmid is not null and coalesce(p.abstract, '') <> ''
                             and p.label in ('female_only_verified', 'female_only_probable')""", (AREA,)).fetchall()
    conn.close()
    by_id = {r[0]: r for r in rows}
    locked = json.load(open(papers_file)) if os.path.exists(papers_file) else None
    order = locked["papers"] if locked else sorted(by_id, key=order_key)
    print(f"{len(by_id)} eligible papers; sample {'locked' if locked else 'new'}", flush=True)

    terms = symptoms.lexicon()
    matcher = symptoms.compile_matcher(terms)
    mesh = mesh_index()
    lex_c23 = {t: n for t, n in terms.items()}          # word -> symptom name (C23.888 + heart terms)

    chosen, cands, n_cand = [], [], 0
    batch = 40
    i = 0
    stats = {"pubtator_docs": 0, "epmc_docs": 0, "pubtator_unplaced": 0, "epmc_unplaced": 0}
    while i < len(order) and (locked or n_cand < TARGET_CANDIDATES):
        ids = [p for p in order[i:i + batch] if p in by_id]
        i += batch
        pmids = [by_id[p][1] for p in ids]
        pt, ep = fetch_pubtator(pmids), fetch_epmc(pmids)
        stats["pubtator_docs"] += sum(1 for p in pmids if p in pt)
        stats["epmc_docs"] += sum(1 for p in pmids if p in ep)
        for pid in ids:
            if not locked and n_cand >= TARGET_CANDIDATES:
                break
            _, pmid, title, abstract, label = by_id[pid]
            sents = sentences(abstract)
            spans = [{**h, "system": "ours"} for h in run_ours(sents, matcher, terms)]
            for a in pt.get(pmid, []):
                name, in_c23 = mesh.get(a["mesh"], (None, False))
                if not in_c23 or not a["text"]:
                    continue
                loc = locate(sents, a["text"], a["rel_pos"])
                if not loc:
                    stats["pubtator_unplaced"] += 1
                    continue
                si, st, en = loc
                spans.append({"system": "pubtator", "sent": si, "start": st, "end": en, "symptom": name,
                              "raw": True, "final": filters_ok(sents[si], st, name)})
            for a in ep.get(pmid, []):
                name = lex_c23.get(a["text"].lower().strip())
                if not name:
                    continue                                   # not a signs-and-symptoms term
                loc = locate(sents, a["text"])
                if not loc:
                    stats["epmc_unplaced"] += 1                # e.g. annotation in the title or full text
                    continue
                si, st, en = loc
                spans.append({"system": "epmc", "sent": si, "start": st, "end": en, "symptom": name,
                              "raw": True, "final": filters_ok(sents[si], st, name)})
            chosen.append(pid)
            for g in merge(spans):
                s = sents[g["sent"]]
                cands.append({"id": f"{pid}:{g['sent']}:{g['start']}", "paper_id": pid, "pmid": pmid, "title": title,
                              "sentence": s, "span": s[g["start"]:g["end"]], "start": g["start"], "end": g["end"],
                              "systems": g["systems"]})
            n_cand = len(cands)
        print(f"  {len(chosen)} papers, {n_cand} candidates", flush=True)

    if not locked:
        json.dump({"area": AREA, "salt": SALT, "created": time.strftime("%Y-%m-%d"), "papers": chosen},
                  open(papers_file, "w"), indent=1)
    json.dump(cands, open(os.path.join(out_dir, "candidates.json"), "w"), indent=1, ensure_ascii=False)
    res = {"papers": len(chosen), "candidates": len(cands), **stats,
           "flagged": {f"{sys}_{k}": sum(1 for c in cands if c["systems"].get(sys, {}).get(k))
                       for sys in ("ours", "pubtator", "epmc") for k in ("raw", "final")}}
    json.dump(res, open(os.path.join(out_dir, "build_stats.json"), "w"), indent=1)
    return res


# ---------- score

def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - r) / d, 3), round((c + r) / d, 3)


def kappa(a: list[str], b: list[str]):
    n = len(a)
    if n == 0:
        return None
    cats = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def score(d: str) -> dict:
    cands = json.load(open(os.path.join(d, "candidates.json")))
    labels = json.load(open(os.path.join(d, "labels.json")))      # {annotator: {candidate_id: yes|no|unsure}}
    names = sorted(labels)
    both = [c["id"] for c in cands if all(c["id"] in labels[n] for n in names)]
    agree = kappa([labels[names[0]][i] for i in both], [labels[names[1]][i] for i in both]) if len(names) >= 2 else None
    # gold: both say yes -> yes; both say no -> no; anything else is a disagreement to settle (gold.json overrides)
    gold_file = os.path.join(d, "gold.json")
    settled = json.load(open(gold_file)) if os.path.exists(gold_file) else {}
    gold, open_items = {}, []
    for c in cands:
        votes = {labels[n].get(c["id"]) for n in names} - {None}
        if c["id"] in settled:
            gold[c["id"]] = settled[c["id"]]
        elif len(votes) == 1 and votes <= {"yes", "no"}:
            gold[c["id"]] = votes.pop()
        elif votes:
            open_items.append(c["id"])
    positives = [c for c in cands if gold.get(c["id"]) == "yes"]
    out = {"annotators": names, "labelled_by_all": len(both), "kappa": agree, "gold": len(gold),
           "gold_yes": len(positives), "disagreements_open": len(open_items), "systems": {}}
    for sys in ("ours", "pubtator", "epmc"):
        for k in ("raw", "final"):
            flagged = [c for c in cands if c["id"] in gold and c["systems"].get(sys, {}).get(k)]
            tp = sum(1 for c in flagged if gold[c["id"]] == "yes")
            found = sum(1 for c in positives if c["systems"].get(sys, {}).get(k))
            out["systems"][f"{sys}_{k}"] = {
                "flagged": len(flagged), "true": tp,
                "precision": round(tp / len(flagged), 3) if flagged else None, "precision_ci": wilson(tp, len(flagged)),
                "pooled_recall": round(found / len(positives), 3) if positives else None,
                "recall_ci": wilson(found, len(positives))}
    json.dump(out, open(os.path.join(d, "scores.json"), "w"), indent=1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "score"])
    ap.add_argument("--out", "--dir", dest="dir", default="eval/symptoms")
    a = ap.parse_args()
    print(json.dumps(build(a.dir) if a.step == "build" else score(a.dir), indent=1))


if __name__ == "__main__":
    main()
