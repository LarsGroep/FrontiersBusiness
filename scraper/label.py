"""Decide whether a paper's study population was women only.

Layer 1 (always): MeSH tags + rule-based scan of abstract and methods.
Layer 2 (optional): Claude reads abstract + methods and returns a structured verdict,
                    enabled when ANTHROPIC_API_KEY is set.
"""
from __future__ import annotations

import json
import os
import re

import requests

# Words that suggest male participants. \b keeps "men" from matching "women" and "male" from "female".
MALE_RX = re.compile(
    r"\b(men|man|males?|boys?|fathers?|sons|husbands?|male participants|male patients|"
    r"both sexes|both genders|men and women|women and men|sex[- ]matched|sex[- ]stratified|"
    r"\d+(?:\.\d+)?\s*%\s*(?:were\s+)?male)\b",
    re.I,
)
# Male words that usually do NOT mean male participants in a women-only study.
BENIGN_MALE_CONTEXT = re.compile(
    r"(partner|spouse|husband|father|son|infant|offspring|newborn|baby|neonat|fetus|fetal|child|"
    r"previous stud|prior stud|than men|unlike men|compared (?:to|with) men|in men,|among men in|literature|"
    r"male[- ]dominated|male[- ]factor|male infertility|sex of the (?:infant|baby|child|fetus))",
    re.I,
)
FEMALE_N_RX = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d+)\s+(?:[a-z\-]+\s+){0,3}?"
    r"(women|females|female participants|female patients|girls|mothers|pregnant women|"
    r"postmenopausal women|premenopausal women|participants|patients|subjects)\b",
    re.I,
)
POPULATION_TERMS = [
    "pregnant", "postpartum", "postmenopausal", "premenopausal", "perimenopausal", "menopausal",
    "breast cancer", "ovarian", "cervical", "endometri", "polycystic ovary", "pcos", "gestational",
    "infertil", "lactating", "breastfeeding", "athlete", "older women", "adolescent girls", "mothers",
]
STUDY_TYPES = [
    ("randomized controlled trial", re.compile(r"randomi[sz]ed (controlled )?trial|\bRCT\b", re.I)),
    ("cohort", re.compile(r"cohort|longitudinal|prospective", re.I)),
    ("case-control", re.compile(r"case[- ]control", re.I)),
    ("cross-sectional", re.compile(r"cross[- ]sectional|survey", re.I)),
    ("qualitative", re.compile(r"qualitative|interview|focus group", re.I)),
    ("meta-analysis", re.compile(r"meta[- ]analys", re.I)),
]


def _snippet(text: str, m: re.Match, width: int = 90) -> str:
    a, b = max(0, m.start() - width), min(len(text), m.end() + width)
    return text[a:b].replace("\n", " ")


def rule_label(paper: dict, methods_text: str) -> dict:
    mesh = {m.lower() for m in paper.get("mesh_terms") or []}
    reasons = []
    has_female, has_male, has_humans = "female" in mesh, "male" in mesh, "humans" in mesh
    if not (has_female and has_humans):
        reasons.append("mesh_missing_female_or_humans")
    if has_male:
        reasons.append("mesh_male")

    scan = f"{paper.get('title','')} {paper.get('abstract','')} {methods_text}"
    hard, soft = [], []
    for m in MALE_RX.finditer(scan):
        snip = _snippet(scan, m)
        (soft if BENIGN_MALE_CONTEXT.search(snip) else hard).append(snip)

    # Evidence + sample size: first sentence mentioning a count of women/participants.
    n_female, evidence = None, None
    for m in FEMALE_N_RX.finditer(scan):
        try:
            n = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if 5 <= n <= 5_000_000 and not (1900 <= n <= 2100):
            n_female, evidence = n, _snippet(scan, m, 120)
            break

    low = scan.lower()
    population = ", ".join(t for t in POPULATION_TERMS if t in low)[:200] or None
    study_type = next((name for name, rx in STUDY_TYPES if rx.search(scan)), None)

    if has_male or not (has_female and has_humans):
        label = "rejected"
    elif hard:
        label = "female_only_probable"
        reasons.append(f"male_terms_in_text:{len(hard)}")
    elif not methods_text:
        label = "female_only_unverified"
        reasons.append("no_methods_section")
    else:
        label = "female_only_verified"

    return {
        "label": label,
        "label_reasons": reasons,
        "male_mentions": len(hard),
        "male_snippets": hard[:5],
        "female_evidence": evidence,
        "n_female": n_female,
        "population": population,
        "study_type": study_type,
    }


LLM_PROMPT = """You are screening scientific papers for a dataset of studies whose participants were ONLY women or girls (human females).
Read the title, abstract and methods below and answer with JSON only, no prose:
{{"female_only": true|false|null, "n_female": int|null, "n_male": int|null, "population": "short description", "study_type": "e.g. RCT, cohort, cross-sectional, qualitative, case series", "evidence_quote": "exact sentence that shows who the participants were"}}
Rules: female_only is true only if every human participant whose data was analysed was female. Male partners, infants or comparison literature do not count as participants. Use null if the text does not say.

TITLE: {title}
ABSTRACT: {abstract}
METHODS: {methods}"""


def llm_label(paper: dict, methods_text: str) -> dict | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    prompt = LLM_PROMPT.format(title=paper.get("title", ""), abstract=paper.get("abstract", "")[:3000], methods=methods_text[:6000])
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.getenv("LABEL_MODEL", "claude-haiku-5-5"), "max_tokens": 400,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=60,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"]
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as e:  # never let the verifier break the scrape
        return {"error": str(e)[:200]}


def combine(rule: dict, llm: dict | None) -> dict:
    """LLM verdict can upgrade 'probable'/'unverified' or downgrade anything to rejected."""
    if not llm or "error" in llm:
        return rule
    out = dict(rule, llm_label=llm)
    fo = llm.get("female_only")
    if fo is False or (llm.get("n_male") or 0) > 0:
        out["label"] = "rejected"
        out["label_reasons"] = rule["label_reasons"] + ["llm_says_not_female_only"]
    elif fo is True and rule["label"] != "rejected":
        out["label"] = "female_only_verified"
        out["label_reasons"] = rule["label_reasons"] + ["llm_confirmed"]
    if llm.get("n_female"):
        out["n_female"] = llm["n_female"]
    if llm.get("evidence_quote"):
        out["female_evidence"] = llm["evidence_quote"]
    out["population"] = llm.get("population") or rule["population"]
    out["study_type"] = llm.get("study_type") or rule["study_type"]
    return out
