"""엑셀 남는 일 재발 방지: 켠 것 기록·남은 것 닫기 요청(강제 종료 없음)·응답 없음 시간 제한·실행 끝 정리."""
import threading
import time

import pytest

from engine import office_guard as og
from engine.office import OfficeError, OfficeSession


@pytest.fixture
def fake_os(monkeypatch, tmp_path):
    st = {"procs": {}, "wins": {}, "closed": []}
    monkeypatch.setattr(og, "processes", lambda names=None: dict(st["procs"]))
    monkeypatch.setattr(og, "windows", lambda pid: list(st["wins"].get(pid, [])))
    monkeypatch.setattr(og, "post_close", lambda h: st["closed"].append(h))
    st["root"] = str(tmp_path)
    return st


def test_owner_gone_hidden_docless_gets_close_request(fake_os):
    r = fake_os["root"]
    og.started("엑셀", 111, root=r)
    rows = og._load(og.record_path(r))
    rows[0]["owner"] = 999               # 주인 프로그램이 꺼진 상태
    og._save(og.record_path(r), rows)
    fake_os["procs"] = {111: "EXCEL.EXE"}
    fake_os["wins"] = {111: [{"hwnd": 5, "cls": "XLMAIN", "title": "Excel", "visible": False}]}
    rep = og.cleanup(root=r)
    assert rep == [{"pid": 111, "app": "엑셀", "done": "closed"}]
    assert fake_os["closed"] == [5]
    fake_os["procs"] = {}                # 닫기 요청 뒤 꺼짐 → 기록에서 빠짐
    assert og.cleanup(root=r)[0]["done"] == "gone"
    assert og._load(og.record_path(r)) == []


def test_document_open_is_kept_and_noticed_once(fake_os):
    r = fake_os["root"]
    og.started("엑셀", 222, root=r)
    rows = og._load(og.record_path(r))
    rows[0]["owner"] = 999
    og._save(og.record_path(r), rows)
    fake_os["procs"] = {222: "EXCEL.EXE"}
    fake_os["wins"] = {222: [{"hwnd": 7, "cls": "XLMAIN", "title": "장부.xlsx - Excel", "visible": False}]}
    seen = []
    assert og.cleanup(root=r, notify=lambda a, p: seen.append(p))[0]["done"] == "kept"
    og.cleanup(root=r, notify=lambda a, p: seen.append(p))
    assert fake_os["closed"] == [] and seen == [222]


def test_owner_alive_in_use_is_left_alone(fake_os):
    import os
    r = fake_os["root"]
    og.started("워드", 333, root=r)
    fake_os["procs"] = {333: "WINWORD.EXE", os.getpid(): "PYTHON.EXE"}
    fake_os["wins"] = {333: [{"hwnd": 9, "cls": "OpusApp", "title": "Word", "visible": False}]}
    assert og.cleanup(root=r) == []
    assert fake_os["closed"] == []
    og.quit_sent(333, root=r)            # 닫으라고 한 지 1분 지나도 살아 있으면 남은 것
    assert og.cleanup(root=r, now=time.time() + 61)[0]["done"] == "closed"


def test_pid_reused_by_other_program_is_dropped(fake_os):
    r = fake_os["root"]
    og.started("엑셀", 444, root=r)
    fake_os["procs"] = {444: "NOTEPAD.EXE"}
    assert og.cleanup(root=r)[0]["done"] == "gone"
    assert fake_os["closed"] == []


def test_session_call_timeout_marks_broken():
    s = OfficeSession(call_timeout=0.3, guard=False)
    gate = threading.Event()
    with pytest.raises(OfficeError, match="응답 없음"):
        s._call(lambda: gate.wait(5))
    assert s.broken
    with pytest.raises(OfficeError):
        s._call(lambda: 1)
    gate.set()
    t0 = time.time()
    s.shutdown()                         # 멈춘 세션이어도 닫기가 오래 걸리지 않음
    assert time.time() - t0 < 2


def test_runner_shuts_office_even_on_unexpected_error(monkeypatch):
    from engine import new_macro
    from tests.engine.test_runner import World
    m = new_macro("t", [{"type": "delay", "seconds": 0}])
    r = World().runner(m)
    closed = []

    class Off:
        def shutdown(self):
            closed.append(1)
    r.office = Off()
    r._office_owner = True

    def boom(stop):
        raise KeyboardInterrupt
    monkeypatch.setattr(r, "_run", boom)
    with pytest.raises(KeyboardInterrupt):
        r.run()
    assert closed == [1] and r.office is None
