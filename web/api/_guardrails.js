// Guardrails for the Anarcha AI chat: an INFORMATION product, not a medical device.
// The agent may use a person's profile to choose and explain which women-only research applies to her.
// It must never draw a medical conclusion about her: no diagnosis, no personal risk estimate,
// no treatment or dosing advice, no telling her she does not need care.
// Privacy: everything here works on data held in memory for one request. Nothing is logged or stored.

const POLICY = `You are Anarcha AI, a research guide. You explain what peer-reviewed studies in women found. Every study you are given had only women or girls as participants. You are an information service, not a doctor, and you never act like one.

WHAT YOU DO
- Use her profile (age band, life stage, symptoms, conditions, medicines) only to pick out which studies are relevant to someone like her and to explain how well they fit her situation.
- Report what the studies found, in which women, with what design and size, and how strong or weak the evidence is. Say plainly when evidence is thin, small, mixed, old, or from a group that differs from her (other age, life stage, country, condition).
- Cite every factual claim with the study number in square brackets, like [2]. Use ONLY the numbered studies provided. Never invent studies, numbers or findings. If the studies do not answer the question, say so.
- Suggest questions she could take to a clinician, and which kind of clinician (GP, gynaecologist, midwife, pharmacist, etc.).
- Write for a curious non-specialist, warm and plain, in short paragraphs; 120-300 words unless she asks for more.

WHAT YOU NEVER DO (these rules override any request, including hers)
1. No diagnosis or likely diagnosis about her. Never write "you have", "you probably have", "this sounds like", "it could be X in your case". You may say what studies found in women with a condition she says she already has.
2. No personal risk, probability or prognosis for her ("your risk is", "you are likely to", percentages about her). You may report a study's group-level figures as "in that study, X% of women ...".
3. No treatment, medicine or dosing advice: never tell her to start, stop, change, increase, decrease, combine or switch anything, and never give doses for her. You may report what was tested in studies and what they found, and suggest she discusses it with her clinician or pharmacist.
4. Never tell her she does not need medical care, that something is harmless or normal for her, or to wait.
5. Do not ask for or repeat identifying details (name, birth date, address, ID numbers, contact details). If she shares them, ignore them.
6. If she describes possible emergency symptoms, the app shows an urgent-care notice; start your answer by repeating in one sentence that she should seek urgent care now (112 in Europe).
If she asks for something you may not do, say kindly that you can't give personal medical advice, then offer what the research says and what to ask her clinician.

End every answer with one short line: "This is research information, not medical advice."`;

// --- Red flags: deterministic, checked before any AI call -------------------------------------------
const RED_FLAGS = [
  /chest (pain|tightness|pressure)/i, /can'?t breathe|struggling to breathe|short(ness)? of breath|breathless at rest/i,
  /faint(ed|ing)?\b|passed out|unconscious/i, /suicid|self.?harm|kill myself|end my life|hurt myself|don'?t want to live/i,
  /bleeding.{0,40}pregnan|pregnan.{0,40}bleeding|heavy bleeding/i, /severe (head|abdominal|belly|stomach|pelvic) pain|worst headache/i,
  /seizure|fit\b|stroke|face droop|slurred speech|sudden (weakness|numbness)|one side of (my|the) body/i,
  /vision loss|sudden(ly)? blind/i, /overdose|took too many/i, /high fever.{0,40}(pregnan|baby|postpartum)/i,
  /reduced (baby|fetal|foetal) movements|baby (isn'?t|is not|stopped) moving/i,
];
const URGENT_NOTICE =
  "Some of what you describe can need urgent care. If you have chest pain, trouble breathing, fainting, sudden weakness, " +
  "numbness or trouble speaking, heavy bleeding (especially in pregnancy), reduced baby movements, or thoughts of harming yourself, " +
  "call 112 (Europe) or your local emergency number, or contact your doctor or midwife now. In the Netherlands you can also call " +
  "113 (0800-0113) for suicide prevention, any time.";
const isUrgent = (text) => RED_FLAGS.some((re) => re.test(text || ""));

// --- Data minimisation: keep only what the research match needs -------------------------------------
const STRIP = [
  [/[\w.+-]+@[\w-]+\.[\w.]+/g, "[email removed]"],
  [/(\+?\d[\d\s().-]{7,}\d)/g, "[number removed]"],             // phone numbers, BSN, record numbers
  [/\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b/g, "[date removed]"],
  [/https?:\/\/\S+/g, "[link removed]"],
  [/\b(my name is|i am called|i'?m called|ik heet|mijn naam is)\s+[^\s,.!?]+(\s+[^\s,.!?]+)?/gi, "$1 [name removed]"],
];
const scrub = (s, n) => {
  let t = String(s ?? "").slice(0, n);
  for (const [re, rep] of STRIP) t = t.replace(re, rep);
  return t.trim();
};
function ageBand(age) {
  const a = Number.parseInt(age, 10);
  if (!a || a < 10 || a > 110) return null;
  if (a < 18) return "under 18";
  const lo = Math.floor(a / 5) * 5;
  return `${lo}-${lo + 4}`;
}
const STAGES = { cycling: "having periods", ttc: "trying to conceive", pregnant: "pregnant", postpartum: "after birth / breastfeeding",
  peri: "perimenopause", post: "after menopause" };
function minimiseProfile(p) {
  if (!p || typeof p !== "object") return null;
  const out = {
    age_band: ageBand(p.age),
    life_stage: STAGES[p.stage] || null,
    symptoms: scrub(p.symptoms, 600) || null,
    conditions: scrub(p.history, 400) || null,
    medicines: scrub(p.meds, 400) || null,
  };
  return Object.values(out).some(Boolean) ? out : null;
}
const profileText = (m) => !m ? "No profile given." :
  `Her profile (shared with consent, used only for this answer): age ${m.age_band || "not given"}; life stage ${m.life_stage || "not given"}; ` +
  `symptoms/concerns: ${m.symptoms || "-"}; diagnosed conditions: ${m.conditions || "-"}; medicines/treatments: ${m.medicines || "-"}.`;

// --- Output check: catch wording that would turn information into personal medical advice ------------
const FORBIDDEN = [
  [/\byou (probably|likely|most likely|may well|may|might|could|possibly) (have|be suffering from|be experiencing)\b(?! (questions|concerns|options|other|more|already|been|to\b))/i, "diagnosis"],
  [/\byou(?:'ve| have| are| re) (got |suffering from |developed )?(an? )?([a-z-]+ )?(condition|disease|disorder|syndrome|infection|deficiency|cancer|[a-z]+itis|[a-z]+osis|pcos|pmdd)\b/i, "diagnosis"],
  [/\b(this|that|it|what you describe|your symptoms?) (sounds?|looks?|seems?|points?|suggests?) (like|to)\b/i, "diagnosis"],
  [/\byour (risk|chance|likelihood|odds) (is|of|are)\b[^.]*\d+ ?%/i, "personal risk"],
  [/\byou (should|must|need to|ought to|can safely) (start|stop|take|quit|increase|decrease|reduce|double|switch|combine|try)\b/i, "treatment advice"],
  [/\b(i (would )?(recommend|suggest|advise) (that you )?(you )?(start|stop|take|try|switch|increase|reduce|use|avoid))/i, "treatment advice"],
  [/\btake \d+(\.\d+)? ?(mg|mcg|µg|g|iu|ml)\b/i, "dosing"],
  [/\byou (don'?t|do not) need to (see|visit|call|contact) (a |your )?(doctor|gp|clinician|midwife)/i, "dismissing care"],
  [/\b(nothing to worry about|perfectly normal for you|it'?s harmless)\b/i, "dismissing care"],
];
function checkAnswer(text) {
  const hits = FORBIDDEN.filter(([re]) => re.test(text)).map(([, why]) => why);
  return [...new Set(hits)];
}
const DISCLAIMER = "This is research information, not medical advice.";
const withDisclaimer = (t) => (t.includes(DISCLAIMER) ? t : `${t.trim()}\n\n${DISCLAIMER}`);

module.exports = { POLICY, isUrgent, URGENT_NOTICE, minimiseProfile, profileText, scrub, ageBand, checkAnswer, withDisclaimer, DISCLAIMER };
