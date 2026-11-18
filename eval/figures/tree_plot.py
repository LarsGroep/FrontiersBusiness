"""Render a decision tree JSON (pi/trees.py output) as a left-to-right figure in plain words.
  python eval/figures/tree_plot.py web/graph/tree-cv.json eval/figures/tree_cv.png "Decision tree, heart and blood vessel studies"
"""
import json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROSE, ROSE_SOFT, INK, MUTED, LINE = "#B03A56", "#F9E1E4", "#2B1A1E", "#765C62", "#D5ABAE"
Q = {"Pregnancy": "Pregnant?", "Postpartum": "After giving birth?", "Menopause": "Around menopause?",
     "Age: adolescent or young adult": "Under 25?", "Age: middle-aged": "Aged 45 to 64?", "Age: 65 or older": "65 or older?",
     "Design: randomised trial": "Randomised trial?", "Design: cohort or observational": "Follow-up study?",
     "Design: cross-sectional": "Survey study?", "Dyspnea": "Short of breath?", "Edema": "Swelling?", "Nausea": "Feeling sick?", "Anorexia": "Loss of appetite?", "Cyanosis": "Bluish skin or lips?", "Palpitations": "Racing heart?", "Syncope": "Fainting?",
     "Fatigue": "Tiredness?", "Chest Pain": "Chest pain?", "Sleep Wake Disorders": "Sleep problems?",
     "Syncope": "Fainting?", "Dizziness": "Dizziness?", "Palpitations": "Racing heart?", "Headache": "Headache?",
     "Nausea": "Feeling sick?", "Anorexia": "Loss of appetite?", "Pelvic Pain": "Pelvic pain?", "Anxiety": "Anxiety?", "Abdominal Pain": "Tummy pain?",
     "Visual Disturbances": "Vision problems?", "Hot Flashes": "Hot flushes?", "Fever": "Fever?",
     "Angina Pectoris": "Angina?", "Back Pain": "Back pain?", "Cough": "Cough?", "Pruritus": "Itching?",
     "Pain": "Pain?", "Obesity": "Overweight?", "Infertility": "Infertility?"}
G = {"Hypertensive disorders of pregnancy": "High blood pressure in pregnancy", "Hypertension": "High blood pressure",
     "Coronary / ischaemic heart disease": "Coronary heart disease", "Thrombosis / embolism": "Blood clots",
     "Stroke / cerebrovascular": "Stroke", "Arrhythmia": "Heart rhythm problems", "Cardiomyopathy": "Heart muscle disease",
     "Heart valve disease": "Heart valve disease", "Other vascular": "Other blood vessel conditions",
     "Other heart": "Other heart conditions", "Other cardiovascular": "Other heart and vessel conditions"}

def q(f): return Q.get(f, f.replace("Age: ", "").replace("Design: ", "") + "?")
A = {"C01 Infections": "Infections", "C04 Neoplasms": "Cancer", "C05 Musculoskeletal Diseases": "Bones and muscles",
     "C06 Digestive System Diseases": "Digestive system", "C08 Respiratory Tract Diseases": "Lungs and airways",
     "C10 Nervous System Diseases": "Brain and nerves", "C12 Urogenital Diseases": "Pregnancy, urinary and reproductive",
     "C16 Congenital, Hereditary, and Neonatal Diseases": "Inherited and newborn conditions", "C26 Wounds and Injuries": "Injuries",
     "C25 Chemically-Induced Disorders": "Harm from substances", "C24 Occupational Diseases": "Work-related conditions",
     "C09 Otorhinolaryngologic Diseases": "Ear, nose and throat", "C07 Stomatognathic Diseases": "Mouth and teeth",
     "C11 Eye Diseases": "Eyes",
     "C13 Female Urogenital Diseases and Pregnancy Complications": "Pregnancy and reproductive",
     "C14 Cardiovascular Diseases": "Heart and blood vessels", "C15 Hemic and Lymphatic Diseases": "Blood",
     "C17 Skin and Connective Tissue Diseases": "Skin and connective tissue",
     "C18 Nutritional and Metabolic Diseases": "Nutrition and metabolism", "C19 Endocrine System Diseases": "Hormones",
     "C20 Immune System Diseases": "Immune system", "C23 Pathological Conditions, Signs and Symptoms": "General signs",
     "F03 Mental Disorders": "Mental health"}
def g(n):
    if n in G: return G[n]
    if n in A: return A[n]
    return n.split(" ", 1)[1] if n[:1] in "CF" and n[1:3].isdigit() else n

def main(src, out, title):
    t = json.load(open(src))
    leaves, nodes, edges = [], [], []
    def walk(n, depth):
        if n["leaf"]:
            y = len(leaves); leaves.append((n, depth, y)); return y
        ys = walk(n["yes"], depth + 1); yn = walk(n["no"], depth + 1)
        y = (ys + yn) / 2
        nodes.append((n, depth, y)); edges.extend([(depth, y, depth + 1, ys, "yes"), (depth, y, depth + 1, yn, "no")])
        return y
    walk(t["tree"], 0)
    maxd = max(d for _, d, _ in leaves)
    nl = len(leaves)
    fig, ax = plt.subplots(figsize=(13, 0.62 * nl + 1.2), dpi=200)
    X = lambda d: d * 2.3
    for d0, y0, d1, y1, lab in edges:
        x0, x1 = X(d0) + 0.95, X(d1) - (0.05 if d1 < maxd + 1 else 0)
        ax.plot([x0, (x0 + x1) / 2, (x0 + x1) / 2, x1], [y0, y0, y1, y1], color=LINE, lw=1.2, zorder=1)
        ax.text((x0 + x1) / 2 + 0.07, y0 + 0.45 * (y1 - y0), lab, fontsize=7.5, color=MUTED, ha="left", va="center", zorder=3,
                bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none"))
    for n, d, y in nodes:
        ax.add_patch(FancyBboxPatch((X(d) - 0.95, y - 0.26), 1.9, 0.52, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc="white", ec=ROSE, lw=1.4, zorder=2))
        ax.text(X(d), y, q(n["feature"]), ha="center", va="center", fontsize=9, fontweight="bold", color=INK, zorder=3)
    lx = X(maxd + 1) - 0.1
    for n, d, y in leaves:
        x = X(d) - 0.95
        # leaves are drawn in one column on the right, joined by a thin line when they sit at a lower depth
        if d <= maxd:
            ax.plot([X(d) - 0.05, lx], [y, y], color=LINE, lw=1.2, ls=(0, (2, 2)), zorder=1)
        top = n["groups"][0] if n["groups"] else ["-", 0]
        second = n["groups"][1] if len(n["groups"]) > 1 else None
        ax.add_patch(FancyBboxPatch((lx, y - 0.26), 3.6, 0.52, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc=ROSE_SOFT, ec="none", zorder=2))
        ax.text(lx + 0.1, y - 0.07, g(top[0]), ha="left", va="center", fontsize=8.6, fontweight="bold", color=INK, zorder=3)
        sub = f"{n['papers']} studies" + (f" · then {g(second[0]).lower()}" if second else "")
        ax.text(lx + 0.1, y + 0.14, sub, ha="left", va="center", fontsize=7.3, color=MUTED, zorder=3)
    ax.set_xlim(-1.1, lx + 3.8); ax.set_ylim(nl - 0.4, -0.6); ax.axis("off")
    m = t["metrics"]
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.text(0.01, 0.005, f"Trained on {m['papers']:,} studies that describe symptoms. On unseen studies the right group is first "
             f"{round(m['top1'] * 100)}% of the time ({round(m['baseline_top1'] * 100)}% by chance) and in the top three "
             f"{round(m['top3'] * 100)}% of the time. Each end point lists the best-fitting group of studies; it is not a diagnosis.",
             fontsize=7.3, color=MUTED, wrap=True)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97)); fig.savefig(out, facecolor="white"); plt.close(fig)

if __name__ == "__main__":
    main(*sys.argv[1:4])
