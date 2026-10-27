"""Markdown tables and ECharts charts in PDFs, Telegram and the app."""

from xp_core.services.documents import ReportSpec, render_report_html
from xp_core.services.rich_text import markdown_to_telegram, render_charts, rich_html, split_charts

MD = """## Rice prices
| City | Price (₦) |
|---|---:|
| Kaduna | 78,000 |
| Kano | 80,500 |

Cheapest is **Kaduna**. <img src=x onerror=alert(1)>

```chart
{"title": {"text": "Rice"}, "xAxis": {"type": "category", "data": ["Kaduna", "Kano"]},
 "yAxis": {"type": "value"}, "series": [{"type": "bar", "data": [78000, 80500]}]}
```
"""


def test_pdf_html_has_table_chart_and_no_raw_html():
    h = rich_html(MD)
    assert "<table>" in h and "<th" in h and "<svg" in h
    assert "<img" not in h and "onerror" not in h.replace("&lt;img src=x onerror=alert(1)&gt;", "")


def test_report_includes_rich_body():
    from datetime import UTC, datetime

    spec = ReportSpec(title="t", goal="g", generated_at=datetime.now(UTC), body=[MD], limitations=["none"])
    out = render_report_html(spec)
    assert "<table>" in out and "<svg" in out


def test_bad_chart_json_is_dropped_not_shown():
    body, opts = split_charts("a\n```chart\n{not json}\n```\nb")
    assert opts == [] and "{not json}" not in body


def test_telegram_html_and_png():
    body, opts = split_charts(MD)
    tg = markdown_to_telegram(body)
    assert "<b>Rice prices</b>" in tg and "<pre>" in tg and "&lt;img" in tg
    charts = render_charts(opts, png=True)
    assert charts[0].png and charts[0].png[:4] == b"\x89PNG"
