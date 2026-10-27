"""Rich answers from Satish AI: Markdown (headings, lists, tables, bold,
links, code) plus charts.

A chart is a fenced block whose language is ``chart`` (or ``echarts``)
holding an ECharts option as JSON::

    ```chart
    {"title": {"text": "Rice prices"}, "xAxis": {"type": "category", "data": ["Kaduna", "Kano"]},
     "yAxis": {"type": "value"}, "series": [{"type": "bar", "data": [78000, 80500]}]}
    ```

- PDFs: Markdown -> HTML (raw HTML in the text is never passed through),
  charts -> SVG drawn by ECharts on the server (services/chart-renderer).
- Telegram: Markdown -> Telegram's small HTML subset, tables as aligned
  monospace blocks, charts -> PNG photos.
- The app renders the same Markdown and charts itself.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt

from xp_core.logging import get_logger

log = get_logger(__name__)

CHART_RE = re.compile(r"```(?:chart|echarts)[ \t]*\n(.*?)\n```", re.S | re.I)
MAX_CHARTS = 8


@dataclass
class Chart:
    option: dict
    svg: str | None = None
    png: bytes | None = None
    error: str | None = None


def split_charts(text: str) -> tuple[str, list[dict]]:
    """Replace chart blocks with markers [[CHART:n]] and return their options."""
    options: list[dict] = []

    def take(m: re.Match) -> str:
        if len(options) >= MAX_CHARTS:
            return ""
        try:
            opt = json.loads(m.group(1))
        except ValueError:
            return ""  # unreadable chart: drop it rather than show raw JSON
        if not isinstance(opt, dict):
            return ""
        options.append(opt)
        return f"\n\n[[CHART:{len(options) - 1}]]\n\n"

    return CHART_RE.sub(take, text or ""), options


def _renderer_dir() -> Path | None:
    env = os.environ.get("XP_CHART_RENDERER_DIR")
    candidates = [Path(env)] if env else []
    here = Path(__file__).resolve()
    candidates += [p / "services" / "chart-renderer" for p in here.parents]
    candidates.append(Path("/app/services/chart-renderer"))
    for c in candidates:
        if (c / "render.mjs").is_file() and (c / "node_modules" / "echarts").is_dir():
            return c
    return None


def render_charts(options: list[dict], *, png: bool = False, width: int = 720, height: int = 400) -> list[Chart]:
    charts = [Chart(option=o) for o in options]
    if not charts:
        return charts
    where = _renderer_dir()
    if where is None:
        for c in charts:
            c.error = "chart renderer not installed"
        return charts
    req = {"png": png, "charts": [{"option": c.option, "width": width, "height": height} for c in charts]}
    try:
        out = subprocess.run(
            ["node", str(where / "render.mjs")],
            input=json.dumps(req).encode(),
            capture_output=True,
            timeout=40,
            cwd=where,
        )
        data = json.loads(out.stdout or b"{}").get("charts") or []
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        log.warning("chart_render_failed", error=type(exc).__name__)
        data = []
    for c, d in zip(charts, data, strict=False):
        c.svg = d.get("svg")
        c.png = base64.b64decode(d["png"]) if d.get("png") else None
        c.error = d.get("error")
    return charts


_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "breaks": True}).enable(["table", "strikethrough"])


def markdown_to_html(text: str, charts: list[Chart] | None = None) -> str:
    """Markdown -> safe HTML for PDFs; [[CHART:n]] markers become SVG figures."""
    out = _md.render(text or "")
    if charts is not None:

        def put(m: re.Match) -> str:
            i = int(m.group(1))
            c = charts[i] if i < len(charts) else None
            if c and c.svg:
                return f'<figure class="chart">{c.svg}</figure>'
            return '<p class="muted">(chart could not be drawn)</p>'

        out = re.sub(r"<p>\[\[CHART:(\d+)\]\]</p>", put, out)
    return out


def rich_html(text: str) -> str:
    """Markdown with charts -> HTML for a PDF."""
    body, options = split_charts(text)
    return markdown_to_html(body, render_charts(options))


# --- Telegram -------------------------------------------------------------

def _table_to_pre(lines: list[str]) -> str:
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    widths = [min(max(len(r[i]) for r in rows), 24) for i in range(n)]
    out = []
    for k, r in enumerate(rows):
        out.append("  ".join(r[i][:24].ljust(widths[i]) for i in range(n)).rstrip())
        if k == 0:
            out.append("  ".join("-" * widths[i] for i in range(n)))
    return "<pre>" + html.escape("\n".join(out)) + "</pre>"


def _inline_tg(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
    return s


def markdown_to_telegram(text: str) -> str:
    """Markdown -> Telegram HTML (b, i, s, code, pre, a, blockquote)."""
    lines = (text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                block.append(lines[j])
                j += 1
            out.append("<pre>" + html.escape("\n".join(block)) + "</pre>")
            i = j + 1
            continue
        if ln.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            j = i
            table = []
            while j < len(lines) and lines[j].strip().startswith("|"):
                table.append(lines[j])
                j += 1
            out.append(_table_to_pre(table))
            i = j
            continue
        m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", ln)
        if m:
            out.append(f"<b>{_inline_tg(m.group(2))}</b>")
        elif re.match(r"^\s*[-*+]\s+", ln):
            out.append("• " + _inline_tg(re.sub(r"^\s*[-*+]\s+", "", ln)))
        elif ln.startswith(">"):
            out.append(f"<blockquote>{_inline_tg(ln.lstrip('> '))}</blockquote>")
        elif re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", ln):
            out.append("")
        else:
            out.append(_inline_tg(ln))
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
