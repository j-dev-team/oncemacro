"""프로그램에 든 PDF 부품(pdfplumber)으로 글자·표 읽기, 글자 없는 PDF 알림. 워드 없이 돈다."""
import pytest

from engine import new_macro
from engine import pdfread
from tests.engine.test_runner import World

pytestmark = pytest.mark.skipif(not pdfread.available(), reason="PDF 부품 없음")


def make_pdf(path, lines):
    """글자가 든 아주 작은 PDF(기본 글꼴, 영어·숫자). lines=[] 이면 글자 없는 빈 쪽."""
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({ln}) '" for ln in lines) + " ET" if lines else ""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offs:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as fh:
        fh.write(out)


def test_builtin_reads_text_and_extracts(tmp_path):
    p = tmp_path / "invoice.pdf"
    make_pdf(str(p), ["INVOICE INV-1103", "Date: 2026-11-03", "Total: 1,250,000 KRW"])
    assert "Total: 1,250,000" in pdfread.read_text(str(p))
    w = World()
    r = w.runner(new_macro("m", [
        {"type": "pdf", "action": "extract", "path": "invoice.pdf", "pattern": r"Total:\s*([\d,]+)", "var": "t"},
        {"type": "text", "var": "n", "text": "{t}", "action": "number"},
        {"type": "type_text", "text": "{n}"}]))
    r.base_dir = str(tmp_path)
    r.office = None                       # 워드를 안 씀
    res = r.run()
    assert res.status == "ok", res.error
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["1250000"]


def test_scanned_pdf_says_no_text(tmp_path):
    p = tmp_path / "scan.pdf"
    make_pdf(str(p), [])
    with pytest.raises(pdfread.PdfError) as ei:
        pdfread.read_text(str(p))
    assert "글자가 없음" in str(ei.value)
    w = World()
    r = w.runner(new_macro("m", [{"type": "pdf", "path": "scan.pdf", "var": "t"}]))
    r.base_dir = str(tmp_path)
    res = r.run()
    assert res.status == "failed" and "글자가 없음" in res.error["reason"]


def test_missing_file(tmp_path):
    with pytest.raises(pdfread.PdfError):
        pdfread.read_text(str(tmp_path / "없음.pdf"))
