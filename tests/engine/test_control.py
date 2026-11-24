"""실행 한 곳에서만: 화면 프로그램 제어 통로(engine/control.py) 시험. 실제 입력 없음(가짜 도구 함수)."""
import json
import os

import pytest

from engine import control


@pytest.fixture
def server(tmp_path, monkeypatch):
    calls = []

    def fake_call(tool, args):
        calls.append((tool, args))
        if tool == "macro_screenshot":
            from mcp.server.mcpserver import Image
            return ["보는 중", Image(data=b"\x89PNG fake", format="png")]
        return "ok:" + json.dumps(args, ensure_ascii=False)

    path = str(tmp_path / "control.json")
    srv = control.ControlServer(call=fake_call, path=path).start()
    monkeypatch.setattr(control, "IN_SERVER", False)          # 같은 프로세스에서 클라이언트 쪽도 시험
    # 같은 pid 는 넘기지 않게 돼 있으므로, 시험에서는 다른 pid 로 적고 살아 있다고 침
    info = json.load(open(path, encoding="utf-8"))
    info["pid"] = os.getpid() + 1
    json.dump(info, open(path, "w", encoding="utf-8"))
    monkeypatch.setattr(control, "_pid_alive", lambda pid: True)
    yield srv, path, calls
    srv.stop()


def test_relay_roundtrip_with_image(server):
    srv, path, calls = server
    out = control.relay("macro_screenshot", {"window_title": "창"}, path=path)
    assert out[0] == "보는 중"
    assert type(out[1]).__name__ == "Image" and out[1].to_image_content().mime_type == "image/png"
    assert calls == [("macro_screenshot", {"window_title": "창"})]
    assert control.relay("macro_stop", {}, path=path) == "ok:{}"


def test_unknown_tool_not_relayed(server):
    srv, path, calls = server
    assert control.relay("macro_save", {"name": "x"}, path=path) is None
    assert calls == []


def test_wrong_token_rejected(server):
    srv, path, calls = server
    info = json.load(open(path, encoding="utf-8"))
    r = control._request(dict(info, token="nope"), "POST", "/call", {"tool": "macro_stop", "args": {}}, 5)
    assert r["_status"] == 403 and calls == []


def test_dead_pid_falls_back(server, monkeypatch):
    srv, path, calls = server
    monkeypatch.setattr(control, "_pid_alive", lambda pid: False)
    assert control.relay("macro_stop", {}, path=path) is None


def test_no_file_falls_back(tmp_path):
    assert control.relay("macro_stop", {}, path=str(tmp_path / "없음.json")) is None


def test_server_side_never_relays(server, monkeypatch):
    srv, path, calls = server
    monkeypatch.setattr(control, "IN_SERVER", True)
    assert control.relay("macro_stop", {}, path=path) is None


def test_stop_removes_own_file(tmp_path):
    path = str(tmp_path / "c.json")
    srv = control.ControlServer(call=lambda t, a: None, path=path).start()
    assert os.path.exists(path)
    srv.stop()
    assert not os.path.exists(path)
    control.IN_SERVER = False


def test_reply_in_requesters_language(tmp_path, monkeypatch):
    from engine import i18n
    path = str(tmp_path / "c.json")
    srv = control.ControlServer(call=lambda tool, a: i18n.t("진행 중인 실행 없음"), path=path).start()
    monkeypatch.setattr(control, "IN_SERVER", False)
    info = json.load(open(path, encoding="utf-8"))
    info["pid"] = os.getpid() + 1
    json.dump(info, open(path, "w", encoding="utf-8"))
    monkeypatch.setattr(control, "_pid_alive", lambda pid: True)
    i18n.set_language("ko")
    tok = i18n.use_language("en")          # 요청하는 쪽만 영어
    try:
        out = control.relay("macro_stop", {}, path=path)
    finally:
        i18n._override.reset(tok)
        srv.stop()
    assert out != "진행 중인 실행 없음" and "run" in out.lower()
