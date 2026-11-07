"""Embeddings, disease areas and clustering for the Pi database.

  python -m pi.analysis mesh        # load MeSH tree numbers, tag every paper with disease areas + symptoms
  python -m pi.analysis embed       # embed title + abstract of papers that have no vector yet (resumable)
  python -m pi.analysis cluster     # two-level k-means over the vectors, label clusters from MeSH
  python -m pi.analysis all         # the three steps in order
  python -m pi.analysis summary     # print the cluster tree as compact text

Runs on a Raspberry Pi 5 with 1 GB RAM: the model is bge-small-en-v1.5 (ONNX via fastembed, the same model and
384 dimensions as the Supabase passages), and clustering works on a 64-dim PCA projection.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import requests

from . import store

MODEL = "BAAI/bge-small-en-v1.5"
MODEL_DIR = os.getenv("PI_MODEL_DIR", "/opt/herevidence/models")
MESH_YEARS = [time.gmtime().tm_year, time.gmtime().tm_year - 1, time.gmtime().tm_year + 1]
MESH_XML_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc{year}.gz"
INCLUDE_LABELS = ("female_only_verified", "female_only_probable")

AREAS = {
    "C01": "Infections", "C04": "Neoplasms", "C05": "Musculoskeletal Diseases", "C06": "Digestive System Diseases",
    "C07": "Stomatognathic Diseases", "C08": "Respiratory Tract Diseases", "C09": "Otorhinolaryngologic Diseases",
    "C10": "Nervous System Diseases", "C11": "Eye Diseases", "C12": "Urogenital Diseases",
    "C13": "Female Urogenital Diseases and Pregnancy Complications", "C14": "Cardiovascular Diseases",
    "C15": "Hemic and Lymphatic Diseases", "C16": "Congenital, Hereditary, and Neonatal Diseases",
    "C17": "Skin and Connective Tissue Diseases", "C18": "Nutritional and Metabolic Diseases",
    "C19": "Endocrine System Diseases", "C20": "Immune System Diseases", "C21": "Disorders of Environmental Origin",
    "C23": "Pathological Conditions", "C24": "Occupational Diseases", "C25": "Chemically-Induced Disorders",
    "C26": "Wounds and Injuries", "F03": "Mental Disorders",
}
SYMPTOM_PREFIX = "C23.888"          # Signs and Symptoms
# MeSH branches that describe who/how a study was done rather than what it is about: not used for cluster labels.
NON_TOPICAL = ("M01", "N", "E05", "L01", "Z01", "I", "K", "V", "J", "H", "B01")
CHECK_TAGS = {"Female", "Male", "Humans", "Animals", "Adult", "Middle Aged", "Aged", "Young Adult", "Adolescent",
              "Child", "Aged, 80 and over", "Infant", "Child, Preschool", "Infant, Newborn"}


def norm_term(t: str) -> str:
    """'*Breast Neoplasms/diagnosis' -> 'Breast Neoplasms'."""
    return t.replace("*", "").split("/")[0].strip()


# ---------------------------------------------------------------- MeSH
def load_mesh(conn) -> int:
    """Load MeSH descriptor names + tree numbers from NLM's yearly XML (the ASCII format ended in Jan 2026).

    Streams the ~17 MB gzip to the data disk and parses it record by record, so memory stays small on the Pi.
    """
    n = conn.execute("select count(*) from mesh").fetchone()[0]
    if n > 20000:
        return n
    from lxml import etree

    os.makedirs(MODEL_DIR, exist_ok=True)
    path = None
    for year in MESH_YEARS:
        url = MESH_XML_URL.format(year=year)
        with requests.get(url, stream=True, timeout=300, allow_redirects=False) as r:
            if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
                continue
            path = os.path.join(MODEL_DIR, f"desc{year}.gz")
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            print(f"  MeSH {year}: {os.path.getsize(path) / 1e6:.0f} MB downloaded", flush=True)
            break
    if path is None:
        raise RuntimeError("could not download the MeSH descriptor file from NLM")
    rows = []
    with gzip.open(path, "rb") as fh:
        for _, el in etree.iterparse(fh, events=("end",), tag="DescriptorRecord"):
            ui = el.findtext("DescriptorUI")
            name = el.findtext("DescriptorName/String")
            trees = [t.text for t in el.findall("TreeNumberList/TreeNumber")]
            if name:
                rows.append((name, ui, trees))
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    if len(rows) < 20000:
        raise RuntimeError(f"MeSH file looks incomplete ({len(rows)} descriptors)")
    with conn.cursor() as c:
        c.execute("delete from mesh")
        c.executemany("insert into mesh (name, ui, trees) values (%s,%s,%s) on conflict (name) do nothing", rows)
    conn.commit()
    return len(rows)


def tag_areas(conn) -> dict:
    trees = dict(conn.execute("select name, trees from mesh").fetchall())
    papers = conn.execute("select id, mesh_terms from papers where mesh_terms is not null").fetchall()
    area_rows, sym_rows = [], []
    for pid, terms in papers:
        by_area = defaultdict(set); syms = set()
        for t in {norm_term(x) for x in terms or []}:
            for tn in trees.get(t, []):
                if tn.startswith(SYMPTOM_PREFIX):
                    syms.add(t); by_area["Signs and Symptoms"].add(t)
                elif tn[:3] in AREAS:
                    by_area[f"{tn[:3]} {AREAS[tn[:3]]}"].add(t)
        area_rows += [(pid, a, sorted(ts)) for a, ts in by_area.items()]
        sym_rows += [(pid, s) for s in syms]
    with conn.cursor() as c:
        c.execute("delete from paper_area"); c.execute("delete from paper_symptom")
        c.executemany("insert into paper_area (paper_id, area, terms) values (%s,%s,%s)", area_rows)
        c.executemany("insert into paper_symptom (paper_id, symptom) values (%s,%s)", sym_rows)
    conn.commit()
    return {"papers": len(papers), "area_tags": len(area_rows), "symptom_tags": len(sym_rows)}


# ---------------------------------------------------------------- embeddings
def embed(batch: int = 64, threads: int = 2) -> dict:
    from fastembed import TextEmbedding  # imported here so the other steps work without it

    conn = store.connect()
    model = TextEmbedding(model_name=MODEL, cache_dir=MODEL_DIR, threads=threads)
    todo = conn.execute("""select count(*) from papers p where label = any(%s)
                           and not exists (select 1 from paper_vec v where v.paper_id = p.id)""",
                        (list(INCLUDE_LABELS),)).fetchone()[0]
    done, started = 0, time.time()
    while True:
        rows = conn.execute("""select id, title, coalesce(abstract, '') from papers p where label = any(%s)
                               and not exists (select 1 from paper_vec v where v.paper_id = p.id)
                               order by id limit %s""", (list(INCLUDE_LABELS), batch)).fetchall()
        if not rows:
            break
        texts = [f"{t}. {a}"[:2000] for _, t, a in rows]
        vecs = list(model.embed(texts, batch_size=16))
        with conn.cursor() as c:
            c.executemany("insert into paper_vec (paper_id, model, embedding) values (%s,%s,%s::vector) "
                          "on conflict (paper_id) do nothing",
                          [(pid, MODEL, "[" + ",".join(f"{x:.6f}" for x in v) + "]") for (pid, _, _), v in zip(rows, vecs)])
        conn.commit()
        done += len(rows)
        rate = done / max(1e-6, time.time() - started)
        print(f"  embedded {done}/{todo}  ({rate:.1f}/s, ~{(todo - done) / max(rate, 0.01) / 60:.0f} min left)", flush=True)
    conn.close()
    return {"embedded": done}


# ---------------------------------------------------------------- clustering
def _load_vectors(conn):
    ids, vecs = [], []
    with conn.cursor(name="vecs") as c:
        c.itersize = 2000
        c.execute("select paper_id, embedding::text from paper_vec order by paper_id")
        for pid, v in c:
            ids.append(pid); vecs.append(np.array(v[1:-1].split(","), dtype=np.float32))
    return ids, np.vstack(vecs)


def _describe(members, ids, X, centre, info, df, n_all, topical):
    tc = Counter(); ac = Counter(); sc = Counter(); years = []
    for i in members:
        mesh, areas, syms, year, _ = info[ids[i]]
        tc.update(mesh); ac.update(areas); sc.update(syms)
        if year:
            years.append(year)
    size = len(members)
    scored = []
    for t, n in tc.items():
        if t in CHECK_TAGS or not topical.get(t, False) or n < max(3, 0.08 * size):
            continue
        scored.append(((n / size) * math.log(1 + n_all / df[t]), t, n))
    scored.sort(reverse=True)
    top = [{"term": t, "n": n, "share": round(n / size, 3)} for _, t, n in scored[:8]]
    d = np.linalg.norm(X[members] - centre, axis=1)
    ex = [members[i] for i in np.argsort(d)[:5]]
    return {
        "size": size,
        "label": " · ".join(x["term"] for x in top[:3]) or "(no distinctive MeSH terms)",
        "top_mesh": top,
        "areas": [{"area": a, "n": n} for a, n in ac.most_common(6)],
        "symptoms": [{"symptom": s, "n": n} for s, n in sc.most_common(8)],
        "years": {"min": min(years), "median": int(np.median(years)), "max": max(years)} if years else {},
        "examples": [{"id": ids[i], "title": info[ids[i]][4]} for i in ex],
    }, d


def cluster(k1: int = 30, per_sub: int = 250, max_sub: int = 12, seed: int = 7) -> dict:
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA

    conn = store.connect()
    ids, V = _load_vectors(conn)
    print(f"  {len(ids)} vectors loaded", flush=True)
    X = PCA(n_components=64, random_state=seed).fit_transform(V).astype(np.float32)
    del V
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9

    trees = dict(conn.execute("select name, trees from mesh").fetchall())
    topical = {t: bool(tr) and not all(x.startswith(NON_TOPICAL) for x in tr) for t, tr in trees.items()}
    info, df = {}, Counter()
    areas = defaultdict(set); syms = defaultdict(set)
    for pid, a in conn.execute("select paper_id, area from paper_area").fetchall():
        areas[pid].add(a)
    for pid, s in conn.execute("select paper_id, symptom from paper_symptom").fetchall():
        syms[pid].add(s)
    for pid, mesh, year, title in conn.execute("select id, mesh_terms, pub_year, title from papers").fetchall():
        m = {norm_term(x) for x in mesh or []}
        info[pid] = (m, areas[pid], syms[pid], year, title)
        df.update(m)
    n_all = len(ids)

    km1 = KMeans(n_clusters=k1, n_init=4, random_state=seed).fit(X)
    l1 = km1.labels_
    clusters, assign = [], {}
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for c1 in range(k1):
        m1 = np.where(l1 == c1)[0].tolist()
        d1, _ = _describe(m1, ids, X, km1.cluster_centers_[c1], info, df, n_all, topical)
        cid1 = c1 + 1
        df1 = Counter()
        for i in m1:
            df1.update(info[ids[i]][0])
        clusters.append({"id": cid1, "level": 1, "parent": None, **d1})
        k2 = 1 if len(m1) < 2 * per_sub else min(max_sub, max(2, round(len(m1) / per_sub)))
        if k2 == 1:
            sub_labels, centres = np.zeros(len(m1), dtype=int), X[m1].mean(axis=0, keepdims=True)
        else:
            km2 = KMeans(n_clusters=k2, n_init=3, random_state=seed).fit(X[m1])
            sub_labels, centres = km2.labels_, km2.cluster_centers_
        for c2 in range(k2):
            m2 = [m1[i] for i in np.where(sub_labels == c2)[0]]
            # Sub-theme labels: what makes this group distinctive *within* its theme.
            d2, dist = _describe(m2, ids, X, centres[c2], info, df1, len(m1), topical)
            cid2 = cid1 * 100 + c2 + 1
            clusters.append({"id": cid2, "level": 2, "parent": cid1, **d2})
            for i, dd in zip(m2, dist):
                assign[ids[i]] = (cid1, cid2, float(dd))
        print(f"  theme {cid1}: {len(m1)} papers, {k2} sub-themes — {d1['label']}", flush=True)

    with conn.cursor() as c:
        c.execute("delete from paper_cluster"); c.execute("delete from clusters")
        c.executemany("""insert into clusters (id, level, parent, size, label, top_mesh, areas, symptoms, years, examples, run_id)
                         values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      [(x["id"], x["level"], x["parent"], x["size"], x["label"], json.dumps(x["top_mesh"]),
                        json.dumps(x["areas"]), json.dumps(x["symptoms"]), json.dumps(x["years"]),
                        json.dumps(x["examples"]), run_id) for x in clusters])
        c.executemany("insert into paper_cluster (paper_id, l1, l2, dist) values (%s,%s,%s,%s)",
                      [(pid, a, b, d) for pid, (a, b, d) in assign.items()])
    store.set_meta(conn, "cluster_run", run_id)
    conn.commit(); conn.close()
    return {"run_id": run_id, "papers": n_all, "themes": k1, "sub_themes": sum(1 for x in clusters if x["level"] == 2)}


def summary() -> None:
    conn = store.connect()
    rows = conn.execute("select id, level, size, label from clusters order by coalesce(parent, id), level, size desc").fetchall()
    for cid, level, size, label in rows:
        print(("" if level == 1 else "    ") + f"{cid} [{size}] {label}")
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["mesh", "embed", "cluster", "all", "summary"])
    ap.add_argument("--k", type=int, default=30, help="number of broad themes")
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()
    conn = store.connect()
    conn.execute((Path(__file__).resolve().parent / "schema_analysis.sql").read_text()); conn.commit()
    out = {}
    if a.step in ("mesh", "all"):
        out["mesh_descriptors"] = load_mesh(conn)
        out["areas"] = tag_areas(conn)
        print(json.dumps(out), flush=True)
    conn.close()
    if a.step in ("embed", "all"):
        out["embed"] = embed(threads=a.threads)
    if a.step in ("cluster", "all"):
        out["cluster"] = cluster(k1=a.k)
    if a.step == "summary":
        return summary()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
