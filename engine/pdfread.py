"""PDF 글자·표 읽기(Qt 없음). 기본은 프로그램에 든 pdfplumber(MIT, 워드 없이 됨), 없거나 via="word" 면 워드로.

- 글자가 하나도 없는 PDF(그림으로 스캔한 것)는 '글자 없음' 오류로 분명히 알린다.
"""
from __future__ import annotations

import os
from typing import Any, List

from .i18n import t


class PdfError(Exception):
    pass


def _open(path: str):
    if not os.path.exists(path):
        raise PdfError(t("파일이 없음: {path}", path=path))
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        return pdfplumber.open(path)
    except Exception as e:
        raise PdfError(t("PDF 를 열 수 없음(암호가 걸렸거나 깨진 파일): {error}", error=e))


def available() -> bool:
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


def read_text(path: str, pages: Any = None) -> str:
    pdf = _open(path)
    if pdf is None:
        raise PdfError(t("PDF 읽기 부품이 없음"))
    with pdf:
        out = []
        for i, pg in enumerate(pdf.pages, 1):
            if pages and i not in pages:
                continue
            out.append(pg.extract_text() or "")
    text = "\n".join(out).strip()
    if not text:
        raise PdfError(t("PDF 에 글자가 없음(그림으로 스캔한 PDF 일 수 있음): {path}", path=path))
    return text


def read_tables(path: str) -> List[List[List[str]]]:
    pdf = _open(path)
    if pdf is None:
        raise PdfError(t("PDF 읽기 부품이 없음"))
    tables = []
    has_text = False
    with pdf:
        for pg in pdf.pages:
            if (pg.extract_text() or "").strip():
                has_text = True
            for tb in pg.extract_tables() or []:
                tables.append([[("" if c is None else str(c).replace("\n", " ").strip()) for c in row] for row in tb])
    if not has_text:
        raise PdfError(t("PDF 에 글자가 없음(그림으로 스캔한 PDF 일 수 있음): {path}", path=path))
    return tables


def page_count(path: str) -> int:
    pdf = _open(path)
    if pdf is None:
        raise PdfError(t("PDF 읽기 부품이 없음"))
    with pdf:
        return len(pdf.pages)
