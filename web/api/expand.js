// POST {symptoms, age, stage, history, meds, question} -> {groups:[{label, query}]}
// Turns everyday descriptions into Postgres web-search queries over medical literature.
const { claude, handler, clip } = require("./_claude");

const SYSTEM = `You turn a woman's own description of her symptoms, conditions and medicines into literature search queries.
Return JSON only: {"groups":[{"label":"short plain-English heading","query":"search query"}]}
Rules:
- 2 to 6 groups: one per distinct symptom, condition or medicine theme, plus one for her question if she asked one.
- Each query uses Postgres websearch syntax: alternatives joined with OR, multi-word terms in "double quotes". Example: "hot flushes" OR "hot flashes" OR vasomotor
- Include the everyday word AND the clinical terms researchers use (e.g. period pain -> dysmenorrhea OR dysmenorrhoea OR "menstrual pain"). British and American spellings.
- 3 to 8 alternatives per query. Never use AND, NOT, parentheses or the word "women" (every study is already women-only).
- Labels are short, in the person's own language, e.g. "Night sweats", "Your levothyroxine".
- Do not diagnose or add conditions she did not mention.`;

module.exports = handler(async (b) => {
  const user = [
    `Symptoms: ${clip(b.symptoms, 800) || "-"}`,
    `Age: ${b.age || "-"}`,
    `Life stage: ${clip(b.stage, 40) || "-"}`,
    `Diagnosed conditions: ${clip(b.history, 600) || "-"}`,
    `Medicines/treatments: ${clip(b.meds, 600) || "-"}`,
    `Question: ${clip(b.question, 400) || "-"}`,
  ].join("\n");
  const text = await claude({ system: SYSTEM, user, model: process.env.EXPAND_MODEL || "claude-haiku-5-5", maxTokens: 700 });
  const json = JSON.parse(text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1));
  const groups = (json.groups || [])
    .filter((g) => g && g.label && g.query)
    .slice(0, 6)
    .map((g) => ({ label: clip(g.label, 80), query: clip(g.query, 400).replace(/[()]/g, " ") }));
  return { groups };
});
