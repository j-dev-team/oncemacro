"""
엔진 글(실패 이유·형식 오류·실행 기록 요약) 번역. 2026-11-17.

쓰는 법: 사람에게 보이는 한국어 글을 t("변수 '{name}'가 없음", name=name) 처럼 쓴다.
- 한국어 글(자리표시 포함) 자체가 열쇠. 영어면 engine/lang/en/*.json 사전에서 찾아 바꾼 뒤 자리표시를 채운다.
- 사전에 없으면 한국어 그대로(자리표시는 채움).
- 언어: set_language() 로 정하거나, 안 정했으면 환경변수 MACRO_LANG(en 이면 영어). 기본 한국어.
  화면(gui/v2/i18n.py)·MCP 서버(--lang en)가 켤 때 같이 맞춘다.
- 실행 기록(logs/runs/*.jsonl)에도 그때 언어로 들어간다(형식·키 이름은 언어와 상관없이 같음).
"""
from __future__ import annotations

import contextvars
import glob
import json
import os
import sys
from typing import Dict, Optional

_lang: Optional[str] = None
_dict: Dict[str, str] = {}
_cache: Dict[str, Dict[str, str]] = {}
# 요청 하나만 다른 언어로(화면 프로그램이 영어 MCP 요청을 대신 처리할 때). 스레드·작업으로 이어짐(contextvars)
_override: contextvars.ContextVar = contextvars.ContextVar("macro_lang", default=None)


def _lang_dir(lang: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    root = os.path.join(base, "engine") if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "lang", lang)


def _norm(lang: str) -> str:
    return "en" if (lang or "").strip().lower().startswith("en") else "ko"


def _load(lang: str) -> Dict[str, str]:
    if lang == "ko":
        return {}
    if lang not in _cache:
        d: Dict[str, str] = {}
        for fp in sorted(glob.glob(os.path.join(_lang_dir(lang), "*.json"))):    # 여러 파일로 나눠도 됨
            try:
                with open(fp, encoding="utf-8") as fh:
                    d.update(json.load(fh))
            except Exception:
                pass
        _cache[lang] = d
    return _cache[lang]


def set_language(lang: str) -> None:
    global _lang, _dict
    _lang = _norm(lang)
    _cache.pop(_lang, None)
    _dict = _load(_lang)


def use_language(lang: Optional[str]):
    """지금 작업(과 거기서 띄운 스레드)만 이 언어로. 돌려준 토큰은 _override.reset 에 쓴다."""
    return _override.set(_norm(lang) if lang else None)


def system_language() -> str:
    """윈도우 표시 언어: 한국어면 ko, 아니면 en (정하지 않았을 때의 기본, 11-24)."""
    try:
        import ctypes
        return "ko" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x12 else "en"
    except Exception:
        return "ko"


def current() -> str:
    o = _override.get()
    if o:
        return o
    if _lang is None:
        set_language(os.environ.get("MACRO_LANG", ""))
    return _lang


def row_item(n) -> dict:
    """표 한 줄 dict 의 머리. 화면 언어와 상관없이 두 열쇠를 다 둔다(같은 매크로가 어느 언어에서든 똑같이 돌게)."""
    return {"행": n, "row": n}


def K(text: str) -> str:
    """번역 열쇠 표시: 나중에 t(변수) 로 번역될 한국어 글(자리표시 포함)을 상수로 둘 때 감싼다. 값은 그대로."""
    return text


def t(text: str, **kw) -> str:
    """번역 + 자리표시 채우기. 자리표시가 안 맞아도 오류를 내지 않는다(글이 깨지는 것보다 나음)."""
    lang = current()
    s = text if lang == "ko" else (_dict if lang == _lang else _load(lang)).get(text, text)
    if not kw:
        return s
    try:
        return s.format(**kw)
    except Exception:
        try:
            return text.format(**kw)
        except Exception:
            return s
