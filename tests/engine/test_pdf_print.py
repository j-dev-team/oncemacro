"""PDF 읽기·인쇄(가짜 오피스). 진짜 워드·엑셀은 design/scenario_runs.py 시나리오 7."""
import os

from engine import new_macro, validate_macro
from engine.office import _clean_pdf_text
from tests.engine.test_runner import World


class FakeOffice:
    def __init__(self):
        self.calls = []

    def run(self, kind, action, p):
        self.calls.append((kind, action, dict(p)))
        if action == "pdf_text":
            return "청구서\n날짜: 2026-11-03\n거래처: 가나상사\n합계 금액: 1,250,000원"
        if action == "pdf_tables":
            return [[["품목", "수량", "금액"], ["볼펜", "4", "4800"], ["", "", ""], ["토너", "1", "89000"]]]
        return None

    def shutdown(self):
        pass


def run(steps):
    w = World()
    r = w.runner(new_macro("m", steps))
    office = FakeOffice()
    r.office = office
    r.base_dir = "C:\\자료"
    res = r.run()
    return res, w, office


def test_pdf_text_extract_table():
    res, w, office = run([
        {"type": "pdf", "via": "word", "action": "extract", "path": "청구서.pdf", "pattern": r"합계 금액:\s*([\d,]+)", "var": "금액글"},
        {"type": "text", "var": "금액", "text": "{금액글}", "action": "number"},
        {"type": "pdf", "via": "word", "action": "extract", "path": "청구서.pdf", "pattern": r"날짜:\s*(\S+)", "var": "날짜"},
        {"type": "pdf", "via": "word", "action": "table", "path": "청구서.pdf", "var": "표"},
        {"type": "each", "var": "줄", "list": "표", "steps": [{"type": "type_text", "text": "{줄.품목}={줄.금액}"}]},
        {"type": "type_text", "text": "{날짜} {금액}"},
    ])
    assert res.status == "ok", res.error
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["볼펜=4800", "토너=89000", "2026-11-03 1250000"]
    assert office.calls[0][2]["path"] == "C:\\자료\\청구서.pdf"


def test_pdf_no_match_fails_and_print_validates():
    res, _, _ = run([{"type": "pdf", "via": "word", "action": "extract", "path": "a.pdf", "pattern": r"없는글자(\d+)", "var": "x"}])
    assert res.status == "failed"
    ok = new_macro("m", [{"type": "excel", "action": "print", "to_file": "a.pdf"},
                         {"type": "word", "action": "print", "printer": "Microsoft Print to PDF", "to_file": "b.pdf"},
                         {"type": "hwp", "action": "print"}, {"type": "pdf", "path": "a.pdf", "var": "t"}])
    assert validate_macro(ok) == []
    assert len(validate_macro(new_macro("m", [{"type": "pdf", "path": "a.pdf"},
                                              {"type": "pdf", "action": "extract", "path": "a", "var": "x"}]))) == 2


def test_print_passes_printer_and_file():
    res, _, office = run([{"type": "set", "var": "달", "value": "11월"},
                          {"type": "word", "action": "print", "to_file": "출력/{달}.pdf", "copies": 2}])
    assert res.status == "ok"
    assert office.calls[-1] == ("word", "print", {"to_file": os.path.join("C:\\자료", "출력/11월.pdf"), "copies": 2})


def test_clean_pdf_text():
    raw = "\r날짜 품목\r\x07수량\r\x07\r\x072026-10-01볼펜\r\x074\r\x07\r\x07\r"
    assert _clean_pdf_text(raw) == "날짜 품목\t수량\n2026-10-01볼펜\t4"
