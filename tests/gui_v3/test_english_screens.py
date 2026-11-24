"""영어 화면에 한글이 하나도 없어야 한다(전 세계 공개용).

별도 프로세스(MACRO_LANG=en, 화면 없는 Qt, 가짜 화면)에서 tests/gui_v3/english_scan.py 가 메인 창·메뉴·우클릭 메뉴·
모든 대화상자·편집기의 스텝 종류별 입력칸(콤보를 바꿔 가며)·실행 기록·승인 대기함·고침 기록·알림창 글을 훑어
한글이 든 글을 모아 준다. 사용자가 만든 이름(시험용 매크로 이름)·파일 경로·언어 이름(한국어)은 뺀다.
"""
import json
import os
import subprocess
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def test_no_korean_on_english_screens(tmp_path):
    out = tmp_path / "scan.json"
    env = dict(os.environ)
    env["MACRO_LANG"] = "en"
    env["SCAN_LANG"] = "en"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, os.path.join(HERE, "english_scan.py"), str(out)], cwd=ROOT, env=env,
                       capture_output=True, timeout=600)
    assert out.exists(), "훑기 도구가 끝까지 못 돌았음:\n" + p.stderr.decode("utf-8", "replace")[-2000:]
    res = json.loads(out.read_text(encoding="utf-8"))
    lines = [f"{k!r}  <- {sorted(v)[0]}" for k, v in sorted(res["found"].items())]
    assert not lines, f"영어 화면에 한글 {len(lines)}개:\n" + "\n".join(lines)
    assert not res["errors"], "못 띄운 화면이 있음(훑기가 비어 있을 수 있음):\n" + "\n".join(res["errors"])


@pytest.mark.skipif(not hasattr(__import__("ctypes"), "windll"), reason="윈도우 전용")
def test_start_language_follows_windows_display_language(monkeypatch):
    """윈도우 표시 언어가 한국어가 아니면 영어로 시작, 한국어면 한국어."""
    import ctypes
    from gui.v2 import i18n

    def fake(lid):
        return types.SimpleNamespace(kernel32=types.SimpleNamespace(GetUserDefaultUILanguage=lambda: lid))
    for lid, want in ((0x0412, "ko"), (0x0409, "en"), (0x0411, "en"), (0x0C0A, "en")):
        monkeypatch.setattr(ctypes, "windll", fake(lid), raising=False)
        assert i18n._system_lang() == want

    # 저장된 선택도 환경 값도 없을 때 처음 정해지는 언어
    old_lang, old_dict = i18n._lang, dict(i18n._dict)
    try:
        monkeypatch.delenv("MACRO_LANG", raising=False)
        monkeypatch.setattr(i18n, "_settings", lambda: types.SimpleNamespace(value=lambda *a, **k: "", setValue=lambda *a: None))
        monkeypatch.setattr(i18n, "_system_lang", lambda: "en")
        i18n._lang = None
        assert i18n.current() == "en"
        assert i18n.tr("새 매크로") == "New macro"
        # 설정에서 고른 언어가 윈도우 언어보다 먼저
        monkeypatch.setattr(i18n, "_settings", lambda: types.SimpleNamespace(value=lambda *a, **k: "ko", setValue=lambda *a: None))
        i18n._lang = None
        assert i18n.current() == "ko"
    finally:
        i18n._lang, i18n._dict = old_lang, old_dict
        monkeypatch.setenv("MACRO_LANG", "ko")
