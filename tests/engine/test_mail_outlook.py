"""메일 가(아웃룩): 가짜 아웃룩(자동화 통로 흉내)으로 찾기·본문·첨부 저장·읽음·옮기기·보내기(기본 임시 보관함)."""
import os

from engine import new_macro, validate_macro
from engine.mail import OutlookMail
from tests.engine.test_runner import World


class Att:
    def __init__(self, name, data):
        self.FileName, self.data = name, data

    def SaveAsFile(self, p):
        with open(p, "wb") as fh:
            fh.write(self.data)


class Atts:
    def __init__(self, items):
        self.items = list(items)

    @property
    def Count(self):
        return len(self.items)

    def Item(self, i):
        return self.items[i - 1]

    def Add(self, p):
        self.items.append(Att(os.path.basename(p), b""))


class Mail:
    Class = 43

    def __init__(self, eid, sender, subject, when, unread, atts=(), body=""):
        self.EntryID, self.SenderName, self.SenderEmailAddress = eid, sender, sender.lower() + "@example.invalid"
        self.Subject, self.ReceivedTime, self.UnRead, self.Body = subject, when, unread, body
        self.Attachments = Atts(atts)
        self.saved = False
        self.moved_to = None

    def Save(self):
        self.saved = True

    def Move(self, folder):
        self.moved_to = folder.name


class Items:
    def __init__(self, mails):
        self.mails = list(mails)
        self.i = 0

    def Sort(self, key, desc):
        self.mails.sort(key=lambda m: m.ReceivedTime, reverse=desc)

    def Restrict(self, f):
        if "UnRead" in f:
            return Items([m for m in self.mails if m.UnRead])
        return self

    def GetFirst(self):
        self.i = 0
        return self.GetNext()

    def GetNext(self):
        if self.i >= len(self.mails):
            return None
        self.i += 1
        return self.mails[self.i - 1]


class Folder:
    def __init__(self, name, mails=(), subs=None, parent=None):
        self.name, self._mails, self.subs, self.Parent = name, list(mails), subs or {}, parent

    @property
    def Items(self):
        return Items(self._mails)

    def Folders(self, name):
        return self.subs[name]


class NS:
    def __init__(self, inbox, all_mails):
        self.inbox, self.all = inbox, {m.EntryID: m for m in all_mails}

    def GetDefaultFolder(self, n):
        return self.inbox

    def GetItemFromID(self, eid):
        return self.all[eid]


class App:
    def __init__(self):
        m1 = Mail("A1", "거래처", "11월 청구서", "2026-11-03 09:00", True, [Att("청구서.pdf", b"%PDF-1"), Att("logo.png", b"x")])
        m2 = Mail("A2", "광고", "할인 안내", "2026-11-04 10:00", True)
        m3 = Mail("A3", "거래처", "10월 청구서", "2026-10-03 09:00", False, [Att("청구서.pdf", b"%PDF-2")], body="본문입니다")
        root = Folder("root")
        self.done = Folder("처리완료", parent=root)
        root.subs = {"처리완료": self.done}
        self.inbox = Folder("받은편지함", [m1, m2, m3], parent=root)
        self.ns = NS(self.inbox, [m1, m2, m3])
        self.created = []

    def GetNamespace(self, n):
        return self.ns

    def CreateItem(self, k):
        m = Mail("NEW", "", "", "", False)
        m.Send = lambda: setattr(m, "sent", True)
        self.created.append(m)
        return m


def run(steps, tmp_path, app):
    w = World()
    r = w.runner(new_macro("m", steps))
    r.base_dir = str(tmp_path)
    r.mail_factory = lambda via: OutlookMail(app)
    return r.run(), w


def test_find_save_mark_move(tmp_path):
    app = App()
    res, w = run([
        {"type": "mail", "action": "find", "from": "거래처", "subject": "청구서", "unread": True, "has_attachment": True,
         "var": "메일들"},
        {"type": "mail", "action": "save_attachments", "mail": "메일들", "path": "받은첨부", "pattern": "*.pdf", "var": "저장"},
        {"type": "mail", "action": "mark_read", "mail": "메일들"},
        {"type": "mail", "action": "move", "mail": "메일들", "to_folder": "처리완료"},
        {"type": "mail", "action": "read", "mail": "A3", "var": "본문"},
        {"type": "type_text", "text": "{메일들.1.subject}/{본문}"},
    ], tmp_path, app)
    assert res.status == "ok", res.error
    assert os.listdir(tmp_path / "받은첨부") == ["청구서.pdf"]
    m1 = app.ns.all["A1"]
    assert m1.UnRead is False and m1.moved_to == "처리완료"
    assert app.ns.all["A2"].UnRead is True                         # 광고는 안 건드림
    assert [e[2] for e in w.input.events if e[1] == "type"] == ["11월 청구서/본문입니다"]
    assert any(e.get("event") == "file" and e.get("action") == "mail_attachment" for e in w.events)


def test_send_default_is_draft_and_logged(tmp_path):
    app = App()
    (tmp_path / "정리.xlsx").write_bytes(b"x")
    res, w = run([{"type": "mail", "action": "send", "to": "boss@example.invalid", "subject": "11월 정리",
                   "body": "첨부합니다", "attachments": "정리.xlsx"}], tmp_path, app)
    assert res.status == "ok", res.error
    m = app.created[0]
    assert m.saved and not getattr(m, "sent", False)               # 기본은 임시 보관함
    ev = [e for e in w.events if e.get("event") == "mail_draft"]
    assert ev and ev[0]["to"] == "boss@example.invalid" and ev[0]["attachments"] == ["정리.xlsx"]
    res, w = run([{"type": "mail", "action": "send", "to": "a@example.invalid", "send_now": True}], tmp_path, app)
    assert getattr(app.created[1], "sent", False) and any(e.get("event") == "mail_sent" for e in w.events)


def test_send_missing_attachment_fails_and_validation(tmp_path):
    res, _ = run([{"type": "mail", "action": "send", "to": "a@example.invalid", "attachments": "없음.pdf"}], tmp_path, App())
    assert res.status == "failed" and "첨부할 파일" in res.error["reason"]
    errs = validate_macro(new_macro("m", [{"type": "mail", "action": "find"},
                                          {"type": "mail", "action": "read", "var": "x"},
                                          {"type": "mail", "action": "send"},
                                          {"type": "mail", "via": "web", "action": "find", "var": "x"},
                                          {"type": "mail", "via": "server", "action": "find", "var": "x"}]))
    assert len(errs) == 5, errs
