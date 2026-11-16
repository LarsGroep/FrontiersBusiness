import json, sys
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, "/home/claude/frontiersbusiness")
from pi.trees import GROUPS, OTHER
S = sys.argv[1]
c = json.load(open(S + "/coords.json")); trees = json.load(open(S + "/mesh_trees.json"))
ROSE, GREY, INK, MUTED = "#B03A56", "#D6D3CD", "#2B1A1E", "#6E6862"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "text.color": INK})

def panels(xy, masks, titles, out, suptitle, ncols=4):
    xy = np.asarray(xy); n = len(masks); rows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(rows, ncols, figsize=(3.1 * ncols, 3.25 * rows), dpi=200)
    for ax, m, t in zip(axes.flat, masks, titles):
        m = np.asarray(m)
        ax.scatter(xy[~m, 0], xy[~m, 1], s=0.6, c=GREY, linewidths=0, rasterized=True)
        ax.scatter(xy[m, 0], xy[m, 1], s=2.2, c=ROSE, linewidths=0, rasterized=True)
        ax.set_title(f"{t}\n{m.sum():,} papers ({100 * m.mean():.0f}%)", fontsize=9, loc="left", color=INK)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
        for s in ax.spines.values(): s.set_visible(False)
    for ax in list(axes.flat)[n:]: ax.axis("off")
    fig.suptitle(suptitle, x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95)); fig.savefig(out, facecolor="white"); plt.close(fig)

# Figure 1: whole database
A = c["areas"]
f1 = [("Pregnancy and urogenital (C12)", lambda a: any(x.startswith("C12") for x in a)),
      ("Cancer (C04)", lambda a: any(x.startswith("C04") for x in a)),
      ("Cardiovascular (C14)", lambda a: any(x.startswith("C14") for x in a)),
      ("Nutritional and metabolic (C18)", lambda a: any(x.startswith("C18") for x in a)),
      ("Infections (C01)", lambda a: any(x.startswith("C01") for x in a)),
      ("Mental disorders (F03)", lambda a: any(x.startswith("F03") for x in a)),
      ("Nervous system (C10)", lambda a: any(x.startswith("C10") for x in a)),
      ("No disease term (healthy women)", lambda a: not a)]
panels(c["xy"], [[f(a) for a in A] for _, f in f1], [t for t, _ in f1], S + "/tsne_all.png",
       f"Women-only studies, t-SNE of {len(A):,} paper embeddings, by disease area")

# Figure 2: cardiovascular pilot
def group_of(conds):
    nums = [t for x in conds for t in trees.get(x, [])]
    for label, pre in GROUPS:
        if any(n.startswith(p) for n in nums for p in pre): return label
    return OTHER
G = [group_of(t) for t in c["cv_terms"]]
ids = [c["ids"][i] for i in c["cv_idx"]]
g = json.load(open("/home/claude/frontiersbusiness/web/graph/cv.json"))
sym = {pid for n in g["nodes"] if n["kind"] == "symptom" for pid in n["evidence"]}
rhythm = {"Arrhythmia", "Heart failure", "Cardiomyopathy", "Heart valve disease"}
f2 = [("Hypertensive disorders of pregnancy", [x == "Hypertensive disorders of pregnancy" for x in G]),
      ("Hypertension", [x == "Hypertension" for x in G]),
      ("Coronary / ischaemic heart disease", [x == "Coronary / ischaemic heart disease" for x in G]),
      ("Heart rhythm, failure, muscle, valves", [x in rhythm for x in G]),
      ("Thrombosis / embolism", [x == "Thrombosis / embolism" for x in G]),
      ("Stroke / cerebrovascular", [x == "Stroke / cerebrovascular" for x in G]),
      ("Other cardiovascular", [x in ("Other cardiovascular", "Other vascular", "Other heart") for x in G]),
      ("Reports a patient symptom (evidence graph)", [p in sym for p in ids])]
panels(c["cv_xy"], [m for _, m in f2], [t for t, _ in f2], S + "/tsne_cv.png",
       f"Cardiovascular pilot, t-SNE of {len(ids):,} women-only papers, by condition group")
print("ok", sum(p in sym for p in ids))
