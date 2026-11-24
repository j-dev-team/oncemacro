"""메일 다(메일 서버 직접): 이 컴퓨터 안 가짜 IMAP·SMTP 로 찾기·본문·첨부·읽음·옮기기·임시 저장·보내기."""
import email
import json
import os
from email.message import EmailMessage

import pytest

from engine import new_macro
from engine import mailserver
from engine.mailserver import ServerMail, save_account, load_accounts
from tests.engine.fake_mailservers import FakeIMAP, FakeSMTP
from tests.engine.test_runner import World


def mk(subject, sender, body, att=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "me@example.invalid", subject
    m["Date"] = "Tue, 03 Nov 2026 09:00:00 +0900"
    m.set_content(body)
    if att:
        m.add_attachment(att[1], maintype="application", subtype="pdf", filename=att[0])
    return m.as_bytes()


@pytest.fixture
def servers(tmp_path):
    imap = FakeIMAP(folders={"INBOX": [], "Drafts": [], "처리완료": []})
    imap.add("INBOX", mk("11월 청구서", "거래처 <bill@client.invalid>", "금액 1,250,000원", ("청구서.pdf", b"%PDF-1")))
    imap.add("INBOX", mk("할인 안내", "광고 <ad@x.invalid>", "광고"))
    imap.add("INBOX", mk("10월 청구서", "거래처 <bill@client.invalid>", "지난달", ("청구서.pdf", b"%PDF-0")), seen=True)
    smtp = FakeSMTP()
    save_account("회사", {"imap_host": "127.0.0.1", "imap_port": imap.port, "smtp_host": "127.0.0.1",
                         "smtp_port": smtp.port, "user": "me", "ssl": False, "drafts": "Drafts", "password": "넣어도 저장 안 됨"},
                 root=str(tmp_path))
    yield imap, smtp
    imap.stop()
    smtp.stop()


def run(steps, tmp_path):
    w = World()
    r = w.runner(new_macro("m", steps))
    r.base_dir = str(tmp_path)
    r.mail_factory = lambda via: ServerMail("회사", root=str(tmp_path), password_reader=lambda a: "pw")
    return r.run(), w


def test_password_never_saved_in_settings(servers, tmp_path):
    raw = open(mailserver.accounts_path(str(tmp_path)), encoding="utf-8").read()
    assert "password" not in raw and "넣어도" not in raw
    assert load_accounts(str(tmp_path))["회사"]["user"] == "me"


def test_find_read_attach_mark_move(servers, tmp_path):
    imap, _ = servers
    res, w = run([
        {"type": "mail", "via": "server", "account": "회사", "action": "find", "subject": "청구서", "unread": True,
         "has_attachment": True, "var": "메일들"},
        {"type": "mail", "via": "server", "account": "회사", "action": "read", "mail": "메일들", "var": "본문"},
        {"type": "mail", "via": "server", "account": "회사", "action": "save_attachments", "mail": "메일들", "path": "첨부"},
        {"type": "mail", "via": "server", "account": "회사", "action": "mark_read", "mail": "메일들"},
        {"type": "mail", "via": "server", "account": "회사", "action": "move", "mail": "메일들", "to_folder": "처리완료"},
        {"type": "type_text", "text": "{메일들.1.subject}|{본문}"},
    ], tmp_path)
    assert res.status == "ok", res.error
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["11월 청구서|금액 1,250,000원"]
    assert os.listdir(tmp_path / "첨부") == ["청구서.pdf"]
    assert len(imap.folders["처리완료"]) == 1 and "\\Seen" in imap.folders["처리완료"][0]["flags"]
    assert len(imap.folders["INBOX"]) == 2                               # 광고·지난달은 그대로


def test_send_draft_default_and_send_now(servers, tmp_path):
    imap, smtp = servers
    (tmp_path / "정리.xlsx").write_bytes(b"xlsx")
    res, w = run([{"type": "mail", "via": "server", "account": "회사", "action": "send", "to": "boss@example.invalid",
                   "subject": "11월 정리", "body": "첨부합니다", "attachments": "정리.xlsx"}], tmp_path)
    assert res.status == "ok", res.error
    assert smtp.sent == [] and len(imap.folders["Drafts"]) == 1          # 기본은 임시 보관함
    d = email.message_from_bytes(imap.folders["Drafts"][0]["raw"])
    assert mailserver._dec(d["Subject"]) == "11월 정리" and "\\Draft" in imap.folders["Drafts"][0]["flags"]
    res, w = run([{"type": "mail", "via": "server", "account": "회사", "action": "send", "to": "boss@example.invalid",
                   "subject": "바로", "send_now": True}], tmp_path)
    assert res.status == "ok" and len(smtp.sent) == 1 and smtp.sent[0]["rcpt"] == ["boss@example.invalid"]
    assert any(e.get("event") == "mail_sent" for e in w.events)


def test_missing_account_or_password(tmp_path):
    w = World()
    r = w.runner(new_macro("m", [{"type": "mail", "via": "server", "account": "없음", "action": "find", "var": "x"}]))
    r.mail_factory = lambda via: ServerMail("없음", root=str(tmp_path), password_reader=lambda a: None)
    res = r.run()
    assert res.status == "failed" and "설정 → 메일 계정" in res.error["reason"]


def test_korean_folder_quote():
    assert mailserver._imap_quote_folder("INBOX") == '"INBOX"'
    from tests.engine.fake_mailservers import _mutf7_decode
    q = mailserver._imap_quote_folder("보낸편지함")
    assert q.startswith('"&') and _mutf7_decode(q.strip('"')) == "보낸편지함"
