"""
화면 글 번역(한국어 ↔ 영어). 2026-11-17.

쓰는 법: 화면에 보이는 한국어 글을 tr("...") 로 감싼다. 한국어 글 자체가 열쇠다.
- 지금 언어가 한국어면 그대로, 영어면 gui/v2/lang/en/*.json 사전에서 찾아 바꾼다(없으면 한국어 그대로).
- 변수가 들어가는 글은 tr("매크로 {n}개").format(n=3) 처럼 자리표시를 쓴다(사전에도 같은 자리표시).
- 언어는 설정(QSettings MacroManager/v2 'lang')에 저장. 처음에는 윈도 표시 언어(한국어면 ko, 아니면 en).
  바꾼 뒤에는 프로그램을 다시 켜야 화면 전체에 적용된다.
- 사전 파일은 여러 개로 나눠도 됨(lang/en/main.json, lang/en/editor.json …) — 전부 합쳐 읽는다.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from typing import Dict, Optional

LANGS = {"ko": "한국어", "en": "English"}
_lang: Optional[str] = None
_dict: Dict[str, str] = {}


def _lang_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "gui", "v2", "lang")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")


def _lang_dirs():
    """사전 폴더들: 지금 화면(v2) + 새 화면(v3, 있으면). 새 화면에서 새로 생긴 글만 v3 쪽에 둔다."""
    d2 = _lang_dir()
    return [d2, os.path.join(os.path.dirname(os.path.dirname(d2)), "v3", "lang")]


def _qt_core():
    """지금 프로세스가 쓰는 Qt 묶음(새 화면은 PySide6, 지금 화면은 PyQt5). 둘을 한 프로세스에 같이 불러오지 않는다."""
    if "PySide6" in sys.modules:
        from PySide6 import QtCore
    else:
        from PyQt5 import QtCore
    return QtCore


def _system_lang() -> str:
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "ko" if (lid & 0x3FF) == 0x12 else "en"
    except Exception:
        return "ko"


def _settings():
    from .settings_path import open_settings
    return open_settings(_qt_core(), "v2")


def current() -> str:
    global _lang
    if _lang is None:
        lang = os.environ.get("MACRO_LANG")
        if not lang:
            try:
                lang = _settings().value("lang", "", type=str)
            except Exception:
                lang = ""
        set_language(lang if lang in LANGS else _system_lang())
    return _lang


def set_language(lang: str, save: bool = False) -> None:
    """이번 실행의 언어를 정한다. save=True 면 설정에도 저장(다음에 켤 때 적용)."""
    global _lang, _dict
    _lang = lang if lang in LANGS else "ko"
    _dict = {}
    if _lang != "ko":
        for fp in [f for d in _lang_dirs() for f in sorted(glob.glob(os.path.join(d, _lang, "*.json")))]:
            try:
                with open(fp, encoding="utf-8") as fh:
                    _dict.update(json.load(fh))
            except Exception:
                pass
    try:                                            # 엔진 글(실패 이유 등)도 같은 언어로
        from engine import i18n as _engine_i18n
        _engine_i18n.set_language(_lang)
    except Exception:
        pass
    if save and not os.environ.get("MACRO_LANG"):     # 환경 값으로 언어를 정한 실행(시험·캡처)은 사용자 설정을 안 바꿈
        try:
            _settings().setValue("lang", _lang)
        except Exception:
            pass


def tr(text: str) -> str:
    if current() == "ko" or not isinstance(text, str):
        return text
    return _dict.get(text, text)


def tr_dict(d: Dict[str, str]) -> Dict[str, str]:
    """값이 화면 글인 사전(스텝 이름 등)을 통째로 번역한 새 사전."""
    return {k: tr(v) for k, v in d.items()}


_qt_translators = []


def install_qt_translator(app) -> bool:
    """Qt 기본 버튼·대화상자 글(OK·Cancel·Close·Yes·No 등)을 지금 언어로. 한국어면 Qt 의 한국어 사전을 붙인다."""
    if current() != "ko":
        return False
    try:
        qc = _qt_core()
        QLibraryInfo, QTranslator = qc.QLibraryInfo, qc.QTranslator
        if hasattr(QLibraryInfo, "location"):
            dirs = [QLibraryInfo.location(QLibraryInfo.TranslationsPath)]
        else:                                        # Qt6
            dirs = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
        base = getattr(sys, "_MEIPASS", None)
        if base:
            dirs += [os.path.join(base, "PyQt5", "Qt5", "translations"), os.path.join(base, "PyQt5", "Qt", "translations"),
                     os.path.join(base, "PySide6", "translations")]
        ok = False
        for name in ("qtbase_ko", "qt_ko"):
            for d in dirs:
                tr_ = QTranslator()
                if d and tr_.load(name, d):
                    app.installTranslator(tr_)
                    _qt_translators.append(tr_)
                    ok = True
                    break
        return ok
    except Exception:
        return False
