"""Ask the women-only evidence base a question.

  export SUPABASE_URL=https://jvlrbsusjvuxsgijgxpb.supabase.co
  export SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
  export ANTHROPIC_API_KEY=...        # optional: generates a cited answer
  python -m rag.ask "Does resistance training improve bone density in postmenopausal women?"
"""
from __future__ import annotations

import argparse
import os

import requests

from scraper.embed import embed_query


def retrieve(question: str, k: int = 8, min_year: int | None = None, include_probable: bool = True) -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/match_chunks"
    key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
    labels = ["female_only_verified"] + (["female_only_probable"] if include_probable else [])
    body = {"query_embedding": embed_query(question), "match_count": k, "labels": labels, "min_year": min_year}
    r = requests.post(url, json=body, headers={"apikey": key, "Content-Type": "application/json"}, timeout=60)
    r.raise_for_status()
    return r.json()


def answer(question: str, hits: list[dict]) -> str:
    ctx = "\n\n".join(
        f"[{i+1}] {h['title']} ({h['journal']}, {h['pub_year']}; n_female={h['n_female']}; {h['study_type']}; doi:{h['doi']})\n"
        f"Section: {h['section']}\n{h['content']}"
        for i, h in enumerate(hits)
    )
    prompt = (
        "Answer the question using ONLY the excerpts below. Every excerpt comes from a study whose participants were women only. "
        "Cite excerpts as [n]. Mention sample sizes and study types, and say plainly when the evidence is thin or mixed.\n\n"
        f"QUESTION: {question}\n\nEXCERPTS:\n{ctx}"
    )
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": os.getenv("ANSWER_MODEL", "claude-sonnet-5-5"), "max_tokens": 1200,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--min-year", type=int)
    ap.add_argument("--verified-only", action="store_true")
    a = ap.parse_args()
    hits = retrieve(a.question, a.k, a.min_year, not a.verified_only)
    for i, h in enumerate(hits, 1):
        print(f"[{i}] {h['similarity']:.3f}  {h['title']} ({h['pub_year']}) {h['section']}  doi:{h['doi']}")
    if os.getenv("ANTHROPIC_API_KEY") and hits:
        print("\n" + answer(a.question, hits))


if __name__ == "__main__":
    main()
