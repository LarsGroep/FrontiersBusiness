// Read-only access to the evidence database (public publishable key; row-level security allows reads only).
const SUPABASE_URL = process.env.SUPABASE_URL || "https://jvlrbsusjvuxsgijgxpb.supabase.co";
const SUPABASE_KEY = process.env.SUPABASE_PUBLISHABLE_KEY || "sb_publishable_aA-czPmRvwj2QODVXOUS3A_-AHkUK7F";

async function rpc(fn, body) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: { apikey: SUPABASE_KEY, "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`db_${r.status}`);
  return r.json();
}

async function select(table, query) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${query}`, { headers: { apikey: SUPABASE_KEY } });
  if (!r.ok) throw new Error(`db_${r.status}`);
  return r.json();
}

// Small helpers shared by the agent endpoints.
function params(req) {
  const q = Object.fromEntries(new URL(req.url, "http://x").searchParams);
  const b = req.body && typeof req.body === "object" ? req.body : {};
  return { ...q, ...b };
}
const list = (v) => (v == null || v === "" ? null : Array.isArray(v) ? v : String(v).split(",").map((s) => s.trim()).filter(Boolean));
const int = (v, d, lo, hi) => Math.min(hi, Math.max(lo, Number.parseInt(v, 10) || d));

function send(res, code, data) {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", code === 200 ? "public, max-age=60" : "no-store");
  res.status(code).send(JSON.stringify(data));
}

module.exports = { rpc, select, params, list, int, send };
