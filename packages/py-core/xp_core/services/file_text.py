"""Text from files people send to Satish AI (PDF, plain text, CSV, Markdown,
JSON). Read in memory, never stored. Images need OCR/vision, not supported yet."""

from __future__ import annotations

import io

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 8000


def extract_text(data: bytes, filename: str = "", mime: str = "") -> str | None:
    name = (filename or "").lower()
    if len(data) > MAX_BYTES:
        return None
    if name.endswith(".pdf") or mime == "application/pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            parts = []
            for page in reader.pages[:40]:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) > MAX_CHARS:
                    break
            text = "\n".join(parts)
        except Exception:
            return None
    elif name.endswith((".txt", ".csv", ".md", ".json", ".tsv")) or mime.startswith("text/"):
        text = data.decode("utf-8", errors="replace")
    else:
        return None
    text = " ".join(text.split()) if len(text) > MAX_CHARS * 2 else text.strip()
    return text[:MAX_CHARS] or None
