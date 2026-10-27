// Render ECharts options to SVG and PNG without a browser.
// stdin: {"charts": [{"option": {...}, "width": 720, "height": 400}], "png": true}
// stdout: {"charts": [{"svg": "<svg…>", "png": "<base64>" | null, "error": null}]}
// Options are plain JSON from Satish AI: no functions, so nothing executes.
import * as echarts from "echarts";
import { Resvg } from "@resvg/resvg-js";

const PALETTE = ["#f7931a", "#2563eb", "#16a34a", "#dc2626", "#9333ea", "#0891b2", "#ca8a04", "#db2777", "#475569", "#65a30d"];

function sanitize(v, depth = 0) {
  if (depth > 12) return null;
  if (Array.isArray(v)) return v.slice(0, 2000).map((x) => sanitize(x, depth + 1));
  if (v && typeof v === "object") {
    const out = {};
    for (const [k, x] of Object.entries(v)) {
      if (/^(on|formatter$|renderItem$)/i.test(k) && typeof x !== "string") continue;
      out[k] = sanitize(x, depth + 1);
    }
    return out;
  }
  if (typeof v === "string") return v.slice(0, 500);
  return v;
}

function renderOne({ option, width = 720, height = 400 }) {
  const w = Math.min(Math.max(Number(width) || 720, 200), 1600);
  const h = Math.min(Math.max(Number(height) || 400, 150), 1200);
  const chart = echarts.init(null, null, { renderer: "svg", ssr: true, width: w, height: h });
  try {
    const opt = sanitize(option);
    chart.setOption({
      color: PALETTE,
      backgroundColor: "#ffffff",
      animation: false,
      textStyle: { fontFamily: "DejaVu Sans, Arial, sans-serif" },
      grid: { containLabel: true, left: 12, right: 24, top: 56, bottom: 16 },
      ...opt,
    });
    return chart.renderToSVGString();
  } finally {
    chart.dispose();
  }
}

let input = "";
for await (const chunk of process.stdin) input += chunk;
const req = JSON.parse(input || "{}");
const out = [];
for (const c of (req.charts || []).slice(0, 12)) {
  try {
    const svg = renderOne(c);
    let png = null;
    if (req.png) {
      const img = new Resvg(svg, { fitTo: { mode: "width", value: Math.min((c.width || 720) * 2, 2000) }, font: { loadSystemFonts: true } }).render();
      png = Buffer.from(img.asPng()).toString("base64");
    }
    out.push({ svg, png, error: null });
  } catch (e) {
    out.push({ svg: null, png: null, error: String(e && e.message ? e.message : e).slice(0, 200) });
  }
}
process.stdout.write(JSON.stringify({ charts: out }));
