// GET or POST /api/search — evidence search for people and agents.
// Params: q (required; web-search syntax: words, OR, "phrases"), k (studies, 1-25, default 10),
//         include_probable (bool), min_year, topics (comma list), population (comma list of
//         life-stage terms to boost, e.g. postmenopaus), open_licence_only (bool)
// Returns studies grouped by paper with their best passages and evidence records.
const { rpc, select, params, list, int, send } = require("./_db");

const yes = (v) => v === true || v === "true" || v === "1";

module.exports = async (req, res) => {
  if (req.method === "OPTIONS") {
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type");
    return res.status(204).end();
  }
  const p = params(req);
  const q = String(p.q || "").slice(0, 500).trim();
  if (!q) return send(res, 400, { error: "missing_q", hint: "Add ?q=your+search, e.g. ?q=hot flushes OR vasomotor" });
  const k = int(p.k, 10, 1, 25);
  try {
    const rows = await rpc("search_evidence", {
      q,
      match_count: Math.min(50, k * 2),
      labels: yes(p.include_probable) ? ["female_only_verified", "female_only_probable"] : ["female_only_verified"],
      min_year: p.min_year ? int(p.min_year, 0, 1900, 2100) : null,
      topics: list(p.topics),
      population_terms: list(p.population),
      commercial_only: yes(p.open_licence_only),
    });
    const papers = new Map();
    for (const r of rows) {
      if (!papers.has(r.paper_id)) {
        papers.set(r.paper_id, {
          id: r.paper_id, title: r.title, journal: r.journal, year: r.pub_year, doi: r.doi,
          url: r.source_url, label: r.label, study_type: r.study_type, n_women: r.n_female,
          population: r.population, topic: r.topic, open_licence: r.commercial_use_ok,
          matches_life_stage: r.population_match, score: Number(r.score.toFixed(5)), passages: [],
        });
      }
      papers.get(r.paper_id).passages.push({ section: r.section, text: r.content });
    }
    const out = [...papers.values()].slice(0, k);
    // Attach structured evidence records (present once Claude extraction has run).
    if (out.length) {
      const ev = await select("papers", `select=id,evidence&id=in.(${out.map((x) => `"${x.id}"`).join(",")})`).catch(() => []);
      const byId = Object.fromEntries(ev.map((e) => [e.id, e.evidence]));
      out.forEach((x) => (x.evidence = byId[x.id] || null));
    }
    return send(res, 200, { query: q, count: out.length, studies: out });
  } catch (e) {
    return send(res, 502, { error: String(e.message), hint: "The database may be warming up; retry once." });
  }
};
