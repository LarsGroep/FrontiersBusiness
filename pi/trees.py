"""XGBoost decision trees over the evidence graph: which bodies of women-only evidence fit a symptom pattern.

Each paper with at least one extracted symptom is one observation.
  features  symptom indicators (graph nodes with >= MIN_FEATURE papers) + context from the paper's MeSH terms and
            publication types: pregnancy, postpartum, menopause, age groups, study design
  outcome   the paper's cardiovascular condition group (MeSH tree C14, see GROUPS); a paper with several groups gets
            the first in GROUPS order, so the large pregnancy-hypertension group does not absorb comorbid papers
  model     XGBoost, multi-class log-loss, balanced class weights; depth / trees / learning rate chosen by stratified
            5-fold cross-validation on 80% of papers; 20% held out for the reported metrics
  readable  the boosted ensemble is distilled into one classification tree (fit to the XGBoost predictions); we
            report fidelity (agreement with XGBoost on held-out papers) and the tree's own accuracy
  output    leaves list condition groups by number of supporting papers, with the papers. It ranks evidence, it does
            not estimate a patient's diagnosis.

  python -m pi.trees --out web/graph/tree-cv.json        (needs the graph: built here, or passed from pi.build_demo)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter

import numpy as np

from . import store

# (label, MeSH tree prefixes) in priority order; first match wins.
GROUPS = [
    ("Coronary / ischaemic heart disease", ["C14.280.647"]),
    ("Arrhythmia", ["C14.280.067"]),
    ("Heart failure", ["C14.280.434"]),
    ("Cardiomyopathy", ["C14.280.238"]),
    ("Heart valve disease", ["C14.280.484"]),
    ("Stroke / cerebrovascular", ["C14.907.253", "C10.228.140.300"]),
    ("Thrombosis / embolism", ["C14.907.355"]),
    ("Hypertensive disorders of pregnancy", ["C14.907.489.480", "C13.703.395"]),
    ("Hypertension", ["C14.907.489"]),
    ("Other vascular", ["C14.907"]),
    ("Other heart", ["C14.280"]),
]
OTHER = "Other cardiovascular"
MIN_FEATURE = 5          # a symptom needs this many papers to be a feature
MIN_CLASS = 12           # smaller groups are merged into OTHER
CONTEXT = {              # feature -> MeSH terms / publication types that set it
    "Pregnancy": ["Pregnancy", "Pregnancy Trimester, Third", "Pregnancy Trimester, Second", "Pregnancy Trimester, First"],
    "Postpartum": ["Postpartum Period", "Puerperal Disorders"],
    "Menopause": ["Menopause", "Postmenopause", "Perimenopause", "Menopause, Premature"],
    "Age: adolescent or young adult": ["Adolescent", "Young Adult"],
    "Age: middle-aged": ["Middle Aged"],
    "Age: 65 or older": ["Aged", "Aged, 80 and over"],
    "Design: randomised trial": ["Randomized Controlled Trial", "Randomized Controlled Trials as Topic"],
    "Design: cohort or observational": ["Cohort Studies", "Prospective Studies", "Retrospective Studies", "Observational Study"],
    "Design: cross-sectional": ["Cross-Sectional Studies"],
}


def group_of(conditions: list[str], trees: dict[str, list[str]]) -> str:
    nums = [t for c in conditions for t in trees.get(c, [])]
    for label, prefixes in GROUPS:
        if any(n.startswith(p) for n in nums for p in prefixes):
            return label
    return OTHER


def dataset(g):
    conn = store.connect()
    trees = {n: t for n, t in conn.execute("select name, trees from mesh").fetchall()}
    meta = {r[0]: (set(r[1] or []), set(r[2] or [])) for r in
            conn.execute("select id, mesh_terms, pub_types from papers where id = any(%s)", (g.ids,)).fetchall()}
    conn.close()
    sym_feats = sorted(s for s, ps in g.sym.items() if len(ps) >= MIN_FEATURE)
    feats = sym_feats + list(CONTEXT)
    rows, ys, pids = [], [], []
    for pid in g.ids:
        has = [s for s in sym_feats if pid in g.sym[s]]
        if not has:
            continue
        mesh, ptypes = meta.get(pid, (set(), set()))
        terms = mesh | ptypes
        x = [1 if pid in g.sym[s] else 0 for s in sym_feats] + [1 if terms & set(v) else 0 for v in CONTEXT.values()]
        rows.append(x)
        ys.append(group_of(g.papers[pid]["conditions"], trees))
        pids.append(pid)
    counts = Counter(ys)
    ys = [y if counts[y] >= MIN_CLASS else OTHER for y in ys]
    return np.array(rows, dtype=np.float32), ys, pids, feats, len(sym_feats)


def train(g, out: str, seed: int = 42) -> dict:
    from sklearn.model_selection import StratifiedKFold, train_test_split
    from sklearn.metrics import log_loss
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.utils.class_weight import compute_sample_weight
    import xgboost as xgb

    X, ys, pids, feats, n_sym = dataset(g)
    classes = sorted(set(ys))
    y = np.array([classes.index(v) for v in ys])
    idx = np.arange(len(y))
    tr, te = train_test_split(idx, test_size=0.2, stratify=y, random_state=seed)
    w = compute_sample_weight("balanced", y[tr])
    grid = [{"max_depth": d, "n_estimators": n, "learning_rate": lr}
            for d in (2, 3, 4) for n in (100, 300) for lr in (0.05, 0.1)]
    skf = StratifiedKFold(5, shuffle=True, random_state=seed)
    best, best_loss = None, 1e9
    for params in grid:
        losses = []
        for a, b in skf.split(X[tr], y[tr]):
            m = xgb.XGBClassifier(objective="multi:softprob", eval_metric="mlogloss", subsample=0.8,
                                  colsample_bytree=0.8, random_state=seed, n_jobs=4, **params)
            m.fit(X[tr][a], y[tr][a], sample_weight=w[a])
            losses.append(log_loss(y[tr][b], m.predict_proba(X[tr][b]), labels=list(range(len(classes)))))
        if np.mean(losses) < best_loss:
            best, best_loss = params, float(np.mean(losses))
    model = xgb.XGBClassifier(objective="multi:softprob", eval_metric="mlogloss", subsample=0.8, colsample_bytree=0.8,
                              random_state=seed, n_jobs=4, **best)
    model.fit(X[tr], y[tr], sample_weight=w)
    p = model.predict_proba(X[te])
    prior = np.bincount(y[tr], minlength=len(classes)) / len(tr)
    top = np.argsort(-p, axis=1)
    metrics = {
        "papers": len(y), "train": len(tr), "test": len(te), "cv_best": best, "cv_logloss": round(best_loss, 3),
        "test_logloss": round(float(log_loss(y[te], p, labels=list(range(len(classes))))), 3),
        "baseline_logloss": round(float(log_loss(y[te], np.tile(prior, (len(te), 1)), labels=list(range(len(classes))))), 3),
        "top1": round(float(np.mean(top[:, 0] == y[te])), 3),
        "top3": round(float(np.mean([y[te][i] in top[i, :3] for i in range(len(te))])), 3),
        "baseline_top1": round(float(np.mean(y[te] == np.argmax(prior))), 3),
    }
    # calibration: expected calibration error of the top prediction, 10 bins
    conf, hit = p.max(axis=1), (top[:, 0] == y[te])
    bins = np.minimum((conf * 10).astype(int), 9)
    metrics["ece"] = round(float(sum(abs(conf[bins == b].mean() - hit[bins == b].mean()) * (bins == b).mean()
                                     for b in range(10) if (bins == b).any())), 3)
    # contributions (SHAP values computed by XGBoost itself), mean absolute over held-out papers and classes
    contrib = model.get_booster().predict(xgb.DMatrix(X[te]), pred_contribs=True)      # (n, classes, feats + 1)
    imp = np.abs(contrib[:, :, :-1]).mean(axis=(0, 1))
    importance = sorted(([feats[i], round(float(imp[i]), 4)] for i in range(len(feats))), key=lambda r: -r[1])
    # distil into one readable tree
    teacher = model.predict(X)
    tree = DecisionTreeClassifier(max_depth=4, min_samples_leaf=8, random_state=seed).fit(X[tr], teacher[tr])
    metrics["fidelity"] = round(float(np.mean(tree.predict(X[te]) == teacher[te])), 3)
    metrics["tree_top1"] = round(float(np.mean(tree.predict(X[te]) == y[te])), 3)
    leaf_of = tree.apply(X)

    t = tree.tree_
    def node(i: int) -> dict:
        if t.children_left[i] == -1:
            members = [j for j in range(len(y)) if leaf_of[j] == i]
            groups = Counter(classes[y[j]] for j in members).most_common()
            return {"leaf": True, "papers": len(members), "groups": [[k, v] for k, v in groups],
                    "paper_ids": {k: [pids[j] for j in members if classes[y[j]] == k][:25] for k, _ in groups}}
        f = feats[t.feature[i]]
        return {"leaf": False, "feature": f, "kind": "symptom" if t.feature[i] < n_sym else "context",
                "papers": int(t.n_node_samples[i]),
                "yes": node(t.children_right[i]), "no": node(t.children_left[i])}   # binary features: > 0.5 = yes
    result = {"built": time.strftime("%Y-%m-%d"), "area": g.area, "classes": classes,
              "class_counts": dict(Counter(ys)), "features": feats, "metrics": metrics,
              "importance": importance[:20], "tree": node(0), "groups_definition": [[l, p] for l, p in GROUPS]}
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as fh:
        json.dump(result, fh, separators=(",", ":"), ensure_ascii=False)
    return metrics


def main() -> None:
    from .graph import EvidenceGraph
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="C14 Cardiovascular Diseases")
    ap.add_argument("--out", default="web/graph/tree-cv.json")
    a = ap.parse_args()
    print(json.dumps(train(EvidenceGraph(a.area), a.out), indent=1))


if __name__ == "__main__":
    main()
