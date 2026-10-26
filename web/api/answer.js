// POST {question, profile, evidence:[{n,title,year,journal,study_type,n_female,population,passages[]}]} -> {text}
// Writes a cited plain-language summary of the retrieved women-only studies.
const { claude, handler, clip } = require("./_claude");

const SYSTEM = `You summarise research for a woman who is looking up her own health. Every study you are given had only women or girls as participants.
Write for a curious non-specialist, in short paragraphs (and at most one short bullet list), 150-280 words.
Rules:
- Use ONLY the numbered studies provided. Cite them like [3] after each claim. Never invent studies, numbers or findings.
- Say what kind of evidence it is (trial, cohort, survey, interviews) and roughly how many women, and say plainly when evidence is thin, small, mixed or only about a specific group (e.g. postmenopausal women in China).
- Relate findings to her situation only where the studies fit it; point out when they do not.
- Do not diagnose, do not recommend starting, stopping or dosing any medicine. End with one sentence suggesting which kind of clinician she could discuss this with.
- If she mentions symptoms that can be urgent (chest pain, breathing trouble, heavy bleeding in pregnancy, thoughts of self-harm), first tell her to seek urgent care.`;

module.exports = handler(async (b) => {
  const ev = Array.isArray(b.evidence) ? b.evidence.slice(0, 14) : [];
  if (!ev.length) return { text: "" };
  const p = b.profile || {};
  const profile = b.profile
    ? `About her: age ${p.age || "not given"}; life stage ${clip(p.stage, 30) || "not given"}; symptoms: ${clip(p.symptoms, 500) || "-"}; conditions: ${clip(p.history, 400) || "-"}; medicines: ${clip(p.meds, 400) || "-"}.`
    : "";
  const studies = ev.map((e) =>
    `[${e.n}] ${clip(e.title, 300)} (${e.journal || "journal n/a"}, ${e.year || "year n/a"}; design: ${e.study_type || "not stated"}; women: ${e.n_female || "not stated"}; population: ${clip(e.population, 120) || "-"})\n` +
    (e.passages || []).slice(0, 2).map((t) => `  - ${clip(t, 700)}`).join("\n")
  ).join("\n\n");
  const user = `Question: ${clip(b.question, 500) || "What does this research say?"}\n${profile}\n\nStudies:\n${studies}`;
  const text = await claude({ system: SYSTEM, user, model: process.env.ANSWER_MODEL || "claude-sonnet-5-5", maxTokens: 900 });
  return { text: text.trim() };
});
