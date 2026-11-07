// Relay to the Raspberry Pi full-text search API. The Pi's token stays on the server.
//   GET /api/fulltext?health=1               -> Pi /health
//   GET /api/fulltext?q=...&page=&per_page=  -> Pi /search (every matching study, exact total)
//   GET /api/fulltext?q=...&export=csv       -> Pi /export.csv (download of all matches)
//   GET /api/fulltext?paper=PMC123           -> Pi /paper/PMC123
//   GET /api/fulltext?clusters=1             -> Pi /clusters (theme tree, disease areas, symptoms)
//   GET /api/fulltext?cluster_id=12&page=    -> Pi /clusters/12 (studies in a theme)
//   GET /api/fulltext?similar=PMC123         -> Pi /similar/PMC123
//   GET /api/fulltext?browse=1&area=&cluster= -> Pi /papers (studies in an area/theme, no search term)
//   /search and export also pass  cluster=<id>  and  area=<MeSH area>
// Needs PI_API_URL and PI_API_TOKEN in the Vercel project; answers 503 when the Pi is not set up or offline.
const PI = (process.env.PI_API_URL || "").replace(/\/+$/, "");
const TOKEN = process.env.PI_API_TOKEN || "";
const PASS = ["q", "page", "per_page", "include_probable", "min_year", "topics", "population", "open_licence_only", "cluster", "area"];

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  if (!PI) return res.status(503).json({ error: "fulltext_not_configured" });
  const url = new URL(req.url, "http://x");
  const p = url.searchParams;
  let path;
  const ID = /^(PMC|MED)\d+$/;
  if (p.get("health")) path = "/health";
  else if (p.get("clusters")) path = "/clusters";
  else if (p.get("cluster_id")) {
    if (!/^\d{1,5}$/.test(p.get("cluster_id"))) return res.status(400).json({ error: "bad_cluster" });
    const fwd = new URLSearchParams();
    ["page", "per_page"].forEach((k) => p.get(k) && /^\d{1,4}$/.test(p.get(k)) && fwd.set(k, p.get(k)));
    path = `/clusters/${p.get("cluster_id")}?${fwd}`;
  } else if (p.get("browse")) {
    const fwd = new URLSearchParams();
    ["area", "cluster", "page", "per_page", "include_probable"].forEach((k) => p.get(k) && fwd.set(k, p.get(k).slice(0, 120)));
    path = `/papers?${fwd}`;
  } else if (p.get("similar")) {
    if (!ID.test(p.get("similar"))) return res.status(400).json({ error: "bad_id" });
    path = `/similar/${p.get("similar")}`;
  }
  else if (p.get("paper")) {
    if (!ID.test(p.get("paper"))) return res.status(400).json({ error: "bad_id" });
    path = `/paper/${p.get("paper")}`;
  } else {
    if (!p.get("q")) return res.status(400).json({ error: "missing_q" });
    const fwd = new URLSearchParams();
    PASS.forEach((k) => p.get(k) && fwd.set(k, p.get(k).slice(0, 500)));
    path = (p.get("export") === "csv" ? "/export.csv?" : "/search?") + fwd.toString();
  }
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), p.get("export") ? 25000 : 9000);
  try {
    const r = await fetch(PI + path, {
      headers: { "x-api-key": TOKEN, "x-forwarded-for": (req.headers["x-forwarded-for"] || "").split(",")[0] },
      signal: ctl.signal,
    });
    const body = Buffer.from(await r.arrayBuffer());
    res.setHeader("Content-Type", r.headers.get("content-type") || "application/json");
    const cd = r.headers.get("content-disposition");
    if (cd) res.setHeader("Content-Disposition", cd);
    res.setHeader("Cache-Control", r.ok && !p.get("health") ? "public, max-age=120" : "no-store");
    return res.status(r.status).send(body);
  } catch (e) {
    return res.status(503).json({ error: "fulltext_offline", detail: e.name === "AbortError" ? "timeout" : String(e.message).slice(0, 80) });
  } finally {
    clearTimeout(timer);
  }
};
