"""Build the demo data for the website from the current catalogue: evidence graph, XGBoost decision tree, paper map.

  python -m pi.build_demo                 # web/graph/cv.json, tree-cv.json, papers-cv.json (t-SNE map)
  python -m pi.build_demo --eval          # also run the GraphRAG test questions (eval/graphrag/, pool_new.json)
Run daily by the "Evidence graph" workflow, so papers the Pi collects show up on /graph without manual steps.
"""
from __future__ import annotations

import argparse
import json

from . import graph_test, trees
from .graph import EvidenceGraph


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="C14 Cardiovascular Diseases")
    ap.add_argument("--eval", action="store_true")
    a = ap.parse_args()
    g = EvidenceGraph(a.area, with_sections=True)
    out = {"graph": g.export("web/graph/cv.json"), "trees": trees.train(g, "web/graph/tree-cv.json"),
           "map": trees.export_map(g, "web/graph/papers-cv.json")}
    if a.eval:
        out["eval"] = graph_test.evaluate(g, "eval/graphrag")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
