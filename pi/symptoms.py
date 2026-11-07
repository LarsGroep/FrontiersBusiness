"""Symptom extraction pilot: which symptoms do women-only studies in a disease area report, and for which conditions?

  python -m pi.symptoms run --area "C14 Cardiovascular Diseases"     # extract + summary
  python -m pi.symptoms summary --area "C14 Cardiovascular Diseases" # summary + random sample for checking

Deterministic and auditable (no AI): a dictionary of MeSH "Signs and Symptoms" (C23.888) descriptors with all their
entry terms, plus plain-language terms for heart symptoms, matched in each paper's abstract and results/conclusion
sections. Mentions right after a negation ("no chest pain", "without dyspnea") are flagged, not counted. Every
mention keeps its sentence, so each symptom -> condition link can be traced to the study and the words it came from.

The output is the raw material for the "search map": which conditions women-only studies link to a symptom. It is
not used to tell anyone what they have (information product, see project notes).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import random
import re
from collections import Counter, defaultdict

from . import store
from .analysis import MODEL_DIR

SYMPTOM_TREE = "C23.888"
TOO_GENERIC = {"signs and symptoms", "symptoms", "symptom", "signs", "sign", "disease", "syndrome", "pain", "weight",
               "body weight", "obesity", "overweight", "birth weight", "weight gain", "weight loss", "thinness"}
# Plain-language and clinical variants for heart symptoms, mapped onto MeSH descriptor names. Women more often report
# "atypical" symptoms (fatigue, jaw/back/arm pain, nausea, breathlessness), so these are listed explicitly.
CARDIO_TERMS = {
    "Chest Pain": ["chest pain", "chest discomfort", "chest pressure", "chest tightness", "angina-like pain"],
    "Dyspnea": ["dyspnea", "dyspnoea", "shortness of breath", "breathlessness", "short of breath", "difficulty breathing"],
    "Fatigue": ["fatigue", "tiredness", "exhaustion", "unusual fatigue", "lack of energy"],
    "Palpitations": ["palpitations", "palpitation", "heart racing", "racing heart", "fluttering"],
    "Dizziness": ["dizziness", "lightheadedness", "light-headedness", "dizzy", "vertigo"],
    "Syncope": ["syncope", "fainting", "loss of consciousness", "presyncope"],
    "Nausea": ["nausea", "vomiting", "nauseated"],
    "Sweating": ["sweating", "diaphoresis", "cold sweat"],
    "Edema": ["edema", "oedema", "swelling of the legs", "ankle swelling", "leg swelling"],
    "Headache": ["headache", "headaches"],
    "Jaw Pain": ["jaw pain", "jaw discomfort"],
    "Back Pain": ["back pain", "upper back pain", "pain between the shoulder blades"],
    "Arm Pain": ["arm pain", "left arm pain", "pain in the arm"],
    "Neck Pain": ["neck pain"],
    "Abdominal Pain": ["abdominal pain", "epigastric pain", "stomach pain"],
    "Dyspepsia": ["indigestion", "dyspepsia", "heartburn"],
    "Sleep Wake Disorders": ["sleep disturbance", "sleep disturbances", "insomnia", "poor sleep"],
    "Cough": ["cough", "coughing"],
    "Visual Disturbances": ["visual disturbances", "blurred vision", "visual disturbance"],
    "Anxiety": ["anxiety", "feeling of doom", "sense of impending doom"],
}
# Patient-recognisable symptoms only. MeSH "Signs and Symptoms" also holds body-weight measures, fetal/neonatal
# signs and lab findings (birth weight, fetal distress, proteinuria), which are not things a woman notices.
PATIENT_SYMPTOMS = set(CARDIO_TERMS) | {
    "Angina Pectoris", "Angina, Stable", "Angina, Unstable", "Microvascular Angina", "Dyspnea, Paroxysmal",
    "Orthopnea", "Cyanosis", "Tachycardia", "Bradycardia", "Hot Flashes", "Night Sweats", "Hyperhidrosis",
    "Vomiting", "Constipation", "Diarrhea", "Flatulence", "Pelvic Pain", "Dysmenorrhea", "Dyspareunia",
    "Low Back Pain", "Musculoskeletal Pain", "Arthralgia", "Myalgia", "Chronic Pain", "Pain, Intractable",
    "Migraine Disorders", "Paresthesia", "Hypoesthesia", "Confusion", "Memory Disorders", "Cognitive Dysfunction",
    "Tremor", "Muscle Weakness", "Muscle Cramp", "Fever", "Pruritus", "Urinary Incontinence",
    "Urinary Incontinence, Stress", "Urinary Incontinence, Urge", "Nocturia", "Snoring", "Hoarseness",
    "Tinnitus", "Hearing Loss", "Vision, Low", "Anorexia", "Polydipsia", "Polyuria", "Mastodynia", "Hirsutism",
    "Alopecia", "Hemoptysis", "Epistaxis", "Intermittent Claudication",
}
# Sentences where a symptom is a covariate, a table/figure caption or an abbreviation list, not a finding.
NOT_A_FINDING = re.compile(r"\b(adjusted for|confound\w*|covariate\w*|abbreviations?|table \d|figure \d|fig\. \d|"
                           r"model \d|exclusion criteria|excluded if|were excluded)\b", re.I)
NEGATION = re.compile(r"\b(no|not|without|absence of|absent|denied|denies|free of|neither|nor|negative for)\b", re.I)
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
SECTIONS = ("results", "conclusion")

SCHEMA = """
create table if not exists symptom_mention (
  paper_id  text not null references papers(id) on delete cascade,
  symptom   text not null,     -- MeSH descriptor (or the heart-symptom group name)
  term      text not null,     -- the words matched
  section   text not null,     -- abstract | results | conclusion
  negated   boolean not null,
  sentence  text not null
);
create index if not exists symptom_mention_paper_idx on symptom_mention (paper_id);
create index if not exists symptom_mention_symptom_idx on symptom_mention (symptom);
"""


def lexicon() -> dict[str, str]:
    """term (lower case) -> symptom name. Cached as JSON next to the MeSH file."""
    cache = os.path.join(MODEL_DIR, "symptom_lexicon.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    from lxml import etree

    src = next((os.path.join(MODEL_DIR, f) for f in sorted(os.listdir(MODEL_DIR), reverse=True)
                if f.startswith("desc") and f.endswith(".gz")), None)
    if not src:
        raise RuntimeError("MeSH descriptor file not found; run  python -m pi.analysis mesh  first")
    with open(src, "rb") as probe:
        packed = probe.read(2) == b"\x1f\x8b"
    terms: dict[str, str] = {}
    with (gzip.open(src, "rb") if packed else open(src, "rb")) as fh:
        for _, el in etree.iterparse(fh, events=("end",), tag="DescriptorRecord"):
            trees = [t.text for t in el.findall("TreeNumberList/TreeNumber")]
            if any(t.startswith(SYMPTOM_TREE) for t in trees):
                name = el.findtext("DescriptorName/String")
                for s in el.iterfind(".//Term/String"):
                    t = s.text.lower().strip()
                    if len(t) >= 4 and t not in TOO_GENERIC and "," not in t:
                        terms.setdefault(t, name)
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    for name, words in CARDIO_TERMS.items():
        for w in words:
            terms[w.lower()] = name
    with open(cache, "w") as f:
        json.dump(terms, f)
    return terms


def compile_matcher(terms: dict[str, str]) -> re.Pattern:
    alts = sorted((t for t, name in terms.items() if name in PATIENT_SYMPTOMS), key=len, reverse=True)   # longest first, so "upper back pain" wins over "back pain"
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in alts) + r")\b", re.I)


def extract(text: str, section: str, matcher: re.Pattern, terms: dict[str, str]):
    for sent in SENT.split(text or ""):
        if len(sent) > 1200 or NOT_A_FINDING.search(sent):
            continue
        for m in matcher.finditer(sent):
            before = sent[max(0, m.start() - 60):m.start()]
            neg = bool(NEGATION.search(" ".join(before.split()[-6:])))
            yield terms[m.group(1).lower()], m.group(1), section, neg, sent.strip()[:400]


def run(area: str) -> dict:
    conn = store.connect()
    conn.execute(SCHEMA); conn.commit()
    terms = lexicon()
    matcher = compile_matcher(terms)
    ids = [r[0] for r in conn.execute("select paper_id from paper_area where area = %s", (area,)).fetchall()]
    conn.execute("delete from symptom_mention where paper_id = any(%s)", (ids,)); conn.commit()
    n_mentions = 0
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        abstracts = dict(conn.execute("select id, abstract from papers where id = any(%s)", (chunk,)).fetchall())
        secs = defaultdict(list)
        for pid, kind, text in conn.execute("select paper_id, kind, text from sections where paper_id = any(%s) "
                                            "and kind = any(%s) order by paper_id, idx", (chunk, list(SECTIONS))):
            secs[pid].append((kind, text))
        rows = []
        for pid in chunk:
            seen = set()
            for sym, term, section, neg, sent in [*extract(abstracts.get(pid), "abstract", matcher, terms),
                                                  *(x for kind, t in secs[pid] for x in extract(t, kind, matcher, terms))]:
                key = (sym, section, neg, sent)
                if key not in seen:
                    seen.add(key)
                    rows.append((pid, sym, term, section, neg, sent))
        with conn.cursor() as c:
            c.executemany("insert into symptom_mention values (%s,%s,%s,%s,%s,%s)", rows)
        conn.commit()
        n_mentions += len(rows)
        print(f"  {min(i + 200, len(ids))}/{len(ids)} papers, {n_mentions} mentions", flush=True)
    conn.close()
    return {"area": area, "papers": len(ids), "mentions": n_mentions,
            "lexicon_terms": sum(1 for n in terms.values() if n in PATIENT_SYMPTOMS)}


def summary(area: str, sample: int = 40, seed: int = 7) -> dict:
    conn = store.connect()
    q = "select paper_id from paper_area where area = %(area)s"
    top = conn.execute(f"""select symptom, count(distinct paper_id) from symptom_mention
                           where not negated and paper_id in ({q}) group by 1 order by 2 desc limit 30""",
                       {"area": area}).fetchall()
    # symptom -> condition: the paper's own MeSH terms that fall in this area
    pairs = conn.execute(f"""select sm.symptom, c.term, count(distinct sm.paper_id) n
                             from symptom_mention sm
                             join paper_area pa on pa.paper_id = sm.paper_id and pa.area = %(area)s
                             cross join lateral unnest(pa.terms) as c(term)
                             where not sm.negated
                             group by 1, 2 having count(distinct sm.paper_id) >= 3 order by n desc limit 40""",
                         {"area": area}).fetchall()
    with_any = conn.execute(f"""select count(distinct paper_id) from symptom_mention
                                where not negated and paper_id in ({q})""", {"area": area}).fetchone()[0]
    total = conn.execute(f"select count(*) from ({q}) x", {"area": area}).fetchone()[0]
    neg = conn.execute(f"select count(*) filter (where negated), count(*) from symptom_mention where paper_id in ({q})",
                       {"area": area}).fetchone()
    rows = conn.execute(f"""select paper_id, symptom, term, section, negated, sentence from symptom_mention
                            where paper_id in ({q})""", {"area": area}).fetchall()
    random.Random(seed).shuffle(rows)
    conn.close()
    out = {"area": area, "papers": total, "papers_with_symptoms": with_any, "mentions": neg[1], "negated": neg[0],
           "top_symptoms": [{"symptom": s, "papers": n} for s, n in top],
           "symptom_condition": [{"symptom": s, "condition": c, "papers": n} for s, c, n in pairs],
           "sample": [dict(zip(["paper_id", "symptom", "term", "section", "negated", "sentence"], r)) for r in rows[:sample]]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["run", "summary"])
    ap.add_argument("--area", default="C14 Cardiovascular Diseases")
    ap.add_argument("--out", default=None, help="write the summary JSON here")
    a = ap.parse_args()
    if a.step == "run":
        print(json.dumps(run(a.area), indent=2))
    res = summary(a.area)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(res, f, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "sample"}, indent=1))
    for s in res["sample"][:25]:
        print(f"- [{s['symptom']}{' NEG' if s['negated'] else ''}] {s['paper_id']} {s['section']}: {s['sentence'][:220]}")


if __name__ == "__main__":
    main()
