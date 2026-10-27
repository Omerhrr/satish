<template>
  <div ref="root" class="rich">
    <template v-for="(part, i) in parts" :key="i">
      <div v-if="part.kind === 'md'" class="md" v-html="part.html" />
      <div v-else class="chart-wrap">
        <div :ref="(el) => setChart(el as HTMLElement | null, i)" class="chart" role="img" :aria-label="part.title || 'Chart'" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * Satish AI answers: Markdown (tables, lists, bold, links) and ECharts charts
 * from ```chart blocks. Raw HTML in the text is never rendered; links open
 * in a new tab. ECharts loads only when an answer has a chart.
 */
import MarkdownIt from "markdown-it";

const props = defineProps<{ text: string }>();
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
const defaultLink = md.renderer.rules.link_open || ((t, i, o, _e, s) => s.renderToken(t, i, o));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx]!.attrSet("target", "_blank");
  tokens[idx]!.attrSet("rel", "noopener noreferrer");
  return defaultLink(tokens, idx, options, env, self);
};

type Part = { kind: "md"; html: string } | { kind: "chart"; option: Record<string, unknown>; title: string };

const parts = computed<Part[]>(() => {
  const out: Part[] = [];
  const re = /```(?:chart|echarts)[ \t]*\n([\s\S]*?)\n```/gi;
  let last = 0;
  let m: RegExpExecArray | null;
  const text = props.text || "";
  while ((m = re.exec(text))) {
    if (m.index > last) out.push({ kind: "md", html: md.render(text.slice(last, m.index)) });
    try {
      const option = JSON.parse(m[1]!);
      const t = option?.title;
      out.push({ kind: "chart", option, title: (t && typeof t === "object" && "text" in t ? String(t.text) : "") || "" });
    } catch {
      /* unreadable chart: skip it */
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: "md", html: md.render(text.slice(last)) });
  return out;
});

const PALETTE = ["#f7931a", "#3b82f6", "#22c55e", "#ef4444", "#a855f7", "#06b6d4", "#eab308", "#ec4899", "#64748b", "#84cc16"];
const charts = new Map<number, { dispose: () => void; resize: () => void }>();

async function setChart(el: HTMLElement | null, i: number) {
  if (!el || charts.has(i)) return;
  const part = parts.value[i];
  if (!part || part.kind !== "chart") return;
  charts.set(i, { dispose() {}, resize() {} });
  const echarts = await import("echarts");
  const dark = matchMedia?.("(prefers-color-scheme: dark)").matches;
  const chart = echarts.init(el, dark ? "dark" : undefined, { renderer: "svg" });
  chart.setOption({
    color: PALETTE,
    backgroundColor: "transparent",
    tooltip: { trigger: "item" },
    grid: { containLabel: true, left: 8, right: 16, top: 48, bottom: 8 },
    ...part.option,
  });
  charts.set(i, chart);
}

function onResize() {
  for (const c of charts.values()) c.resize();
}
onMounted(() => window.addEventListener("resize", onResize));
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
  for (const c of charts.values()) c.dispose();
});
watch(
  () => props.text,
  () => {
    for (const c of charts.values()) c.dispose();
    charts.clear();
  },
);
</script>

<style scoped>
.rich { line-height: 1.6; font-size: 15px; }
.md :deep(h1), .md :deep(h2), .md :deep(h3) { font-size: 16px; margin: 14px 0 6px; }
.md :deep(p) { margin: 0 0 8px; }
.md :deep(ul), .md :deep(ol) { padding-left: 20px; margin: 4px 0 8px; }
.md :deep(table) { width: 100%; border-collapse: collapse; margin: 8px 0 12px; font-size: 13px; display: block; overflow-x: auto; }
.md :deep(th) { text-align: left; padding: 6px 8px; background: var(--bg-elev, #1a1f27); border-bottom: 2px solid var(--orange, #f7931a); white-space: nowrap; }
.md :deep(td) { padding: 6px 8px; border-bottom: 1px solid var(--border, #2a3240); }
.md :deep(code) { background: var(--bg-elev, #1a1f27); padding: 1px 4px; border-radius: 4px; font-size: 13px; }
.md :deep(pre) { background: var(--bg-elev, #1a1f27); padding: 10px; border-radius: 8px; overflow-x: auto; }
.md :deep(blockquote) { border-left: 3px solid var(--orange, #f7931a); margin: 8px 0; padding: 2px 10px; color: var(--text-dim); }
.md :deep(a) { color: var(--orange, #f7931a); }
.chart-wrap { margin: 10px 0 14px; }
.chart { width: 100%; height: 300px; }
</style>
