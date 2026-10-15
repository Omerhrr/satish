"""Document generation with quality gates (phase 7 deliverables #5-#8).

Pure rendering + validation — no DB, no network. The report builder in the
API layer assembles a ReportSpec from provenance; THIS module enforces the
report quality checks and refuses to render a spec that violates them:

- every claim must cite at least one source ([S{n}])
- every citation must resolve to a listed source
- source indices must be complete and non-duplicated

Generated files are validated by magic bytes/structure before they are
stored, and stored PRIVATELY (delivery only via the authorized artifact
route). PDF rendering imports WeasyPrint lazily; XLSX imports openpyxl
lazily, so importing this module stays cheap.
"""

from __future__ import annotations

import csv
import html
import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

DocumentKind = Literal["pdf", "csv", "xlsx"]


# -- report spec -------------------------------------------------------------------


@dataclass
class ReportClaim:
    text: str
    citations: list[int]  # 1-based source indices
    kind: str = "observed"  # observed | estimate | assumption


@dataclass
class ReportSource:
    index: int  # 1-based
    url: str
    title: str
    status: str
    retrieved_at: datetime | None = None
    fact_count: int = 0
    retrieval_mode: str = "canned"


@dataclass
class ReportSpec:
    title: str
    goal: str
    generated_at: datetime
    claims: list[ReportClaim] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    sources: list[ReportSource] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    task_id: str = ""
    mode_notes: list[str] = field(default_factory=list)


# -- quality checks -----------------------------------------------------------------


def check_report_spec(spec: ReportSpec) -> list[str]:
    """Report quality checks (phase 7 deliverable #8) — backend-enforced.

    Returns a list of violations; an empty list means the spec may render.
    These gates are deterministic and re-runnable, so a report that passed
    them is reproducible.
    """
    violations: list[str] = []
    indices = [s.index for s in spec.sources]
    known = set(indices)
    if len(known) != len(indices):
        violations.append("duplicate source index in the source list")
    for claim in spec.claims:
        if not claim.citations:
            violations.append(f"claim is not cited by any source: {claim.text[:80]!r}")
        for citation in claim.citations:
            if citation not in known:
                violations.append(
                    f"claim cites unknown source S{citation}: {claim.text[:80]!r}"
                )
    if not spec.sources and spec.claims:
        violations.append("claims exist but the source list is empty")
    return violations


# -- renderers ---------------------------------------------------------------------


def render_report_html(spec: ReportSpec) -> str:
    """Build the cited report's HTML (exposed for tests/preview)."""
    violations = check_report_spec(spec)
    if violations:
        raise DocumentQualityError("report spec failed quality checks", violations)

    def esc(value: str) -> str:
        return html.escape(str(value), quote=True)

    claims_html = "".join(
        f"<li class='claim kind-{esc(c.kind)}'>"
        f"<span class='kind'>{esc(c.kind)}</span> {esc(c.text)}</li>"
        for c in spec.claims
    ) or "<li class='claim muted'>No factual claims were collected — see limitations.</li>"

    conflicts_html = (
        "".join(
            f"<li><b>{esc(c.get('subject', ''))}</b> — {esc(c.get('detail', ''))}</li>"
            for c in spec.conflicts
        )
        or "<li>None detected among fetched sources.</li>"
    )
    gaps_html = (
        "".join(f"<li>{esc(g)}</li>" for g in spec.gaps)
        or "<li>None — all required keys were covered.</li>"
    )
    sources_html = "".join(
        f"<li class='src'><span class='sid'>S{s.index}</span> "
        f"{esc(s.title or '(untitled)')} — <span class='url'>{esc(s.url)}</span><br>"
        f"<span class='srcmeta'>status {esc(s.status)} · retrieved "
        f"{esc(s.retrieved_at.strftime('%Y-%m-%d %H:%M UTC') if s.retrieved_at else 'n/a')} · "
        f"{s.fact_count} facts · mode {esc(s.retrieval_mode)}</span></li>"
        for s in spec.sources
    ) or "<li>No sources were fetched.</li>"
    unavailable_html = "".join(f"<li>{esc(u)}</li>" for u in spec.unavailable) or "<li>None.</li>"
    limitations_html = "".join(f"<li>{esc(item)}</li>" for item in spec.limitations)
    modes_html = "".join(f"<li>{esc(m)}</li>" for m in spec.mode_notes)

    doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  @page {{ size: A4; margin: 2cm 2.2cm;
    @bottom-center {{ content: "XP research report — task {esc(spec.task_id)[:8]} — page " counter(page) " of " counter(pages); font-size: 9px; color: #8a8f98; }} }}
  body {{ font-family: "DejaVu Sans", sans-serif; color: #14181f; line-height: 1.5; font-size: 11px; }}
  .brand {{ color: #f7931a; font-weight: 700; letter-spacing: 2px; font-size: 12px; }}
  h1 {{ font-size: 21px; margin: 6px 0 2px; }}
  .meta {{ color: #6b7280; font-size: 10px; margin-bottom: 18px; }}
  h2 {{ font-size: 14px; border-bottom: 2px solid #f7931a; padding-bottom: 3px; margin-top: 20px; }}
  ul {{ padding-left: 18px; }}
  li {{ margin-bottom: 5px; }}
  .kind {{ display: inline-block; font-size: 9px; padding: 0 5px; border-radius: 3px;
           background: #eef2f7; color: #475569; margin-right: 4px; text-transform: uppercase; }}
  .kind-estimate {{ background: #fef3c7; color: #92400e; }}
  .sid {{ background: #14181f; color: #fff; font-size: 9px; padding: 1px 5px; border-radius: 3px; margin-right: 4px; }}
  .url {{ color: #2563eb; word-break: break-all; font-size: 10px; }}
  .srcmeta {{ color: #6b7280; font-size: 9.5px; }}
  .muted {{ color: #6b7280; }}
  .limit {{ margin-top: 22px; padding: 10px 12px; background: #f6f7f9;
            border-left: 3px solid #f7931a; }}
  .limit ul {{ margin: 6px 0 0; }}
</style></head><body>
  <div class="brand">XP · RESEARCH REPORT</div>
  <h1>{esc(spec.title)}</h1>
  <div class="meta">Goal: {esc(spec.goal)}<br>Generated {esc(spec.generated_at.strftime('%Y-%m-%d %H:%M UTC'))} · task {esc(spec.task_id)}</div>

  <h2>Findings (cited claims)</h2>
  <ul>{claims_html}</ul>

  <h2>Conflicts between sources</h2>
  <ul>{conflicts_html}</ul>

  <h2>Coverage gaps</h2>
  <ul>{gaps_html}</ul>

  <h2>Source appendix</h2>
  <ul>{sources_html}</ul>

  <h2>Unavailable sources</h2>
  <ul>{unavailable_html}</ul>

  <h2>Method notes</h2>
  <ul>{modes_html}</ul>

  <div class="limit"><b>Limitations</b>
    <ul>{limitations_html}</ul>
  </div>
</body></html>"""

    return doc


def render_report_pdf(spec: ReportSpec) -> bytes:
    """Render the cited research report to PDF via WeasyPrint.

    Refuses (DocumentQualityError) when the spec violates quality checks —
    an uncited report never leaves the building.
    """
    from weasyprint import HTML  # lazy: keeps xp_core imports light

    pdf_bytes = HTML(string=render_report_html(spec)).write_pdf()
    if not isinstance(pdf_bytes, bytes):  # pragma: no cover - WeasyPrint returns bytes
        raise DocumentQualityError("weasyprint returned a non-bytes result", [])
    return pdf_bytes


def build_csv(headers: list[str], rows: list[list[Any]]) -> bytes:
    """UTF-8 (BOM) CSV so Excel opens it honestly without mangling."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if v is None else str(v) for v in row])
    return buffer.getvalue().encode("utf-8-sig")


def build_xlsx(sheet_title: str, headers: list[str], rows: list[list[Any]]) -> bytes:
    """Single-sheet XLSX workbook via openpyxl (lazy import)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31] or "comparison"
    ws.append(headers)
    for row in rows:
        ws.append(["" if v is None else v for v in row])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# -- validation --------------------------------------------------------------------


def validate_document(kind: DocumentKind, data: bytes) -> tuple[bool, str]:
    """Structural validation before storage (deliverable #7: files are
    validated before delivery). Returns (ok, detail)."""
    if not data:
        return False, "file is empty"
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            return False, "missing %PDF- magic header"
        if b"%%EOF" not in data[-2048:]:
            return False, "missing %%EOF trailer"
        if len(data) < 500:
            return False, "PDF implausibly small"
        return True, f"pdf ok ({len(data)} bytes)"
    if kind == "csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False, "csv is not valid UTF-8"
        rows = list(csv.reader(io.StringIO(text)))
        if len(rows) < 1 or not rows[0]:
            return False, "csv has no header row"
        width = len(rows[0])
        if any(len(r) != width for r in rows):
            return False, "csv rows have inconsistent width"
        return True, f"csv ok ({len(rows) - 1} data rows)"
    if kind == "xlsx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            return False, "xlsx is not a zip container"
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "xl/workbook.xml" not in zf.namelist():
                    return False, "xlsx missing xl/workbook.xml"
        except zipfile.BadZipFile:
            return False, "xlsx zip container is corrupt"
        return True, f"xlsx ok ({len(data)} bytes)"
    return False, f"unknown document kind {kind!r}"


class DocumentQualityError(Exception):
    """Raised when a report spec fails the quality gates."""

    def __init__(self, message: str, violations: list[str]) -> None:
        super().__init__(f"{message}: {'; '.join(violations)}")
        self.violations = violations


__all__ = [
    "DocumentKind",
    "DocumentQualityError",
    "ReportClaim",
    "ReportSource",
    "ReportSpec",
    "build_csv",
    "build_xlsx",
    "check_report_spec",
    "render_report_pdf",
    "validate_document",
]
