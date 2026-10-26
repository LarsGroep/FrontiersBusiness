"""Europe PMC client: search for women-only human studies and fetch open-access full text."""
from __future__ import annotations

import time
from typing import Iterator

import requests

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
HEADERS = {"User-Agent": "FrontiersBusiness-women-evidence/0.1 (github.com/LarsGroep/FrontiersBusiness)"}

# First-pass filter (verified live: ~110k hits, Oct 2026): indexers tagged the study population as human + female and NOT male.
# Open access + full text in Europe PMC so the RAG can use methods/results, not just abstracts.
# Reviews/editorials excluded: we want primary data from women.
DEFAULT_QUERY = (
    # Europe PMC exposes MeSH headings through the KW field (there is no MESH field).
    '(KW:"Female" AND KW:"Humans" AND OPEN_ACCESS:Y AND HAS_FT:Y AND SRC:MED) '
    'NOT KW:"Male" '
    'NOT PUB_TYPE:"review" NOT PUB_TYPE:"editorial" NOT PUB_TYPE:"comment" '
    'NOT PUB_TYPE:"letter" NOT PUB_TYPE:"case reports" '
    # The methods section itself must talk about women as the study population.
    'AND METHODS:("women" OR "female participants" OR "female patients" OR "girls")'
)


# Topic rotation so the dataset is not dominated by pregnancy / reproductive-health papers.
DEFAULT_TOPICS = [
    "cardiovascular OR hypertension OR stroke OR heart",
    "cancer OR tumor OR oncology",
    "depression OR anxiety OR mental health OR psychiatric",
    "diabetes OR obesity OR metabolic OR nutrition",
    "osteoporosis OR bone OR musculoskeletal OR exercise OR physical activity",
    "pharmacokinetics OR drug OR medication OR adverse events",
    "autoimmune OR lupus OR rheumatoid OR multiple sclerosis OR thyroid",
    "menopause OR perimenopause OR postmenopausal",
    "pregnancy OR maternal OR postpartum OR breastfeeding",
    "contraception OR fertility OR endometriosis OR PCOS OR menstrual",
    "HIV OR infection OR vaccine OR HPV",
    "pain OR migraine OR sleep OR fatigue",
    "violence OR social OR employment OR education",
    "ageing OR older OR dementia OR cognition",
]


def build_query(since_year: int | None = None, topic: str | None = None, base: str = DEFAULT_QUERY) -> str:
    q = base
    if since_year:
        q += f" AND PUB_YEAR:[{since_year} TO 2100]"
    if topic:
        q = f"({topic}) AND {q}"
    return q


def _get(url: str, params: dict | None = None, tries: int = 4) -> requests.Response:
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Europe PMC request failed: {url}")


def search(query: str, max_results: int, page_size: int = 100) -> tuple[int, Iterator[dict]]:
    """Return (hitCount, iterator over 'core' records)."""
    first = _get(f"{BASE}/search", {
        "query": query, "format": "json", "resultType": "core",
        "pageSize": min(page_size, max_results), "cursorMark": "*",
    }).json()
    hit_count = int(first.get("hitCount", 0))

    def it() -> Iterator[dict]:
        page, n = first, 0
        while True:
            results = page.get("resultList", {}).get("result", [])
            for rec in results:
                yield rec
                n += 1
                if n >= max_results:
                    return
            nxt = page.get("nextCursorMark")
            if not results or not nxt or nxt == page.get("request", {}).get("cursorMark"):
                return
            time.sleep(0.2)
            page = _get(f"{BASE}/search", {
                "query": query, "format": "json", "resultType": "core",
                "pageSize": page_size, "cursorMark": nxt,
            }).json()

    return hit_count, it()


def fetch_fulltext_xml(pmcid: str) -> str | None:
    r = _get(f"{BASE}/{pmcid}/fullTextXML")
    if r.status_code != 200 or not r.text.strip().startswith("<"):
        return None
    return r.text


def parse_record(rec: dict) -> dict:
    """Flatten a Europe PMC 'core' record into our paper fields."""
    mesh = [m.get("descriptorName", "") for m in rec.get("meshHeadingList", {}).get("meshHeading", [])]
    pub_types = rec.get("pubTypeList", {}).get("pubType", [])
    if isinstance(pub_types, str):
        pub_types = [pub_types]
    keywords = rec.get("keywordList", {}).get("keyword", [])
    license_ = (rec.get("license") or "").lower()
    journal = (rec.get("journalInfo", {}) or {}).get("journal", {}) or {}
    year = rec.get("pubYear")
    pmcid = rec.get("pmcid")
    return {
        "id": pmcid or f"MED{rec.get('pmid')}",
        "pmid": rec.get("pmid"),
        "pmcid": pmcid,
        "doi": rec.get("doi"),
        "title": (rec.get("title") or "").strip(),
        "authors": rec.get("authorString"),
        "journal": journal.get("title"),
        "pub_year": int(year) if year and str(year).isdigit() else None,
        "abstract": _strip_tags(rec.get("abstractText") or ""),
        "mesh_terms": mesh,
        "pub_types": pub_types,
        "keywords": keywords,
        "license": license_ or None,
        "commercial_use_ok": license_.startswith("cc0") or (license_.startswith(("cc by", "cc-by")) and "nc" not in license_),
        "source_url": f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else None,
    }


def _strip_tags(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()
