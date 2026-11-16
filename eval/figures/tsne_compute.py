import json, sys, time, collections
import numpy as np, pgdumplib
from openTSNE import TSNE
D = sys.argv[1]
d = pgdumplib.load(D + "/data/analysis.dump")
ids, vecs = [], []
for pid, _m, emb, _t in d.table_data("public", "paper_vec"):
    ids.append(pid); vecs.append(np.array(emb.strip("[]").split(","), dtype=np.float32))
X = np.vstack(vecs); X /= np.linalg.norm(X, axis=1, keepdims=True)
areas = collections.defaultdict(list); terms = collections.defaultdict(list)
for pid, area, t in d.table_data("public", "paper_area"):
    areas[pid].append(area)
    if area.startswith("C14"): terms[pid] = [x.strip('"') for x in t.strip("{}").split('","')] if t != "{}" else []
trees = {}
for name, _ui, t in d.table_data("public", "mesh"):
    trees[name] = t.strip("{}").split(",") if t and t != "{}" else []
l1 = {pid: int(a) for pid, a, _b, _c in d.table_data("public", "paper_cluster")}
print(len(ids), "vectors", flush=True)
def run(M, seed=42):
    t0 = time.time()
    emb = TSNE(perplexity=30, metric="cosine", n_jobs=8, random_state=seed, verbose=False).fit(M)
    print(f"t-SNE {M.shape} in {time.time()-t0:.0f}s", flush=True); return np.asarray(emb)
Y = run(X)
cv = [i for i, p in enumerate(ids) if any(a.startswith("C14") for a in areas[p])]
Ycv = run(X[cv])
json.dump({"ids": ids, "xy": Y.round(3).tolist(), "areas": [areas[p] for p in ids], "l1": [l1.get(p) for p in ids],
           "cv_idx": cv, "cv_xy": Ycv.round(3).tolist(), "cv_terms": [terms[ids[i]] for i in cv]},
          open(D + "/coords.json", "w"))
json.dump(trees, open(D + "/mesh_trees.json", "w"))
print("saved")
