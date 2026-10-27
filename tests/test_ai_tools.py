import pytest

from app.services.safe_math import evaluate


def test_safe_math():
    assert evaluate("2,500 * 4 + 10%3") == 10001
    assert evaluate("round(80000 / 160000000 * 1e8)") == 50000
    assert evaluate("sum([1, 2, 3]) - max(1, 2)") == 4
    for bad in ["__import__('os')", "open('x')", "2**10000", "1/0", "a+1", ""]:
        with pytest.raises(ValueError):
            evaluate(bad)


def test_file_text_reads_text_and_pdf():
    from xp_core.services.file_text import extract_text

    assert extract_text(b"rice,price\nlocal,80000", "prices.csv") .startswith("rice,price")
    assert extract_text(b"\x89PNG....", "photo.png") is None
    from pypdf import PdfWriter
    import io

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    assert extract_text(buf.getvalue(), "blank.pdf") is None  # no text, honestly nothing
