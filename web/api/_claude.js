// Shared helper for the optional Claude-powered endpoints.
// Never logs request content (privacy: the chat is stateless).
// Without ANTHROPIC_API_KEY the endpoints answer 503 and the page falls back to its built-in features.

const MAX_BODY = 60_000;

async function readJson(req) {
  if (req.body && typeof req.body === "object") return req.body;
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > MAX_BODY) throw new Error("too_large");
  }
  try {
    return raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error("bad_json");
  }
}

async function claude({ system, user, messages, model, maxTokens }) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": process.env.ANTHROPIC_API_KEY,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model,
      max_tokens: maxTokens,
      system,
      messages: messages || [{ role: "user", content: user }],
    }),
  });
  if (!r.ok) throw new Error(`claude_${r.status}`);
  const data = await r.json();
  return (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join("");
}

function handler(fn) {
  return async (req, res) => {
    res.setHeader("Cache-Control", "no-store");
    if (req.method !== "POST") return res.status(405).json({ error: "method_not_allowed" });
    if (!process.env.ANTHROPIC_API_KEY) return res.status(503).json({ error: "ai_not_configured" });
    try {
      const body = await readJson(req);
      return res.status(200).json(await fn(body));
    } catch (e) {
      const code = e.message === "too_large" ? 413 : e.message === "bad_json" || e.message === "bad_messages" ? 400 : 502;
      return res.status(code).json({ error: String(e.message).slice(0, 80) });
    }
  };
}

const clip = (s, n) => String(s ?? "").slice(0, n);

module.exports = { claude, handler, clip };
