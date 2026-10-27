// GET /api/paper?id=PMC1234567 — one study in full, for people and agents.
// Returns metadata, women-only label + evidence, the structured evidence record, and:
//   - open licence (CC-BY / CC0): the full text by section, fetched live from Europe PMC
//   - other licences: abstract + link only (reuse restricted)
const { select, params, send } = require("./_db");

const COLS = "id,pmid,pmcid,doi,title,authors,journal,pub_year,abstract,license,commercial_use_ok,label,label_reasons," +
  "female_evidence,n_female,population,study_type,topic,evidence,source_url";

const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&amp;/g, "&");
const text = (s) => decode(s.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();
const SKIP = /acknowledg|funding|conflict|competing|author contrib|supplement|supporting information|data availab|abbreviation|consent|ethic|declaration/i;

function sectionsFromJats(xml, maxChars) {
  const body = (xml.match(/<body[\s\S]*<\/body>/) || [""])[0]
    .replace(/<(table-wrap|fig|disp-formula|ref-list)[\s\S]*?<\/\1>/g, " ")
    .replace(/<xref[^>]*>[\s\S]*?<\/xref>/g, "");
  const out = [];
  let current = { title: "Text", paragraphs: [] }, total = 0;
  const re = /<title>([\s\S]*?)<\/title>|<p(?:\s[^>]*)?>([\s\S]*?)<\/p>/g;
  let m;
  while ((m = re.exec(body)) && total < maxChars) {
    if (m[1] !== undefined) {
      if (current.paragraphs.length) out.push(current);
      current = { title: text(m[1]) || "Section", paragraphs: [] };
    } else {
      const t = text(m[2]);
      if (t && !SKIP.test(current.title)) { current.paragraphs.push(t); total += t.length; }
    }
  }
  if (current.paragraphs.length) out.push(current);
  return out.filter((s) => !SKIP.test(s.title)).map((s) => ({ title: s.title, text: s.paragraphs.join("\n\n") }));
}

module.exports = async (req, res) => {
  const p = params(req);
  const id = String(p.id || "").trim();
  if (!/^(PMC\d+|MED\d+)$/.test(id)) return send(res, 400, { error: "bad_id", hint: "Use an id from /api/search, e.g. ?id=PMC1234567" });
  try {
    const rows = await select("papers", `select=${COLS}&id=eq.${id}`);
    if (!rows.length) return send(res, 404, { error: "not_found" });
    const paper = rows[0];
    let full_text = null, note = null;
    if (paper.commercial_use_ok && paper.pmcid) {
      const r = await fetch(`https://www.ebi.ac.uk/europepmc/webservices/rest/${paper.pmcid}/fullTextXML`, {
        headers: { "User-Agent": "FrontiersBusiness-evidence/0.2" },
      });
      if (r.ok) full_text = sectionsFromJats(await r.text(), Number(p.max_chars) || 60000);
      else note = `Full text unavailable from Europe PMC right now (${r.status}).`;
    } else {
      note = "Licence does not allow reuse of the full text; abstract and link only.";
    }
    return send(res, 200, { ...paper, full_text, note });
  } catch (e) {
    return send(res, 502, { error: String(e.message) });
  }
};
