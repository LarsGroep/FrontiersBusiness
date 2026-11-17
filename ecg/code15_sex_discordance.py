# %% [markdown]
# # AI-ECG sex discordance on open data (CODE-15%)
#
# A replication, on open data, of the main idea in Sau et al., *Lancet Digital Health* 2025
# (doi:10.1016/S2589-7500(24)00270-X):
#
# 1. Train a 1D residual network to tell female from male 12-lead ECGs.
# 2. Sex discordance score = |AI-predicted sex − recorded sex|.
# 3. Test whether a higher score goes with higher mortality, separately for women and men, in all patients and in
#    patients with a normal ECG.
#
# **Data:** [CODE-15%](https://zenodo.org/records/4916206) (CC BY 4.0), 345,779 ECGs from 233,770 Brazilian patients, with
# sex, a normal-ECG label, death and follow-up time. This dataset records death from any cause, not cardiovascular death.
#
# **Model design:** the residual network of Ribeiro et al. (Nat Commun 2020,
# [automatic-ecg-diagnosis](https://github.com/antonior92/automatic-ecg-diagnosis), MIT), written here in PyTorch.
#
# **Kaggle settings:** Accelerator GPU (T4 or P100). Either attach your uploaded CODE-15% dataset (Add input), or turn
# Internet on and the notebook downloads it from Zenodo. *Save version → Save & Run All* runs it in the
# background (about 2–4 hours). Results land in `/kaggle/working/`.
#
# Research use only. This is not a diagnostic tool.

# %%
N_PARTS = 8          # CODE-15% parts to use (of 18; ~20k ECGs and 2.7 GB each). 8 parts fit in Kaggle's RAM as float16.
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
from sklearn.metrics import roc_auc_score
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
        keep = np.where(eid != 0)[0]              # the last row of each file is zero padding
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
print(meta[["female", "normal_ecg", "death"]].describe())

# split by patient, 50/10/40 as in the paper, so no patient is in two sets
pats = meta["patient_id"].unique(); rng.shuffle(pats)
n = len(pats); cut1, cut2 = int(.5 * n), int(.6 * n)
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
    def __init__(self, n_leads=8, filters=(64, 128, 196, 256, 320), downs=(4, 4, 4, 4)):
        super().__init__()
        self.stem = nn.Sequential(nn.Conv1d(n_leads, filters[0], 17, padding=8, bias=False), nn.BatchNorm1d(filters[0]), nn.ReLU())
        self.blocks = nn.ModuleList(ResBlock(filters[i], filters[i + 1], downs[i]) for i in range(4))
        self.head = nn.Linear(filters[-1] * 16, 1)
    def forward(self, x):                      # x: (N, 4096, leads)
        x = self.stem(x.transpose(1, 2)); y = x
        for b in self.blocks: x, y = b(x, y)
        return self.head(x.flatten(1)).squeeze(1)

model = ResNet1d(len(LEADS)).to(DEV)
print(sum(p.numel() for p in model.parameters()) / 1e6, "M parameters")

# %% [markdown]
# ## 3. Train: female (1) vs male (0)

# %%
y_all = meta["female"].values.astype(np.float32)
def batches(ix, shuffle):
    ix = rng.permutation(ix) if shuffle else ix
    for s in range(0, len(ix), BATCH):
        b = np.sort(ix[s:s + BATCH])
        yield torch.from_numpy(X[b].astype(np.float32)).to(DEV), torch.from_numpy(y_all[b]).to(DEV), b

def predict(ix):
    model.eval(); out = np.empty(len(ix), dtype=np.float32); pos = {v: k for k, v in enumerate(ix)}
    with torch.no_grad(), torch.autocast(DEV, enabled=DEV == "cuda"):
        for xb, _, b in batches(ix, False):
            p = torch.sigmoid(model(xb).float()).cpu().numpy()
            out[[pos[v] for v in b]] = p
    return out

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
    pv = predict(idx["val"]); auc = roc_auc_score(y_all[idx["val"]], pv)
    vloss = float(F.binary_cross_entropy(torch.tensor(pv).clamp(1e-6, 1 - 1e-6), torch.tensor(y_all[idx["val"]])))
    sched.step(vloss)
    log.append({"epoch": ep, "train_loss": tot / len(idx["train"]), "val_loss": vloss, "val_auroc": auc, "s": time.time() - t0})
    print(log[-1])
    if auc > best: best = auc; torch.save(model.state_dict(), f"{WORK}/ecg_sex_resnet.pt")
model.load_state_dict(torch.load(f"{WORK}/ecg_sex_resnet.pt"))

# %% [markdown]
# ## 4. Test: how well does it tell female from male?

# %%
te = idx["test"]; p_test = predict(te)
tm = meta.iloc[te].copy(); tm["p_female"] = p_test
res = {"data": {"parts": N_PARTS, "ecgs": int(len(meta)), "patients": int(meta.patient_id.nunique()),
                "train": int(len(idx["train"])), "val": int(len(idx["val"])), "test": int(len(te))},
       "training": log}
res["auroc_test"] = float(roc_auc_score(tm.female, tm.p_female))
res["auroc_test_normal_ecg"] = float(roc_auc_score(tm[tm.normal_ecg == True].female, tm[tm.normal_ecg == True].p_female))
res["accuracy_test"] = float(((tm.p_female > .5) == tm.female).mean())
conf = tm[(tm.p_female < .2) | (tm.p_female > .8)]
res["accuracy_confident"] = float(((conf.p_female > .5) == conf.female).mean()); res["share_confident"] = float(len(conf) / len(tm))
print(json.dumps({k: v for k, v in res.items() if k != "training"}, indent=1))

# %% [markdown]
# ## 5. Sex discordance score and mortality (Cox models, one ECG per patient: the first)

# %%
from lifelines import CoxPHFitter, KaplanMeierFitter
tm["sds"] = (tm.p_female - tm.female).abs()
first = tm.sort_values("exam_id").groupby("patient_id").head(1)
first = first[first.death.notna() & first.timey.notna() & (first.timey > 0)].copy()
first["death"] = first.death.astype(bool).astype(int)

def cox(df, label):
    d = df[["timey", "death", "sds", "age"]].dropna().copy()
    if d.death.sum() < 10: return {"group": label, "n": int(len(d)), "deaths": int(d.death.sum()), "note": "too few deaths"}
    d["sds"] = (d.sds - d.sds.mean()) / d.sds.std()       # HR per 1 SD, as in the paper
    c = CoxPHFitter().fit(d, "timey", "death")
    s = c.summary.loc["sds"]
    return {"group": label, "n": int(len(d)), "deaths": int(d.death.sum()), "hr_per_sd": float(s["exp(coef)"]),
            "ci_low": float(s["exp(coef) lower 95%"]), "ci_high": float(s["exp(coef) upper 95%"]), "p": float(s["p"])}

rows = []
for normal, gname in ((None, "all"), (True, "normal ECG")):
    for fem, sname in ((1, "women"), (0, "men")):
        d = first[first.female == fem]
        if normal: d = d[d.normal_ecg == True]
        rows.append(cox(d, f"{sname}, {gname}"))
res["cox_all_cause_death_adjusted_for_age"] = rows
print(pd.DataFrame(rows))

# %% [markdown]
# ## 6. Figures

# %%
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
ROSE, TEAL, INK, MUTED = "#B03A56", "#2A6F73", "#2B1A1E", "#765C62"
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].hist(tm[tm.female == 1].p_female, 50, color=ROSE, alpha=.75, label="Women"); ax[0].hist(tm[tm.female == 0].p_female, 50, color=TEAL, alpha=.75, label="Men")
ax[0].set_xlabel("AI-predicted chance the ECG is female"); ax[0].set_ylabel("ECGs"); ax[0].legend(frameon=False)
ax[0].set_title(f"Test set: AUROC {res['auroc_test']:.3f}", color=INK)
d = first[(first.female == 1) & (first.normal_ecg == True)].copy()
if len(d) > 100:
    d["q"] = pd.qcut(d.sds, 4, labels=["Q1 (most female ECG)", "Q2", "Q3", "Q4 (most male ECG)"])
    for q, col in zip(d.q.cat.categories, ["#E8B4C0", "#D47A90", "#B03A56", "#6E1F33"]):
        k = KaplanMeierFitter().fit(d[d.q == q].timey, d[d.q == q].death, label=q); k.plot_survival_function(ax=ax[1], ci_show=False, color=col)
    ax[1].set_title("Women with a normal ECG: survival by discordance", color=INK); ax[1].set_xlabel("Years"); ax[1].set_ylabel("Alive")
for a in ax: a.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.savefig(f"{WORK}/ecg_sex_discordance.png", dpi=180)

# %%
json.dump(res, open(f"{WORK}/results.json", "w"), indent=1)
tm[["exam_id", "patient_id", "female", "age", "normal_ecg", "death", "timey", "p_female", "sds"]].to_csv(f"{WORK}/test_predictions.csv", index=False)
print("done:", os.listdir(WORK))
