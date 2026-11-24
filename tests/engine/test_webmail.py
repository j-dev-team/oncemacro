"""메일 나(웹메일): 가짜 브라우저로 흐름 확인(찾기·본문·첨부·임시 저장·로그인 화면이면 멈춤). 실제 화면 구조는 사람이 있을 때 확인."""
import base64
import os

import pytest

from engine import new_macro
from engine import webmail
from tests.engine.test_runner import World


class FakeBrowser:
    def __init__(self, logged_in=True):
        self.logged_in = logged_in
        self.url = ""
        self.calls = []

    def run(self, action, **kw):
        self.calls.append((action, kw))
        if action == "goto":
            self.url = kw["url"] if self.logged_in else "https://nid.naver.com/nidlogin.login"
            return {"ok": True, "value": self.url}
        if action == "upload":
            return {"ok": True}
        if action == "script":
            js = kw["text"]
            if js == webmail.JS_LIST:
                res = [{"id": "https://mail.naver.com/read/1", "href": "https://mail.naver.com/read/1", "from": "거래처 <a@x>",
                        "subject": "11월 청구서", "date": "11.03", "unread": True, "attachments": ["(첨부)"]},
                       {"id": "https://mail.naver.com/read/2", "href": "https://mail.naver.com/read/2", "from": "광고",
                        "subject": "할인", "date": "11.04", "unread": True, "attachments": []}]
            elif js == webmail.JS_BODY:
                res = "청구 금액 1,250,000원"
            elif js == webmail.JS_ATTACH:
                res = [{"name": "청구서.pdf", "data": base64.b64encode(b"%PDF").decode()}]
            elif js in (webmail.JS_COMPOSE, webmail.JS_CLICK):
                res = "ok"
            else:
                res = None
            return {"ok": True, "value": {"url": self.url, "result": res}}
        return {"ok": True}

    def cancel(self):
        pass


def run(steps, tmp_path, browser):
    w = World()
    r = w.runner(new_macro("m", steps))
    r.base_dir = str(tmp_path)
    r.web = browser
    return r.run(), w


def test_services_pack_has_four_and_fields():
    packs = webmail.load_services()
    assert set(packs) == {"naver", "daum", "nate", "gmail"}
    for p in packs.values():
        for k in ("inbox_url", "compose_url", "login_hosts", "list", "read", "attachments", "compose"):
            assert k in p
        assert p["verified"] is False                     # 실제 화면으로 아직 확인 안 함


@pytest.mark.parametrize("service", ["naver", "daum", "nate", "gmail"])
def test_find_read_attach_draft(tmp_path, service):
    b = FakeBrowser()
    res, w = run([
        {"type": "mail", "via": "web", "service": service, "action": "find", "subject": "청구서", "has_attachment": True,
         "var": "메일들"},
        {"type": "mail", "via": "web", "service": service, "action": "read", "mail": "메일들", "var": "본문"},
        {"type": "mail", "via": "web", "service": service, "action": "save_attachments", "mail": "메일들", "path": "첨부"},
        {"type": "mail", "via": "web", "service": service, "action": "send", "to": "boss@example.invalid",
         "subject": "정리", "body": "{본문}"},
    ], tmp_path, b)
    assert res.status == "ok", res.error
    assert os.listdir(tmp_path / "첨부") == ["청구서.pdf"]
    pack = webmail.load_services()[service]
    assert b.calls[0] == ("goto", b.calls[0][1]) and b.calls[0][1]["url"] == pack["inbox_url"]
    clicks = [kw["args"]["sel"] for a, kw in b.calls if a == "script" and kw["text"] == webmail.JS_CLICK]
    assert clicks == [pack["compose"]["draft"]]            # 기본은 임시 저장 단추(보내기 아님)
    assert any(e.get("event") == "mail_draft" for e in w.events)


def test_login_page_stops(tmp_path):
    res, _ = run([{"type": "mail", "via": "web", "service": "naver", "action": "find", "var": "x"}], tmp_path,
                 FakeBrowser(logged_in=False))
    assert res.status == "failed" and "로그인이 필요함" in res.error["reason"]


def test_move_not_supported_on_web(tmp_path):
    res, _ = run([{"type": "mail", "via": "web", "service": "gmail", "action": "find", "var": "x"},
                  {"type": "mail", "via": "web", "service": "gmail", "action": "move", "mail": "x", "to_folder": "a"}],
                 tmp_path, FakeBrowser())
    assert res.status == "failed" and "폴더 옮기기" in res.error["reason"]
