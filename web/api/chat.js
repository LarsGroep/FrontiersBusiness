// POST /api/chat — Anarcha AI research guide (information product, see _guardrails.js).
// Body: { messages: [{role:"user"|"assistant", content}], profile?: {age, stage, symptoms, history, meds}, consent?: true }
// Returns: { urgent: string|null, answer: string, studies: [...], queries: [...] }
//
// Privacy by design:
// - Stateless: the conversation lives only in the browser tab; each request carries it and it is dropped afterwards.
// - Nothing from the request is written to a database, file or log (no console.log of content anywhere).
// - The profile is minimised (age -> 5-year band, identifiers stripped) before any AI call.
// - Searching the study database only ever receives search terms, never the profile itself.
// - A profile is only used when the person ticked the consent box (explicit consent, GDPR art. 9(2)(a)).
const { claude, handler, clip } = require("./_claude");
const { rpc } = require("./_db");
const G = require("./_guardrails");

const PLAN = `You turn a chat about women's health into literature search queries over a database of women-only studies.
Return JSON only: {"queries":["...","..."]}
- 1 to 3 queries for the LATEST question, using the profile only to add relevant terms (life stage, condition, medicine).
- Postgres websearch syntax: alternatives joined with OR, multi-word terms in "double quotes", 3-8 alternatives, everyday AND clinical terms, British and American spellings.
- Never use AND, NOT, parentheses or the word "women". Do not add conditions she did not mention.`;

const STAGE_TERMS = { "pregnant": ["pregnan"], "after birth / breastfeeding": ["postpartum", "breastfeed"], "perimenopause": ["perimenopaus", "menopaus"],
  "after menopause": ["postmenopaus"], "trying to conceive": ["infertil", "fertility"], "having periods": ["premenopaus", "menstrua"] };

function cleanMessages(raw) {
  const msgs = (Array.isArray(raw) ? raw : [])
    .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
    .slice(-8)
    .map((m) => ({ role: m.role, content: G.scrub(m.content, m.role === "user" ? 1500 : 2500) }));
  while (msgs.length && msgs[0].role !== "user") msgs.shift();
  if (!msgs.length || msgs[msgs.length - 1].role !== "user") throw new Error("bad_messages");
  return msgs;
}

async function retrieve(queries, profile) {
  const pop = profile && STAGE_TERMS[profile.life_stage] ? STAGE_TERMS[profile.life_stage] : null;
  const results = await Promise.all(queries.map((q) =>
    rpc("search_evidence", { q, match_count: 16, labels: ["female_only_verified"], min_year: null, topics: null,
      population_terms: pop, commercial_only: false }).catch(() => [])));
  const papers = new Map();
  // round-robin over the queries so each part of the question gets studies
  for (let i = 0; i < 16 && papers.size < 10; i++) {
    for (const rows of results) {
      const r = rows[i];
      if (!r) continue;
      const p = papers.get(r.paper_id) || { id: r.paper_id, title: r.title, journal: r.journal, year: r.pub_year, url: r.source_url,
        study_type: r.study_type, n_women: r.n_female, population: r.population, matches_life_stage: r.population_match, passages: [] };
      if (p.passages.length < 2 && !p.passages.includes(r.content)) p.passages.push(r.content);
      if (papers.size < 10 || papers.has(r.paper_id)) papers.set(r.paper_id, p);
    }
  }
  return [...papers.values()].map((p, i) => ({ n: i + 1, ...p }));
}

function studiesBlock(studies) {
  return studies.map((s) =>
    `[${s.n}] ${clip(s.title, 300)} (${s.journal || "journal n/a"}, ${s.year || "year n/a"}; design: ${s.study_type || "not stated"}; ` +
    `women: ${s.n_women || "not stated"}; population: ${clip(s.population, 120) || "-"}${s.matches_life_stage ? "; matches her life stage" : ""})\n` +
    s.passages.map((t) => `  - ${clip(t, 700)}`).join("\n")).join("\n\n");
}

module.exports = handler(async (b) => {
  const msgs = cleanMessages(b.messages);
  const profile = b.consent === true ? G.minimiseProfile(b.profile) : null;
  const latest = msgs[msgs.length - 1].content;

  // 1. Emergency check first, deterministic, before any AI call.
  const urgentText = [latest, profile && profile.symptoms].filter(Boolean).join(" ");
  const urgent = G.isUrgent(urgentText) ? G.URGENT_NOTICE : null;

  // 2. Plan search queries (small, fast model); the database only receives these queries.
  const history = msgs.slice(-4, -1).map((m) => `${m.role}: ${clip(m.content, 400)}`).join("\n");
  const planText = await claude({
    system: PLAN, model: process.env.EXPAND_MODEL || "claude-haiku-5-5", maxTokens: 300,
    user: `${G.profileText(profile)}\nEarlier in the chat:\n${history || "-"}\nLatest question: ${clip(latest, 800)}`,
  });
  let queries = [];
  try { queries = JSON.parse(planText.slice(planText.indexOf("{"), planText.lastIndexOf("}") + 1)).queries || []; } catch { /* fall through */ }
  queries = queries.filter((q) => typeof q === "string" && q.trim()).slice(0, 3).map((q) => clip(q, 300).replace(/[()]/g, " "));
  if (!queries.length) queries = [clip(latest, 200).replace(/[()"]/g, " ")];

  // 3. Retrieve women-only studies.
  const studies = await retrieve(queries, profile);

  // 4. Answer under the guardrail policy.
  const context = `${G.profileText(profile)}\n${urgent ? "The app is showing her an urgent-care notice.\n" : ""}\n` +
    (studies.length ? `Studies (women-only):\n${studiesBlock(studies)}` : "No matching studies were found in the database.");
  const convo = msgs.map((m, i) => (i === msgs.length - 1 ? { role: "user", content: `${context}\n\nHer message: ${m.content}` } : m));
  const model = process.env.ANSWER_MODEL || "claude-sonnet-5-5";
  let answer = await claude({ system: G.POLICY, messages: convo, model, maxTokens: 1000 });

  // 5. Output check; one corrective rewrite, then a safe fallback.
  let issues = G.checkAnswer(answer);
  if (issues.length) {
    answer = await claude({
      system: G.POLICY, model, maxTokens: 1000,
      messages: [...convo, { role: "assistant", content: answer },
        { role: "user", content: `Rewrite your answer. It broke these rules: ${issues.join(", ")}. Report only what the studies found in women, with citations; no diagnosis, personal risk, treatment or dosing advice for her.` }],
    });
    issues = G.checkAnswer(answer);
    if (issues.length) {
      answer = "I can't give personal medical advice, but here is the research that matches your question. " +
        "The studies are listed below; a GP, gynaecologist or pharmacist can help you weigh them for your situation.";
    }
  }
  return {
    urgent,
    answer: G.withDisclaimer(answer),
    queries,
    studies: studies.map(({ passages, ...s }) => ({ ...s, passage: clip(passages[0], 400) })),
  };
});
