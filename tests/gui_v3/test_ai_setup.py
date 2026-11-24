"""AI 연결 한 번에: 깔린 AI 찾기·설정에 macro 한 칸만 넣기(원래 설정 보존·백업·깨진 파일은 안 건드림)·요청 글."""
import json
import os

import pytest

from gui.v3 import ai_setup

SPEC = {"command": r"D:\내 자료\매크로\MacroManager.exe", "args": ["--mcp"], "env": {}, "cwd": r"D:\내 자료\매크로"}


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    app = tmp_path / "appdata"
    (app / "Claude").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    (home / ".cursor").mkdir(parents=True)
    return {"USERPROFILE": str(home), "APPDATA": str(app)}


def _c(env, key):
    return next(c for c in ai_setup.clients(env) if c["key"] == key)


def test_detects_installed(env):
    by = {c["key"]: c["installed"] for c in ai_setup.clients(env)}
    assert by["claude_desktop"] and by["codex"] and by["cursor"] and not by["gemini"]


def test_json_keeps_other_settings_and_backs_up(env):
    c = _c(env, "claude_desktop")
    with open(c["path"], "w", encoding="utf-8") as f:
        json.dump({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}, f)
    assert ai_setup.status(c, SPEC) == "absent"
    res = ai_setup.connect(c, SPEC)
    assert res["ok"] and res["backup"] and os.path.exists(res["backup"])
    d = json.load(open(c["path"], encoding="utf-8"))
    assert d["theme"] == "dark" and d["mcpServers"]["other"] == {"command": "x"}
    assert d["mcpServers"]["macro"]["command"] == SPEC["command"]
    assert ai_setup.status(c, SPEC) == "connected"
    assert ai_setup.status(c, dict(SPEC, command="다른.exe")) == "different"


def test_cursor_entry_has_type_and_new_file(env):
    c = _c(env, "cursor")
    assert ai_setup.connect(c, SPEC)["ok"]
    d = json.load(open(c["path"], encoding="utf-8"))
    assert d["mcpServers"]["macro"]["type"] == "stdio"


def test_broken_json_is_not_overwritten(env):
    c = _c(env, "claude_desktop")
    open(c["path"], "w", encoding="utf-8").write("{ 깨진")
    assert ai_setup.status(c, SPEC) == "broken"
    res = ai_setup.connect(c, SPEC)
    assert not res["ok"] and open(c["path"], encoding="utf-8").read() == "{ 깨진"


def test_toml_replaces_only_macro_block(env):
    c = _c(env, "codex")
    open(c["path"], "w", encoding="utf-8").write(
        'model = "gpt"\n\n[mcp_servers.macro]\ncommand = "old.exe"\nargs = []\n\n[mcp_servers.macro.env]\nA = "1"\n\n'
        '[mcp_servers.other]\ncommand = "o.exe"\n')
    assert ai_setup.status(c, SPEC) == "different"
    assert ai_setup.connect(c, SPEC)["ok"]
    t = open(c["path"], encoding="utf-8").read()
    assert 'model = "gpt"' in t and "[mcp_servers.other]" in t and "old.exe" not in t and 'A = "1"' not in t
    assert t.count("[mcp_servers.macro]") == 1
    assert ai_setup.status(c, SPEC) == "connected"
    import tomllib
    d = tomllib.loads(t)
    assert d["mcp_servers"]["macro"]["cwd"] == SPEC["cwd"] and d["mcp_servers"]["other"]["command"] == "o.exe"


def test_request_text():
    t = ai_setup.request("환율 읽기", "환율")
    assert "macro_reference" in t and "할 일: 환율 읽기" in t and "매크로 이름: 환율" in t


def test_dialog_rows(qapp, env, monkeypatch):
    from gui.v3 import ai_connect
    monkeypatch.setattr(ai_setup, "clients", lambda e=None: [
        c for c in _ORIG(env) if c["kind"] != "cli"])
    monkeypatch.setattr(ai_connect, "launch_spec", lambda: SPEC)
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *a, **k: 0)
    d = ai_connect.show_dialog(None, exec_=False)
    c, st, btn, refresh = d._rows["cursor"]
    assert btn.isEnabled() and "안 됨" in st.text()
    btn.click()
    assert not btn.isEnabled() and "연결됨" in st.text()
    assert "gemini" in d._rows and not d._rows["gemini"][2].isEnabled()     # 없는 프로그램
    d._task.setText("엑셀 정리")
    d._copy.click()
    from PySide6.QtWidgets import QApplication
    assert "할 일: 엑셀 정리" in QApplication.clipboard().text()


_ORIG = ai_setup.clients
