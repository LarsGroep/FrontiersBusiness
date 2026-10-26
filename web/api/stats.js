// GET /api/stats — size and make-up of the evidence database.
const { rpc, send } = require("./_db");

module.exports = async (req, res) => {
  try {
    return send(res, 200, await rpc("evidence_stats", {}));
  } catch (e) {
    return send(res, 502, { error: String(e.message) });
  }
};
