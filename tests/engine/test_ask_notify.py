"""사무 기능 ⑤: 사람에게 묻기·알림(가짜 묻는 창·가짜 알림, 알림 기록 파일은 임시 폴더)."""
import json
import os

from engine import new_macro, validate_macro
from engine import notify
from tests.engine.test_runner import World


def typed(w):
    return [e[2] for e in w.input.events if e[1] == "type"]


def run(steps, **attrs):
    w = World()
    r = w.runner(new_macro("m", steps))
    for k, v in attrs.items():
        setattr(r, k, v)
    return r.run(), w


def test_ask_input_confirm_choose_with_fake_dialog():
    asked = []

    def asker(req, stop):
        asked.append(req)
        return {"input": ("ok", "11"), "confirm": ("ok", True), "choose": ("ok", "부산")}[req["kind"]]
    res, w = run([
        {"type": "set", "var": "지점들", "value": ["강남", "부산"]},
        {"type": "ask", "kind": "input", "var": "달", "message": "몇 월 자료를 처리할까요?"},
        {"type": "ask", "kind": "choose", "var": "지점", "options": "지점들", "message": "{달}월 어느 지점?"},
        {"type": "ask", "kind": "confirm", "var": "진행", "message": "{지점} {달}월로 진행할까요?"},
        {"type": "if", "cond": {"var": "진행", "eq": True}, "then": [{"type": "type_text", "text": "{지점}_{달}월"}]},
    ], asker=asker)
    assert res.status == "ok", res.error
    assert typed(w) == ["부산_11월"]
    assert asked[1]["options"] == ["강남", "부산"] and asked[1]["message"] == "11월 어느 지점?"
    assert asked[2]["message"] == "부산 11월로 진행할까요?"


def test_ask_cancel_timeout_and_no_dialog():
    res, _ = run([{"type": "ask", "var": "x"}], asker=lambda r, s: ("cancel", None))
    assert res.status == "failed" and "취소" in res.error["reason"]
    res, w = run([{"type": "ask", "var": "x", "default": "기본", "timeout": 5},
                  {"type": "type_text", "text": "{x}"}], asker=lambda r, s: ("timeout", None))
    assert res.status == "ok" and typed(w) == ["기본"]
    res, w = run([{"type": "ask", "var": "x", "default": "AI실행"}, {"type": "type_text", "text": "{x}"}])
    assert res.status == "ok" and typed(w) == ["AI실행"]           # 묻는 창이 없으면 기본값 + 경고
    res, _ = run([{"type": "ask", "var": "x"}])
    assert res.status == "failed"


def test_notify_uses_notifier_and_failures_are_warnings():
    sent = []

    def notifier(title, msg, channels, level, url, source):
        sent.append((title, msg, list(channels), level))
        return ["webhook: 주소 없음"] if "webhook" in channels else []
    res, w = run([{"type": "set", "var": "n", "value": 3},
                  {"type": "notify", "title": "끝", "message": "{n}건 처리"},
                  {"type": "notify", "channels": ["webhook"], "message": "실패 알림", "level": "error"},
                  {"type": "type_text", "text": "계속"}], notifier=notifier)
    assert res.status == "ok" and typed(w) == ["계속"]
    assert sent[0] == ("끝", "3건 처리", ["toast"], "info")
    assert any(e.get("event") == "warning" for e in w.events)
    res, _ = run([{"type": "notify", "channels": "webhook", "message": "x", "must": True}], notifier=notifier)
    assert res.status == "failed"


def test_notify_module_log_and_webhook_config(tmp_path, monkeypatch):
    posted = []
    monkeypatch.setattr(notify, "webhook", lambda url, title, msg, timeout=10.0: posted.append((url, title, msg)))
    monkeypatch.setattr(notify, "toast", lambda title, msg: posted.append(("toast", title, msg)))
    os.makedirs(tmp_path / "settings")
    (tmp_path / "settings" / "notify.json").write_text(json.dumps({"webhook": "https://example.invalid/hook"}),
                                                      encoding="utf-8")
    errs = notify.send("매크로 멈춤", "3시간째 그대로", channels=["toast", "webhook"], level="warning",
                       source="감시", root=str(tmp_path))
    assert errs == []
    assert posted == [("toast", "매크로 멈춤", "3시간째 그대로"), ("https://example.invalid/hook", "매크로 멈춤", "3시간째 그대로")]
    line = (tmp_path / "logs" / "notify" / "notify.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["source"] == "감시"
    os.remove(tmp_path / "settings" / "notify.json")
    errs = notify.send("a", "b", channels=["webhook"], root=str(tmp_path))
    assert errs and "webhook" in errs[0]


def test_validate_ask_notify():
    assert validate_macro(new_macro("m", [{"type": "ask", "var": "x", "kind": "choose", "options": ["a"]},
                                          {"type": "notify", "message": "m", "channels": ["toast", "sound"]}])) == []
    errs = validate_macro(new_macro("m", [{"type": "ask", "kind": "없음", "var": "x"},
                                          {"type": "ask", "kind": "choose", "var": "x"},
                                          {"type": "notify", "message": "m", "channels": ["메일"]},
                                          {"type": "notify"}]))
    assert len(errs) == 4, errs
