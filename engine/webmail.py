"""메일 '나': 웹메일(네이버·다음·네이트·지메일)을 브라우저로 다룬다. 기존 웹 단계 엔진(에고라이트) 위에 얹는다.

- 서비스별 화면 정보(주소·선택자)는 engine/webmail_services.json 에 따로 둔다. 화면이 바뀌면 그 묶음만 고친다.
- 로그인은 사람이 그 브라우저에서 미리 해 둔 것을 쓴다. 로그인·2단계 인증·보안문자 화면이 나오면 멈춘다(실패).
  매크로가 아이디·비밀번호를 넣지 않는다.
- 보내기 기본은 임시 보관함 저장(send_now=true 일 때만 보내기 단추).
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Dict, List, Optional

from .i18n import t
from .mail import MailError, match

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICES_FILE = os.path.join(HERE, "webmail_services.json")
LOGIN_WORDS = ("로그인", "Sign in", "보안문자", "captcha", "2단계 인증", "본인 확인", "Verify it")

# 목록 읽기: 서비스 선택자로 줄마다 {id, from, subject, date, unread, attachments, href}
JS_LIST = r"""
const S = args.sel;
const pick = (root, sel) => { if (!sel) return null; for (const s of sel.split(",")) { try { const e = root.querySelector(s.trim()); if (e) return e; } catch (e) {} } return null; };
const txt = (e) => e ? (e.getAttribute("email") ? (e.innerText || "").trim() + " <" + e.getAttribute("email") + ">" : (e.getAttribute("title") || e.innerText || "").replace(/\s+/g, " ").trim()) : "";
let rows = [];
for (const s of S.row.split(",")) { try { rows = rows.concat([...document.querySelectorAll(s.trim())]); } catch (e) {} if (rows.length) break; }
const out = [];
rows.forEach((r, i) => {
  const a = S.link ? pick(r, S.link) : null;
  const href = a && a.href ? a.href : "";
  const id = (S.id_attr && (r.querySelector("[" + S.id_attr + "]") || r).getAttribute(S.id_attr)) || href || r.id || ("row" + i);
  out.push({ id, href, from: txt(pick(r, S.from)), subject: txt(pick(r, S.subject)), date: txt(pick(r, S.date)),
             unread: !!(r.matches(S.unread) || pick(r, S.unread)), attachments: pick(r, S.attach) ? ["(첨부)"] : [] });
});
return out;
"""

# 본문 읽기(메일을 연 화면에서)
JS_BODY = r"""
for (const s of args.sel.body.split(",")) {
  let e = null; try { e = document.querySelector(s.trim()); } catch (x) {}
  if (!e) continue;
  if (e.tagName === "IFRAME") { try { return e.contentDocument.body.innerText.trim(); } catch (x) { continue; } }
  return (e.innerText || "").trim();
}
return { __error: "본문을 찾지 못함(화면 구조가 바뀌었을 수 있음)" };
"""

# 첨부 받기(메일을 연 화면에서, 로그인된 쿠키로 fetch)
JS_ATTACH = r"""
const links = [];
for (const s of args.sel.link.split(",")) { try { links.push(...document.querySelectorAll(s.trim())); } catch (e) {} }
const seen = new Set(); const out = [];
const re = args.pattern ? new RegExp("^" + args.pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$", "i") : null;
for (const a of links) {
  const href = a.href; if (!href || seen.has(href)) continue; seen.add(href);
  const r = await fetch(href, { credentials: "include" }); if (!r.ok) continue;
  const cd = r.headers.get("content-disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const name = m ? decodeURIComponent(m[1] || m[2]) : ((a.innerText || a.getAttribute("download") || "attachment").trim());
  if (re && !re.test(name)) continue;
  const buf = new Uint8Array(await r.arrayBuffer()); let s = "";
  for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  out.push({ name, data: btoa(s) });
}
return out;
"""

# 쓰기 화면에 받는 사람·제목·본문 넣고 임시 저장 또는 보내기
JS_COMPOSE = r"""
const S = args.sel;
const pick = (sel) => { for (const s of sel.split(",")) { try { const e = document.querySelector(s.trim()); if (e) return e; } catch (e) {} } return null; };
const put = (e, v) => { if (!e) return false; e.focus(); if ("value" in e && e.tagName !== "DIV") { e.value = v; } else { e.innerText = v; }
  e.dispatchEvent(new Event("input", { bubbles: true })); e.dispatchEvent(new Event("change", { bubbles: true })); return true; };
if (!put(pick(S.to), args.to)) return { __error: "받는 사람 칸을 찾지 못함(화면 구조가 바뀌었을 수 있음)" };
put(pick(S.subject), args.subject);
const b = pick(S.body);
if (b && b.tagName === "IFRAME") { try { b.contentDocument.body.innerText = args.body; } catch (e) {} } else { put(b, args.body); }
return "filled";
"""

JS_CLICK = r"""
for (const s of args.sel.split(",")) { let e = null; try { e = document.querySelector(s.trim()); } catch (x) {} if (e) { e.click(); return "clicked"; } }
return { __error: "단추를 찾지 못함: " + args.sel };
"""


def load_services() -> Dict[str, dict]:
    with open(SERVICES_FILE, encoding="utf-8") as fh:
        return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}


class WebMail:
    def __init__(self, runner, service: Optional[str] = None):
        self.runner = runner
        self.service = service
        self._cache: Dict[str, dict] = {}

    # ------------------------------------------------------------ 도우미
    def _svc(self) -> dict:
        svc = self.service or getattr(self.runner, "_mail_service", None)
        packs = load_services()
        if svc not in packs:
            raise MailError(t("모르는 웹메일 '{name}'(naver / daum / nate / gmail)", name=svc))
        return packs[svc]

    def _web(self, action: str, **kw) -> dict:
        r = self.runner._web().run(action, page="mail", timeout_ms=int(kw.pop("timeout_ms", 15000)),
                                   should_stop=self.runner._stop.is_set, **kw)
        if not r.get("ok"):
            raise MailError(str(r.get("error")))
        return r

    def _check_login(self, url: str, text: str = "") -> None:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url or "").lower()
        if any(h in host for h in self._svc().get("login_hosts", [])):
            raise MailError(t("로그인이 필요함 — 그 브라우저에서 {name} 에 직접 로그인한 뒤 다시 실행하세요", name=self._svc()["name"]))

    def _script(self, js: str, args: dict) -> object:
        r = self._web("script", text=js, args=args)
        v = r.get("value") or {}
        self._check_login(v.get("url", ""))
        return v.get("result")

    def _open(self, url: str) -> None:
        r = self._web("goto", url=url)
        self._check_login(r.get("value") or r.get("url") or "")

    # ------------------------------------------------------------ 동작
    def find(self, crit: dict) -> List[dict]:
        s = self._svc()
        self._open(s["inbox_url"] if not crit.get("folder") else s["inbox_url"])
        rows = self._script(JS_LIST, {"sel": s["list"]}) or []
        out = []
        for d in rows:
            if match(d, crit):
                self._cache[d["id"]] = d
                out.append(d)
            if len(out) >= int(crit.get("max", 50)):
                break
        return out

    def _open_mail(self, mail_id: str) -> None:
        d = self._cache.get(mail_id) or {}
        href = d.get("href") or (mail_id if str(mail_id).startswith("http") else "")
        if not href:
            raise MailError(t("이 메일을 다시 열 주소가 없음(같은 실행에서 '찾기' 결과로 쓰세요)"))
        self._open(href)

    def read(self, mail_id: str) -> str:
        self._open_mail(mail_id)
        return str(self._script(JS_BODY, {"sel": self._svc()["read"]}) or "")

    def attachments(self, mail_id: str, pattern: str = "*") -> List[tuple]:
        self._open_mail(mail_id)
        got = self._script(JS_ATTACH, {"sel": self._svc()["attachments"], "pattern": pattern or ""}) or []

        def saver(data):
            def save(path):
                with open(path, "wb") as fh:
                    fh.write(base64.b64decode(data))
            return save
        return [(g["name"], saver(g["data"])) for g in got]

    def mark_read(self, mail_id: str) -> None:
        self._open_mail(mail_id)                 # 웹메일은 열면 읽음이 된다

    def move(self, mail_id: str, folder: str) -> None:
        raise MailError(t("웹메일에서는 '폴더 옮기기'를 아직 지원하지 않음 — 웹 단계로 직접 짜 주세요"))

    def send(self, msg: dict, now: bool) -> str:
        s = self._svc()
        self._open(s["compose_url"])
        self._script(JS_COMPOSE, {"sel": s["compose"], "to": msg.get("to", ""), "subject": msg.get("subject", ""),
                                  "body": msg.get("body", "")})
        if msg.get("attachments"):
            self._web("upload", selector=s["compose"]["file"].split(",")[0].strip(), files=list(msg["attachments"]))
        self._script(JS_CLICK, {"sel": s["compose"]["send" if now else "draft"]})
        return "sent" if now else "draft"
