# %% [markdown]
# # Women-only AI-ECG: detecting heart rhythm and conduction problems (CODE-15%)

# %%
N_PARTS = 14          # CODE-15% parts to use (of 18; ~20k ECGs and 2.7 GB each). 8 parts fit in Kaggle's RAM as float16.
EPOCHS = 14
BATCH = 128
SEED = 42
LEADS = [0, 1, 6, 7, 8, 9, 10, 11]   # I, II, V1-V6 (III, aVR, aVL, aVF are combinations of I and II), as in the paper
WORK = "/kaggle/working"
TMP = "/tmp/code15"

# %%
import os, subprocess, sys, json, time, zipfile, glob, math
os.makedirs(WORK, exist_ok=True); os.makedirs(TMP, exist_ok=True)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "lifelines", "h5py"], check=False)
import numpy as np, pandas as pd, h5py, torch, torch.nn as nn, torch.nn.functional as F
from sklearn.metrics import roc_auc_score, f1_score
rng = np.random.default_rng(SEED); torch.manual_seed(SEED)
DEV = "cuda" if torch.cuda.is_available() else "cpu"
print("device:", DEV, torch.cuda.get_device_name(0) if DEV == "cuda" else "")

# %% [markdown]
# ## 1. Download and load the ECGs (part by part, to save disk)

# %%
BASE = "https://zenodo.org/records/4916206/files/{}?download=1"
def fetch(name, dest):
    if not os.path.exists(dest):
        subprocess.run(["wget", "-q", "-O", dest, BASE.format(name)], check=True)
    return dest

# Use a Kaggle dataset copy when one is attached (Add input → your CODE-15% dataset); otherwise download from Zenodo.
# Kaggle unpacks uploaded zips, so a part can arrive as .hdf5 (possibly in a folder) or still as .zip.
def find_input(pattern):
    hits = sorted(glob.glob(f"/kaggle/input/**/{pattern}", recursive=True))
    return hits[0] if hits else None

csv = find_input("exams.csv")
exams = pd.read_csv(csv or fetch("exams.csv", f"{TMP}/exams.csv"))
print("exams.csv from", csv or "Zenodo")
print(exams.shape); print(exams.head(3).T)

WOMEN = exams.loc[~exams["is_male"].astype(bool), "exam_id"].values
signals, ids = [], []
for i in range(N_PARTS):
    t0 = time.time()
    path, own = find_input(f"exams_part{i}.hdf5"), False
    if not path:
        z = find_input(f"exams_part{i}.zip") or fetch(f"exams_part{i}.zip", f"{TMP}/part{i}.zip")
        with zipfile.ZipFile(z) as zf:
            name = [n for n in zf.namelist() if n.endswith(".hdf5")][0]
            zf.extract(name, TMP)
        if z.startswith(TMP): os.remove(z)
        path, own = f"{TMP}/{name}", True
    with h5py.File(path, "r") as f:
        eid = f["exam_id"][:]
        keep = np.where((eid != 0) & np.isin(eid, WOMEN))[0]              # the last row of each file is zero padding
        x = np.empty((len(keep), 4096, len(LEADS)), dtype=np.float16)
        for s in range(0, len(keep), 2000):        # read in chunks
            idx = keep[s:s + 2000]
            x[s:s + len(idx)] = f["tracings"][idx[0]:idx[-1] + 1][idx - idx[0]][:, :, LEADS]
    if own: os.remove(path)
    signals.append(x); ids.append(eid[keep])
    print(f"part {i}: {len(keep)} ECGs in {time.time() - t0:.0f}s")
X = np.concatenate(signals); exam_id = np.concatenate(ids); del signals
print("ECGs loaded:", X.shape, f"{X.nbytes / 1e9:.1f} GB")

# %%
meta = exams.set_index("exam_id").loc[exam_id].reset_index()
meta["female"] = (~meta["is_male"].astype(bool)).astype(int)
LABELS = ["1dAVb", "RBBB", "LBBB", "SB", "ST", "AF"]
for c in LABELS: meta[c] = meta[c].astype(bool).astype(int)
meta["abnormal"] = (~meta["normal_ecg"].astype(bool)).astype(int)
meta["any6"] = meta[LABELS].max(axis=1)
TARGETS = LABELS + ["abnormal"]
print("women only:", X.shape, meta[TARGETS + ["any6"]].mean().round(3).to_dict())

pats = meta["patient_id"].unique(); rng.shuffle(pats)
n = len(pats); cut1, cut2 = int(.6 * n), int(.7 * n)
part = {p: "train" for p in pats[:cut1]} | {p: "val" for p in pats[cut1:cut2]} | {p: "test" for p in pats[cut2:]}
meta["split"] = meta["patient_id"].map(part)
idx = {s: np.where(meta["split"].values == s)[0] for s in ("train", "val", "test")}
print({k: len(v) for k, v in idx.items()})

# %% [markdown]
# ## 2. Model: 1D residual network (Ribeiro et al. design)

# %%
class ResBlock(nn.Module):
    def __init__(self, cin, cout, down, k=17, drop=0.2):
        super().__init__()
        self.c1 = nn.Conv1d(cin, cout, k, padding=k // 2, bias=False); self.b1 = nn.BatchNorm1d(cout)
        self.c2 = nn.Conv1d(cout, cout, k, stride=down, padding=k // 2, bias=False); self.b2 = nn.BatchNorm1d(cout)
        self.drop = nn.Dropout(drop)
        self.skip = nn.Sequential(nn.MaxPool1d(down) if down > 1 else nn.Identity(),
                                  nn.Conv1d(cin, cout, 1, bias=False) if cin != cout else nn.Identity())
    def forward(self, x, y):
        y = self.skip(y)
        x = self.drop(F.relu(self.b1(self.c1(x))))
        x = self.c2(x); x = x + y; y = x
        return self.drop(F.relu(self.b2(x))), y

class ResNet1d(nn.Module):
    def __init__(self, n_leads=8, filters=(64, 128, 196, 256, 320), downs=(4, 4, 4, 4), n_out=1):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv1d(n_leads, filters[0], 17, padding=8, bias=False), nn.BatchNorm1d(filters[0]), nn.ReLU())
        self.blocks = nn.ModuleList(ResBlock(filters[i], filters[i + 1], downs[i]) for i in range(4))
        self.head = nn.Linear(filters[-1] * 16, n_out)
    def forward(self, x):                      # x: (N, 4096, leads)
        x = self.stem(x.transpose(1, 2)); y = x
        for b in self.blocks: x, y = b(x, y)
        return self.head(x.flatten(1))

model = ResNet1d(len(LEADS), n_out=len(TARGETS)).to(DEV)
print(sum(p.numel() for p in model.parameters()) / 1e6, "M parameters")


# %% [markdown]
# ## 3. Train on women only: six ECG abnormalities and "not a normal ECG"

# %%
Y = meta[TARGETS].values.astype(np.float32)
def batches(ix, shuffle):
    ix = rng.permutation(ix) if shuffle else ix
    for s in range(0, len(ix), BATCH):
        b = np.sort(ix[s:s + BATCH])
        yield torch.from_numpy(X[b].astype(np.float32)).to(DEV), torch.from_numpy(Y[b]).to(DEV), b

def predict(ix):
    model.eval(); out = np.empty((len(ix), len(TARGETS)), dtype=np.float32); pos = {v: k for k, v in enumerate(ix)}
    with torch.no_grad(), torch.autocast(DEV, enabled=DEV == "cuda"):
        for xb, _, b in batches(ix, False):
            out[[pos[v] for v in b]] = torch.sigmoid(model(xb).float()).cpu().numpy()
    return out

def mean_auc(y, p):
    return float(np.mean([roc_auc_score(y[:, j], p[:, j]) for j in range(y.shape[1]) if 0 < y[:, j].sum() < len(y)]))

opt = torch.optim.Adam(model.parameters(), lr=1e-3)
sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.1, patience=2)
scaler = torch.cuda.amp.GradScaler(enabled=DEV == "cuda")
best, log = 0, []
for ep in range(EPOCHS):
    model.train(); t0 = time.time(); tot = 0
    for xb, yb, _ in batches(idx["train"], True):
        opt.zero_grad()
        with torch.autocast(DEV, enabled=DEV == "cuda"):
            loss = F.binary_cross_entropy_with_logits(model(xb), yb)
        scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); tot += loss.item() * len(yb)
    pv = predict(idx["val"]); auc = mean_auc(Y[idx["val"]], pv)
    vloss = float(F.binary_cross_entropy(torch.tensor(pv).clamp(1e-6, 1 - 1e-6), torch.tensor(Y[idx["val"]])))
    sched.step(vloss)
    log.append({"epoch": ep, "train_loss": tot / len(idx["train"]), "val_loss": vloss, "val_mean_auroc": auc, "s": time.time() - t0})
    print(log[-1])
    if auc > best: best = auc; torch.save(model.state_dict(), f"{WORK}/ecg_women_abnormal_resnet.pt")
model.load_state_dict(torch.load(f"{WORK}/ecg_women_abnormal_resnet.pt"))

# %% [markdown]
# ## 4. Test on women the model has never seen

# %%
pv, pt = predict(idx["val"]), predict(idx["test"])
yv, yt = Y[idx["val"]], Y[idx["test"]]
def best_thr(y, p):
    grid = np.linspace(0.05, 0.95, 91)
    return float(grid[np.argmax([f1_score(y, p > g, zero_division=0) for g in grid])])
res = {"data": {"parts": N_PARTS, "women_ecgs": int(len(meta)), "women_patients": int(meta.patient_id.nunique()),
                "train": int(len(idx["train"])), "val": int(len(idx["val"])), "test": int(len(idx["test"]))},
       "prevalence_test": {t: float(yt[:, j].mean()) for j, t in enumerate(TARGETS)}, "training": log, "per_label": {}}
for j, t in enumerate(TARGETS):
    if not 0 < yt[:, j].sum() < len(yt): continue
    th = best_thr(yv[:, j], pv[:, j]); pr = pt[:, j] > th; y = yt[:, j] == 1
    res["per_label"][t] = {"auroc": float(roc_auc_score(yt[:, j], pt[:, j])), "threshold": th,
                           "f1": float(f1_score(y, pr)), "sensitivity": float((pr & y).sum() / max(1, y.sum())),
                           "specificity": float((~pr & ~y).sum() / max(1, (~y).sum())), "accuracy": float((pr == y).mean()),
                           "positives": int(y.sum())}
k = TARGETS.index("abnormal")
youden = np.linspace(0.05, 0.95, 91)[np.argmax([((pv[:, k] > g) & (yv[:, k] == 1)).sum() / max(1, yv[:, k].sum()) +
                                               ((pv[:, k] <= g) & (yv[:, k] == 0)).sum() / max(1, (yv[:, k] == 0).sum()) for g in np.linspace(0.05, 0.95, 91)])]
pr = pt[:, k] > youden; y = yt[:, k] == 1
res["abnormal_balanced"] = {"threshold": float(youden), "sensitivity": float((pr & y).sum() / y.sum()),
                            "specificity": float((~pr & ~y).sum() / (~y).sum()), "accuracy": float((pr == y).mean())}
any6_true = meta["any6"].values[idx["test"]] == 1
any6_score = pt[:, :6].max(axis=1)
res["any_of_six_auroc"] = float(roc_auc_score(any6_true, any6_score))
print(json.dumps({k2: v for k2, v in res.items() if k2 != "training"}, indent=1))

# %% [markdown]
# ## 5. Figure

# %%
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve
ROSE, INK = "#B03A56", "#2B1A1E"
NAMES = {"1dAVb": "1st-degree AV block", "RBBB": "Right bundle branch block", "LBBB": "Left bundle branch block",
         "SB": "Slow heart rate (sinus bradycardia)", "ST": "Fast heart rate (sinus tachycardia)", "AF": "Atrial fibrillation",
         "abnormal": "Any abnormal ECG"}
fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
labs = [t for t in TARGETS if t in res["per_label"]]
vals = [res["per_label"][t]["auroc"] for t in labs]
ax[0].barh([NAMES[t] for t in labs], vals, color=ROSE); ax[0].set_xlim(0.5, 1); ax[0].set_xlabel("AUROC on unseen women")
for i, v in enumerate(vals): ax[0].text(v + 0.005, i, f"{v:.2f}", va="center", color=INK)
for j, t in enumerate(labs):
    jj = TARGETS.index(t); f, tp, _ = roc_curve(yt[:, jj], pt[:, jj]); ax[1].plot(f, tp, lw=1.6, label=NAMES[t])
ax[1].plot([0, 1], [0, 1], ":", color="#999"); ax[1].set_xlabel("False alarms"); ax[1].set_ylabel("Found"); ax[1].legend(frameon=False, fontsize=7)
for a in ax: a.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.savefig(f"{WORK}/ecg_women_abnormal.png", dpi=180)

# %%
json.dump(res, open(f"{WORK}/results_women_abnormal.json", "w"), indent=1)
print("done:", os.listdir(WORK))
