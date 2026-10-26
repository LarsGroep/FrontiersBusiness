"""Parse JATS full-text XML into named sections and RAG-sized chunks."""
from __future__ import annotations

import re
from lxml import etree

SKIP_SECTIONS = re.compile(r"acknowledg|funding|conflict|competing|author contrib|supplement|data availab|abbreviation|ethics declar|consent for publ", re.I)

SECTION_MAP = [
    ("methods", re.compile(r"method|material|participant|subject|patient|design|procedure|population|setting|sample|statistic|measure", re.I)),
    ("results", re.compile(r"result|finding", re.I)),
    ("discussion", re.compile(r"discussion|limitation|strength", re.I)),
    ("conclusion", re.compile(r"conclusion|summary|implication", re.I)),
    ("introduction", re.compile(r"introduction|background|rationale", re.I)),
]


def normalise_section(title: str, sec_type: str | None = None) -> str:
    probe = f"{sec_type or ''} {title or ''}"
    for name, rx in SECTION_MAP:
        if rx.search(probe):
            return name
    return "other"


def _text(el) -> str:
    # Drop citations/table footnotes noise, keep readable text.
    for bad in el.xpath(".//xref | .//table-wrap | .//fig | .//disp-formula"):
        tail = bad.tail
        parent = bad.getparent()
        if parent is not None:
            prev = bad.getprevious()
            if tail:
                if prev is not None:
                    prev.tail = (prev.tail or "") + tail
                else:
                    parent.text = (parent.text or "") + tail
            parent.remove(bad)
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def parse_sections(xml: str) -> list[tuple[str, str, str]]:
    """Return [(normalised_section, original_title, text)] for top-level body sections."""
    try:
        root = etree.fromstring(xml.encode("utf-8"), parser=etree.XMLParser(recover=True, huge_tree=True))
    except etree.XMLSyntaxError:
        return []
    if root is None:
        return []
    body = root.find(".//body")
    if body is None:
        return []
    out: list[tuple[str, str, str]] = []
    top_secs = body.findall("sec")
    if not top_secs:
        paras = " ".join(_text(p) for p in body.iter("p"))
        return [("other", "", paras)] if paras else []
    for sec in top_secs:
        title_el = sec.find("title")
        title = _text(title_el) if title_el is not None else ""
        if SKIP_SECTIONS.search(title):
            continue
        name = normalise_section(title, sec.get("sec-type"))
        paras = [_text(p) for p in sec.iter("p")]
        text = " ".join(p for p in paras if p)
        if text:
            out.append((name, title, text))
    return out


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> list[str]:
    """Split on sentence boundaries into ~size-char chunks with overlap."""
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text)
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 > size and cur:
            chunks.append(cur.strip())
            cur = cur[-overlap:] + " " + s if overlap else s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur.strip():
        chunks.append(cur.strip())
    # hard-split anything still too long (e.g. no punctuation)
    final = []
    for c in chunks:
        while len(c) > size * 1.6:
            final.append(c[:size])
            c = c[size - overlap:]
        final.append(c)
    return final


def build_chunks(paper: dict, sections: list[tuple[str, str, str]], max_chunks: int = 24) -> list[dict]:
    chunks = []
    if paper.get("abstract"):
        chunks.append({"section": "abstract", "content": paper["abstract"]})
    for name, _title, text in sections:
        if name == "introduction":
            continue  # background mostly cites other (often mixed-sex) studies
        for c in chunk_text(text):
            chunks.append({"section": name, "content": c})
    chunks = chunks[:max_chunks]
    for i, c in enumerate(chunks):
        c["chunk_index"] = i
    return chunks
