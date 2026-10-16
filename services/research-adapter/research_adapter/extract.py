"""Page extraction (phase 7: retrieval -> structured facts).

Deterministic, dependency-free HTML-to-text + fact extraction using the
stdlib HTMLParser. Output is the raw material for provenance records -
everything extracted is UNTRUSTED data and is only ever handed to the model
wrapped in the adapter's untrusted markers, never as instructions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser

# A fact line looks like "Price: 450000" / "seller: John Motors" in the page's
# visible text. Keys are normalized to snake_case; values are kept verbatim
# (compare.py decides whether two values disagree).
_FACT_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9 _/-]{0,48}?)\s*:\s+(.+)$")

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}


@dataclass
class ExtractedFact:
    key: str
    value: str


@dataclass
class ExtractedPage:
    title: str
    text: str
    facts: list[ExtractedFact] = field(default_factory=list)
    content_sha256: str = ""
    byte_size: int = 0


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._description = ""

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attrs_d = dict(attrs)
            if (attrs_d.get("name") or "").lower() == "description":
                self._description = attrs_d.get("content") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self._chunks)


def _normalize_key(raw: str) -> str:
    return re.sub(r"[\s/-]+", "_", raw.strip().lower()).strip("_")


def extract_facts_from_text(text: str) -> list[ExtractedFact]:
    """Deterministic heuristic: 'key: value' lines become facts, in order."""
    facts: list[ExtractedFact] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if len(line) > 300:
            continue
        match = _FACT_LINE.match(line)
        if not match:
            continue
        key = _normalize_key(match.group(1))
        value = unescape(match.group(2)).strip()
        if not key or not value or key in seen:
            continue
        seen.add(key)
        facts.append(ExtractedFact(key=key, value=value))
    return facts


def extract_html(data: bytes, *, base_title: str = "") -> ExtractedPage:
    """Extract title, visible text, and candidate facts from an HTML page."""
    parser = _VisibleTextParser()
    try:
        parser.feed(data.decode("utf-8", errors="replace"))
        parser.close()
    except Exception:  # malformed HTML must not crash research - extract what we have
        title, text = base_title, ""
        return ExtractedPage(
            title=title,
            text=text,
            facts=[],
            content_sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
        )
    text = parser.text
    facts = extract_facts_from_text(text)
    if parser._description and "description" not in {f.key for f in facts}:
        facts.append(ExtractedFact(key="description", value=parser._description.strip()))
    title = unescape(parser.title.strip()) or base_title
    return ExtractedPage(
        title=title,
        text=text,
        facts=facts,
        content_sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )


def extract_plain_text(data: bytes) -> ExtractedPage:
    """text/plain and JSON bodies: the whole body is the text."""
    text = data.decode("utf-8", errors="replace")
    return ExtractedPage(
        title="",
        text=text,
        facts=extract_facts_from_text(text),
        content_sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
    )


__all__ = [
    "ExtractedFact",
    "ExtractedPage",
    "extract_facts_from_text",
    "extract_html",
    "extract_plain_text",
]
