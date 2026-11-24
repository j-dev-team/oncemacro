"""메일 단계(Qt 없음). 세 길을 같은 모양으로 다룬다.

- outlook : 이 컴퓨터에 켜진 아웃룩(데스크톱판)을 그대로 씀. 계정·비밀번호 필요 없음.
- web     : 웹메일(다음·네이트·구글·네이버) 브라우저 자동화 — engine/webmail.py (사람이 미리 로그인해 둔 브라우저)
- server  : 메일 서버 직접 연결(IMAP 받기·SMTP 보내기) — 계정은 사용자가 설정 화면에서 넣고, 비밀번호는 윈도우 자격 증명에

동작: find(찾기) · read(본문 읽기) · save_attachments(첨부 저장) · mark_read(읽음 표시) · move(폴더 옮기기) · send(보내기)
보내기 기본은 '임시 보관함 저장'(draft). 바로 보내려면 send_now=true. 보낸 것·임시 저장한 것은 실행 기록에 남긴다.
메일 하나는 {"id", "from", "subject", "date", "unread", "attachments": [이름]} 모양(본문은 read 로).
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any, List, Optional

from .i18n import t

ACTIONS = ("find", "read", "save_attachments", "mark_read", "move", "send")
VIAS = ("outlook", "web", "server")


class MailError(Exception):
    pass


def match(mail: dict, crit: dict) -> bool:
    """찾기 조건(보낸 사람·제목 글자 일부, 안 읽음, 첨부 있음)."""
    if crit.get("from") and str(crit["from"]).lower() not in str(mail.get("from", "")).lower():
        return False
    if crit.get("subject") and str(crit["subject"]).lower() not in str(mail.get("subject", "")).lower():
        return False
    if crit.get("unread") is True and not mail.get("unread"):
        return False
    if crit.get("has_attachment") and not mail.get("attachments"):
        return False
    return True


def safe_name(name: str) -> str:
    return "".join(ch for ch in str(name) if ch not in '\\/:*?"<>|').strip() or "attachment"


# ---------------------------------------------------------------- 아웃룩
class OutlookMail:
    """아웃룩(데스크톱판) 자동화 통로로 메일함을 다룬다. COM 은 만든 스레드에서만 쓰므로 부를 때마다 연다."""

    INBOX = 6

    def __init__(self, app=None):
        self._app = app                  # 시험에서 가짜를 넣음

    def _ns(self):
        if self._app is None:
            try:
                import pythoncom
                import win32com.client
                pythoncom.CoInitialize()
                try:
                    self._app = win32com.client.GetActiveObject("Outlook.Application")
                except Exception:
                    self._app = win32com.client.Dispatch("Outlook.Application")
            except Exception as e:
                raise MailError(t("아웃룩을 쓸 수 없음(데스크톱판 아웃룩이 깔려 있고 계정이 연결돼 있어야 함): {error}", error=e))
        return self._app, self._app.GetNamespace("MAPI")

    def _folder(self, ns, name: Optional[str]):
        f = ns.GetDefaultFolder(self.INBOX)
        if not name or name in ("받은편지함", "inbox", "Inbox"):
            return f
        for part in re.split(r"[\\/>]", name):
            part = part.strip()
            if not part:
                continue
            try:
                f = f.Folders(part)
            except Exception:
                try:
                    f = f.Parent.Folders(part)            # 받은편지함과 나란한 폴더
                except Exception:
                    raise MailError(t("메일 폴더가 없음: {name}", name=name))
        return f

    @staticmethod
    def _to_dict(it) -> dict:
        try:
            atts = [it.Attachments.Item(i).FileName for i in range(1, it.Attachments.Count + 1)]
        except Exception:
            atts = []
        when = getattr(it, "ReceivedTime", None)
        return {"id": it.EntryID, "from": f"{getattr(it, 'SenderName', '')} <{getattr(it, 'SenderEmailAddress', '')}>",
                "subject": getattr(it, "Subject", ""), "date": str(when)[:19] if when else "",
                "unread": bool(getattr(it, "UnRead", False)), "attachments": atts}

    def find(self, crit: dict) -> List[dict]:
        _, ns = self._ns()
        items = self._folder(ns, crit.get("folder")).Items
        items.Sort("[ReceivedTime]", True)
        if crit.get("unread"):
            items = items.Restrict("[UnRead] = True")
        if crit.get("days"):
            import datetime as _dt
            since = (_dt.datetime.now() - _dt.timedelta(days=float(crit["days"]))).strftime("%Y-%m-%d %H:%M")
            items = items.Restrict(f"[ReceivedTime] >= '{since}'")
        out = []
        limit = int(crit.get("max", 50))
        it = items.GetFirst()
        scanned = 0
        while it is not None and len(out) < limit and scanned < 2000:
            scanned += 1
            if getattr(it, "Class", 43) == 43:              # olMail
                d = self._to_dict(it)
                if match(d, crit):
                    out.append(d)
            it = items.GetNext()
        return out

    def _item(self, mail_id: str):
        _, ns = self._ns()
        try:
            return ns.GetItemFromID(mail_id)
        except Exception:
            raise MailError(t("메일을 찾지 못함(지워졌거나 옮겨짐)"))

    def read(self, mail_id: str) -> str:
        return str(self._item(mail_id).Body or "")

    def attachments(self, mail_id: str, pattern: str = "*") -> List[tuple]:
        """[(파일 이름, 저장하는 함수(경로))]"""
        it = self._item(mail_id)
        out = []
        for i in range(1, it.Attachments.Count + 1):
            a = it.Attachments.Item(i)
            if fnmatch.fnmatch(a.FileName.lower(), (pattern or "*").lower()):
                out.append((a.FileName, a.SaveAsFile))
        return out

    def mark_read(self, mail_id: str) -> None:
        it = self._item(mail_id)
        it.UnRead = False
        it.Save()

    def move(self, mail_id: str, folder: str) -> None:
        _, ns = self._ns()
        self._item(mail_id).Move(self._folder(ns, folder))

    def send(self, msg: dict, now: bool) -> str:
        app, _ = self._ns()
        m = app.CreateItem(0)
        m.To = msg.get("to", "")
        if msg.get("cc"):
            m.CC = msg["cc"]
        m.Subject = msg.get("subject", "")
        m.Body = msg.get("body", "")
        for p in msg.get("attachments") or []:
            m.Attachments.Add(p)
        if now:
            m.Send()
            return "sent"
        m.Save()                                              # 임시 보관함
        return "draft"


def split_list(v: Any) -> List[str]:
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[;\n]", str(v or "")) if x.strip()]


def backend(via: str, runner=None, step: Optional[dict] = None):
    step = step or {}
    if via == "outlook":
        return OutlookMail()
    if via == "web":
        from .webmail import WebMail
        return WebMail(runner, step.get("service"))
    if via == "server":
        from .mailserver import ServerMail
        return ServerMail(step.get("account", ""))
    raise MailError(t("모르는 메일 길 '{via}'", via=via))


__all__ = ["ACTIONS", "VIAS", "MailError", "OutlookMail", "match", "safe_name", "split_list", "backend"]

