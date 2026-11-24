"""메일 '다': 메일 서버 직접 연결(IMAP 받기·SMTP 보내기). 파이썬 기본 부품만 쓴다.

계정 설정: <자료 폴더>/settings/mail_accounts.json  {"계정 이름": {"imap_host", "imap_port", "smtp_host", "smtp_port",
          "user", "ssl"(true: IMAP 993·SMTP 465 암호화), "starttls"(SMTP 587), "drafts"(임시 보관함 이름)}}
비밀번호: 윈도우 자격 증명(engine/wincred.py). 설정 파일·매크로·기록에는 없다.
메일 id 는 IMAP UID(폴더 안에서 고유).
"""
from __future__ import annotations

import email
import email.header
import email.utils
import fnmatch
import imaplib
import json
import os
import re
import smtplib
import ssl as _ssl
import time
from email.message import EmailMessage
from typing import Dict, List, Optional

from .i18n import t
from .mail import MailError, match

PRESETS = {     # 널리 알려진 서버 주소(사용자가 고를 때 미리 채움)
    "naver": {"imap_host": "imap.naver.com", "imap_port": 993, "smtp_host": "smtp.naver.com", "smtp_port": 465, "ssl": True},
    "daum": {"imap_host": "imap.daum.net", "imap_port": 993, "smtp_host": "smtp.daum.net", "smtp_port": 465, "ssl": True},
    "nate": {"imap_host": "imap.nate.com", "imap_port": 993, "smtp_host": "smtp.mail.nate.com", "smtp_port": 465, "ssl": True},
    "gmail": {"imap_host": "imap.gmail.com", "imap_port": 993, "smtp_host": "smtp.gmail.com", "smtp_port": 465, "ssl": True},
}


def _root() -> str:
    try:
        from .real import PROJECT_ROOT
        return PROJECT_ROOT
    except Exception:
        return os.getcwd()


def accounts_path(root: Optional[str] = None) -> str:
    return os.path.join(root or _root(), "settings", "mail_accounts.json")


def load_accounts(root: Optional[str] = None) -> Dict[str, dict]:
    try:
        with open(accounts_path(root), encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def save_account(name: str, cfg: dict, root: Optional[str] = None) -> None:
    """계정 설정 저장(비밀번호 칸은 받지 않음 — 들어와도 지운다)."""
    cfg = {k: v for k, v in cfg.items() if k not in ("password", "pass", "pw")}
    acc = load_accounts(root)
    acc[name] = cfg
    p = accounts_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(acc, fh, ensure_ascii=False, indent=1)


def _dec(s) -> str:
    if s is None:
        return ""
    parts = []
    for text, enc in email.header.decode_header(str(s)):
        parts.append(text.decode(enc or "utf-8", "replace") if isinstance(text, bytes) else text)
    return "".join(parts).strip()


def _imap_quote_folder(name: str) -> str:
    """IMAP 폴더 이름(한글은 수정된 UTF-7)."""
    if all(32 <= ord(c) < 127 for c in name):
        return '"' + name.replace('"', '\\"') + '"'
    out, buf = [], ""
    for ch in name:
        if 32 <= ord(ch) < 127:
            if buf:
                import base64
                out.append("&" + base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=").replace("/", ",") + "-")
                buf = ""
            out.append("&-" if ch == "&" else ch)
        else:
            buf += ch
    if buf:
        import base64
        out.append("&" + base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=").replace("/", ",") + "-")
    return '"' + "".join(out) + '"'


class ServerMail:
    def __init__(self, account: str, root: Optional[str] = None, password_reader=None):
        self.account = account
        self.root = root
        self._password_reader = password_reader            # 시험에서 바꿈
        self._imap = None
        self._folder = None

    # ------------------------------------------------------------ 연결
    def _cfg(self) -> dict:
        acc = load_accounts(self.root)
        if self.account not in acc:
            raise MailError(t("메일 계정 '{name}' 이 없음 — 설정 → 메일 계정에서 먼저 만드세요", name=self.account))
        return acc[self.account]

    def _password(self) -> str:
        if self._password_reader is not None:
            pw = self._password_reader(self.account)
        else:
            from . import wincred
            pw = wincred.load(self.account)
        if not pw:
            raise MailError(t("메일 계정 '{name}' 의 비밀번호가 없음 — 설정 → 메일 계정에서 직접 넣으세요", name=self.account))
        return pw

    def _connect(self):
        if self._imap is not None:
            return self._imap
        c = self._cfg()
        try:
            if c.get("ssl", True):
                m = imaplib.IMAP4_SSL(c["imap_host"], int(c.get("imap_port", 993)), ssl_context=_ssl.create_default_context())
            else:
                m = imaplib.IMAP4(c["imap_host"], int(c.get("imap_port", 143)))
            m.login(c["user"], self._password())
        except (imaplib.IMAP4.error, OSError) as e:
            raise MailError(t("메일 서버에 연결하지 못함: {error}", error=e))
        self._imap = m
        return m

    def _select(self, folder: Optional[str]):
        m = self._connect()
        name = folder or "INBOX"
        if name in ("받은편지함", "inbox", "Inbox"):
            name = "INBOX"
        if self._folder != name:
            typ, _ = m.select(_imap_quote_folder(name) if name != "INBOX" else "INBOX")
            if typ != "OK":
                raise MailError(t("메일 폴더가 없음: {name}", name=name))
            self._folder = name
        return m

    def close(self):
        if self._imap is not None:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
            self._folder = None

    # ------------------------------------------------------------ 받기
    def _fetch(self, uid: str):
        m = self._select(self._folder)
        typ, data = m.uid("FETCH", uid, "(BODY.PEEK[] FLAGS)")
        if typ != "OK" or not data or data[0] is None:
            raise MailError(t("메일을 찾지 못함(지워졌거나 옮겨짐)"))
        raw = next((d[1] for d in data if isinstance(d, tuple)), b"")
        flags = b" ".join(d[0] for d in data if isinstance(d, tuple))
        return email.message_from_bytes(raw), (b"\\Seen" not in flags)

    @staticmethod
    def _atts(msg) -> List[tuple]:
        out = []
        for part in msg.walk():
            fn = part.get_filename()
            if fn:
                out.append((_dec(fn), part))
        return out

    def find(self, crit: dict) -> List[dict]:
        m = self._select(crit.get("folder"))
        q = ["ALL"]
        if crit.get("unread"):
            q = ["UNSEEN"]
        if crit.get("days"):
            since = time.strftime("%d-%b-%Y", time.localtime(time.time() - float(crit["days"]) * 86400))
            q += ["SINCE", since]
        typ, data = m.uid("SEARCH", None, *q)
        if typ != "OK":
            raise MailError(t("메일 찾기 실패"))
        uids = (data[0] or b"").split()[::-1]                # 최근 것부터
        out = []
        for uid in uids[:500]:
            msg, unread = self._fetch(uid.decode())
            d = {"id": uid.decode(), "from": _dec(msg.get("From")), "subject": _dec(msg.get("Subject")),
                 "date": "", "unread": unread, "attachments": [n for n, _ in self._atts(msg)]}
            try:
                d["date"] = email.utils.parsedate_to_datetime(msg.get("Date")).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                d["date"] = str(msg.get("Date") or "")
            if match(d, crit):
                out.append(d)
            if len(out) >= int(crit.get("max", 50)):
                break
        if crit.get("unread"):                                # 찾기만으로 읽음이 되지 않게(PEEK 사용) 그대로 둠
            pass
        return out

    def read(self, mail_id: str) -> str:
        msg, _ = self._fetch(mail_id)
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                raw = part.get_payload(decode=True) or b""
                return raw.decode(part.get_content_charset() or "utf-8", "replace").strip()
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html).strip()
        return ""

    def attachments(self, mail_id: str, pattern: str = "*") -> List[tuple]:
        msg, _ = self._fetch(mail_id)
        out = []
        for name, part in self._atts(msg):
            if fnmatch.fnmatch(name.lower(), (pattern or "*").lower()):
                data = part.get_payload(decode=True) or b""

                def save(path, data=data):
                    with open(path, "wb") as fh:
                        fh.write(data)
                out.append((name, save))
        return out

    def mark_read(self, mail_id: str) -> None:
        m = self._select(self._folder)
        m.uid("STORE", mail_id, "+FLAGS", "(\\Seen)")

    def move(self, mail_id: str, folder: str) -> None:
        m = self._select(self._folder)
        typ, _ = m.uid("COPY", mail_id, _imap_quote_folder(folder))
        if typ != "OK":
            raise MailError(t("메일 폴더가 없음: {name}", name=folder))
        m.uid("STORE", mail_id, "+FLAGS", "(\\Deleted)")
        m.expunge()

    # ------------------------------------------------------------ 보내기
    def send(self, msg: dict, now: bool) -> str:
        c = self._cfg()
        em = EmailMessage()
        em["From"] = c.get("from") or c["user"]
        em["To"] = msg.get("to", "")
        if msg.get("cc"):
            em["Cc"] = msg["cc"]
        em["Subject"] = msg.get("subject", "")
        em["Date"] = email.utils.formatdate(localtime=True)
        em.set_content(msg.get("body", ""))
        for p in msg.get("attachments") or []:
            with open(p, "rb") as fh:
                em.add_attachment(fh.read(), maintype="application", subtype="octet-stream",
                                  filename=os.path.basename(p))
        if not now:                                           # 임시 보관함에 넣기(IMAP APPEND)
            m = self._connect()
            box = c.get("drafts") or "Drafts"
            typ, _ = m.append(_imap_quote_folder(box), "(\\Draft)", imaplib.Time2Internaldate(time.time()), em.as_bytes())
            if typ != "OK":
                raise MailError(t("임시 보관함 '{name}' 에 넣지 못함(설정의 임시 보관함 이름을 확인)", name=box))
            return "draft"
        try:
            if c.get("ssl", True):
                s = smtplib.SMTP_SSL(c["smtp_host"], int(c.get("smtp_port", 465)), context=_ssl.create_default_context())
            else:
                s = smtplib.SMTP(c["smtp_host"], int(c.get("smtp_port", 25)))
                if c.get("starttls"):
                    s.starttls(context=_ssl.create_default_context())
            with s:
                s.login(c["user"], self._password())
                s.send_message(em)
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(t("메일을 보내지 못함: {error}", error=e))
        return "sent"
