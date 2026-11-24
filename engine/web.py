"""웹 요소 스텝 실행부(2026-11-16).

좌표·그림 대신 웹 페이지 요소(글자·CSS·역할)로 브라우저를 다룬다.
실제 브라우저는 에고라이트(`ego-browser nodejs`)에 맡긴다 — 사용자가 로그인해 둔 세션을 그대로 쓰고,
매크로 프로그램이 Claude 없이 혼자 불러도 돈다(11-16 시험).

선택자(에고라이트 문법): `text=로그인`(글자 일부·대소문자 무시), `text="정확히"`, `loc=role:button[name='검색']`,
`loc=css:#id`, `loc=href:/path`, `xpath=...`, 그냥 CSS(`input[name=q]`). 하나만 맞아야 한다(여러 개면 `>> nth=0`).

안전: 비밀번호·카드 번호 칸에는 입력하지 않는다(입력 전에 칸 종류를 확인해 막음).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional
from .i18n import K, current, t

ACTIONS = ("goto", "click", "fill", "press", "wait", "read", "exists", "screenshot", "select", "url", "elements",
           "table", "download", "script", "upload", "close")
DEFAULT_SPACE = "macro-web"
DEFAULT_PAGE = "p1"
MARK = "@@MACRO_WEB@@"
NOWIN = 0x08000000

# 페이지 안(JS)에서 만들어 돌려주는 한국어 글 조각 → 영어 모드에서 바꿔 끼움(웹메일 JS 조각 포함)
JS_TEXTS = (
    K("막음: 비밀번호·카드 칸에는 입력하지 않음 ("),
    K("글자 읽기는 CSS·xpath·text= 선택자만 됨(loc=role·@ref 는 안 됨)"),
    K("요소가 안 보임: "),
    K("표가 안 보임: "),
    K("링크가 안 보임: "),
    K("받을 주소가 없음"),
    K("받기 실패 "),
    K("  (위치 기준: 페이지가 바뀌면 틀릴 수 있음)"),
    K("(선택자 못 만듦)"),
    K("(첨부)"),
    K("본문을 찾지 못함(화면 구조가 바뀌었을 수 있음)"),
    K("받는 사람 칸을 찾지 못함(화면 구조가 바뀌었을 수 있음)"),
    K("단추를 찾지 못함: "),
)


def localize_js(v):
    """JS 가 돌려준 값 안의 한국어 글 조각을 현재 언어로. 표 줄의 열쇠('행'·'row')는 그대로 둔다(매크로 동작이 언어에 따라 달라지면 안 됨)."""
    if current() == "ko":
        return v
    if isinstance(v, str):
        for frag in JS_TEXTS:
            if frag in v:
                v = v.replace(frag, t(frag))
        return v
    if isinstance(v, list):
        return [localize_js(x) for x in v]
    if isinstance(v, dict):
        return {k: localize_js(x) for k, x in v.items()}
    return v


# 페이지 안에서 칸 종류 확인(비밀번호·카드 칸이면 입력 막음)
_JS = r"""
const P = __PARAMS__;
const out = (o) => console.log("__MARK__" + JSON.stringify(o));
try {
  const task = await taskSpace(P.space);
  let page = null;
  const pages = await task.pages();
  page = pages.find((p) => p.label === P.page) || null;
  if (!page) page = pages.length && P.page === "p1" ? pages[0] : await task.newPage();
  const t = P.timeout;
  const a = P.action;
  let value = null;
  if (a === "close") {               // 이 매크로가 연 페이지 닫기(사람이 연 탭은 건드리지 않음)
    await page.close();
    value = true;
  } else if (a === "goto") {
    await page.goto(P.url, { timeout: t });
    value = await page.url();
  } else if (a === "click") {
    await page.click(P.selector, { timeout: t, label: P.label || "macro click" });
  } else if (a === "fill" || a === "select") {
    await page.focus(P.selector);
    const kind = await page.evaluate(() => {
      const e = document.activeElement;
      if (!e) return "";
      return [(e.type || "").toLowerCase(), (e.autocomplete || "").toLowerCase(), (e.name || "").toLowerCase()].join("|");
    });
    const bad = /(^|\|)password(\||$)|cc-|card|cvc|cvv|current-password|new-password/.test(kind);
    if (bad) { out({ ok: false, error: "막음: 비밀번호·카드 칸에는 입력하지 않음 (" + kind + ")" }); process.exit(0); }
    if (a === "fill") await page.fill(P.selector, P.text, { clearFirst: true, timeout: t });
    else await page.selectOption(P.selector, P.text);
  } else if (a === "press") {
    if (P.selector) await page.press(P.selector, P.text); else await page.keyboard.press(P.text);
  } else if (a === "wait") {
    await page.waitForSelector(P.selector, { timeout: t, state: P.state || "visible" });
  } else if (a === "exists") {
    try { await page.waitForSelector(P.selector, { timeout: Math.max(1, t), state: P.state || "visible" }); value = true; }
    catch (e) { value = false; }
  } else if (a === "read") {
    // CSS(그냥·css=·loc=css:)·xpath= 는 페이지 안에서 직접 찾아 글자(입력칸이면 값)를 읽는다. 시간 안에 생길 때까지 다시 봄
    const deadline = Date.now() + t;
    for (;;) {
      value = await page.evaluate(({ sel }) => {
        let e = null;
        let nth = 0;
        const m = sel.match(/\s*>>\s*nth=(-?\d+)\s*$/);
        if (m) { nth = parseInt(m[1], 10); sel = sel.slice(0, m.index); }
        const at = (list) => { list = [...list]; return list.length ? list[nth < 0 ? list.length + nth : nth] || null : null; };
        if (sel.startsWith("xpath=")) {
          const r = document.evaluate(sel.slice(6), document, null, 7, null);
          const arr = []; for (let i = 0; i < r.snapshotLength; i++) arr.push(r.snapshotItem(i));
          e = at(arr);
        } else if (sel.startsWith("text=")) {
          let t = sel.slice(5); const exact = /^".*"$/.test(t); t = t.replace(/^"|"$/g, "");
          const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
          const hit = (x) => exact ? norm(x.innerText) === t : norm(x.innerText).toLowerCase().includes(t.toLowerCase());
          const all = [...document.querySelectorAll("body *")].filter((x) => x.offsetParent !== null && hit(x));
          e = at(all.filter((x) => ![...x.children].some((c) => hit(c))));
        } else if (!/^(loc=role:|loc=href:|@|ref=)/.test(sel)) {
          e = at(document.querySelectorAll(sel.replace(/^css=/, "").replace(/^loc=css:/, "")));
        } else return "__UNSUPPORTED__";
        if (!e) return null;
        const isField = (e.tagName === "INPUT" || e.tagName === "TEXTAREA" || e.tagName === "SELECT");
        return isField ? String(e.value) : (e.innerText || e.textContent || "").trim();
      }, { sel: P.selector });
      if (value !== null || Date.now() > deadline) break;
      await page.waitForTimeout(300);
    }
    if (value === "__UNSUPPORTED__") { out({ ok: false, error: "글자 읽기는 CSS·xpath·text= 선택자만 됨(loc=role·@ref 는 안 됨)" }); process.exit(0); }
    if (value === null) { out({ ok: false, error: "요소가 안 보임: " + P.selector }); process.exit(0); }
  } else if (a === "table") {
    // 표 읽기: 선택자(CSS·xpath=)로 표를 찾아 줄마다 {제목: 글자, "1": 글자, ...}. 제목은 thead 또는 첫 줄의 th
    const deadline = Date.now() + t;
    for (;;) {
      value = await page.evaluate(({ sel }) => {
        let tb = null;
        if (sel.startsWith("xpath=")) {
          tb = document.evaluate(sel.slice(6), document, null, 9, null).singleNodeValue;
        } else {
          let nth = 0;
          const m = sel.match(/\s*>>\s*nth=(-?\d+)\s*$/);
          if (m) { nth = parseInt(m[1], 10); sel = sel.slice(0, m.index); }
          const list = [...document.querySelectorAll((sel || "table").replace(/^css=/, ""))];
          tb = list.length ? list[nth < 0 ? list.length + nth : nth] : null;
        }
        if (!tb) return null;
        if (tb.tagName !== "TABLE") tb = tb.closest("table") || tb.querySelector("table") || tb;
        const txt = (c) => (c.innerText || c.textContent || "").replace(/\s+/g, " ").trim();
        const rows = [...tb.querySelectorAll("tr")];
        let head = [];
        const hr = tb.querySelector("thead tr") || (rows.length && rows[0].querySelector("th") ? rows[0] : null);
        if (hr) head = [...hr.children].map(txt);
        const out = [];
        let n = 0;
        for (const r of rows) {
          if (r === hr) continue;
          const cells = [...r.children].filter((c) => c.tagName === "TD" || c.tagName === "TH");
          if (!cells.length) continue;
          n += 1;
          const o = { "행": n, "row": n };
          cells.forEach((c, i) => { o[String(i + 1)] = txt(c); if (head[i]) o[head[i]] = txt(c); });
          out.push(o);
        }
        return out;
      }, { sel: P.selector });
      if (value !== null || Date.now() > deadline) break;
      await page.waitForTimeout(300);
    }
    if (value === null) { out({ ok: false, error: "표가 안 보임: " + (P.selector || "table") }); process.exit(0); }
  } else if (a === "script") {
    // 웹메일 같은 묶음 동작용(사용자 단계로는 안 보임): 정해 둔 글 조각을 페이지 안에서 실행하고 결과를 돌려줌
    const fn = new Function("args", "return (async () => {" + P.text + "})();");
    value = await page.evaluate(fn, P.args || {});
    if (value && value.__error) { out({ ok: false, error: value.__error }); process.exit(0); }
    value = { url: await page.url(), result: value };
  } else if (a === "upload") {
    // 파일 칸(input type=file)에 파일 넣기(웹메일 첨부)
    await page.setInputFiles(P.selector, P.files || []);
  } else if (a === "download") {
    // 내려받기: 링크(선택자) 또는 주소를 로그인된 페이지 안에서 받아 온다(쿠키 그대로). 내용은 base64 로 돌려줌
    value = await page.evaluate(async ({ sel, url }) => {
      let href = url;
      if (sel) {
        const e = document.querySelector(sel.replace(/^css=/, ""));
        if (!e) return { error: "링크가 안 보임: " + sel };
        href = e.href || e.getAttribute("href") || e.src || "";
      }
      if (!href) return { error: "받을 주소가 없음" };
      const r = await fetch(href, { credentials: "include" });
      if (!r.ok) return { error: "받기 실패 " + r.status };
      const cd = r.headers.get("content-disposition") || "";
      let name = "";
      const m = cd.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
      if (m) name = decodeURIComponent(m[1] || m[2]);
      if (!name) name = decodeURIComponent((new URL(r.url, location.href).pathname.split("/").pop() || "download"));
      const buf = new Uint8Array(await r.arrayBuffer());
      let s = "";
      for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      return { name, size: buf.length, data: btoa(s), type: r.headers.get("content-type") || "" };
    }, { sel: P.selector, url: P.url });
    if (value && value.error) { out({ ok: false, error: value.error }); process.exit(0); }
  } else if (a === "screenshot") {
    value = await page.screenshot({ path: P.path });
  } else if (a === "url") {
    value = await page.url();
  } else if (a === "elements") {
    try { await page.waitForLoadState("load", { timeout: 5000 }); } catch (e) {}   // 막 이동한 페이지면 다 뜰 때까지
    // AI 용 '페이지 보기': 누르거나 입력할 수 있는 요소만 한 줄씩 + 바로 쓸 수 있는(하나만 맞는) 선택자
    value = await page.evaluate(({ filter, full, limit }) => {
      const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/([^\w-])/g, "\\$1");
      const uniq = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
      const vis = (e) => {
        const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) return false;
        const st = getComputedStyle(e);
        if (st.visibility === "hidden" || st.display === "none" || +st.opacity === 0) return false;
        if (!full && (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth)) return false;
        return true;
      };
      const label = (e) => {
        const t = (e.getAttribute("aria-label") || e.innerText || e.value || e.placeholder || e.title || e.alt || "").replace(/\s+/g, " ").trim();
        return t.slice(0, 60);
      };
      const cssPath = (e) => {
        const parts = [];
        let n = e;
        while (n && n.nodeType === 1 && parts.length < 5) {
          let p = n.tagName.toLowerCase();
          if (n.id && uniq("#" + esc(n.id))) { parts.unshift("#" + esc(n.id)); break; }
          const par = n.parentElement;
          if (par) {
            const same = [...par.children].filter((c) => c.tagName === n.tagName);
            if (same.length > 1) p += ":nth-of-type(" + (same.indexOf(n) + 1) + ")";
          }
          parts.unshift(p);
          const s = parts.join(" > ");
          if (uniq(s)) return s;
          n = par;
        }
        const s = parts.join(" > ");
        return uniq(s) ? s : null;
      };
      const pick = (e) => {
        const tag = e.tagName.toLowerCase();
        const field = tag === "input" || tag === "textarea" || tag === "select";
        const attrSel = () => {
          for (const at of ["name", "data-testid", "aria-label", "placeholder"]) {
            const v = e.getAttribute(at);
            if (v) { const s = `${tag}[${at}="${v.replace(/"/g, '\\"')}"]`; if (uniq(s)) return s; }
          }
          return null;
        };
        if (field) { const s = attrSel(); if (s) return s; }
        if (e.id && uniq("#" + esc(e.id)) && !/\d{3,}|^mw[A-Za-z0-9]{2,4}$/.test(e.id)) return "#" + esc(e.id);
        { const s = attrSel(); if (s) return s; }
        { const v = e.getAttribute("title"); if (v) { const s = `${tag}[title="${v.replace(/"/g, '\\"')}"]`; if (uniq(s)) return s; } }
        const t = label(e);
        if (t && tag !== "input" && tag !== "textarea" && tag !== "select") {
          const same = [...document.querySelectorAll("a,button,[role=button],[role=link],[role=tab],[role=menuitem],summary,label")]
            .filter((x) => vis(x) && label(x) === t);
          if (same.length === 1) return `text="${t.replace(/"/g, '\\"')}"`;
        }
        const p = cssPath(e);
        return p ? p + "  (위치 기준: 페이지가 바뀌면 틀릴 수 있음)" : null;
      };
      const nodes = [...document.querySelectorAll("a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=combobox],[contenteditable=true],summary,[onclick]")];
      const f = (filter || "").toLowerCase();
      const out = [];
      const seen = new Set();
      for (const e of nodes) {
        if (!vis(e) || seen.has(e)) continue;
        seen.add(e);
        const tag = e.tagName.toLowerCase();
        const kind = tag === "input" ? "input:" + (e.type || "text") : (e.getAttribute("role") || tag);
        const t = label(e);
        if (f && !(t.toLowerCase().includes(f) || kind.includes(f))) continue;
        out.push(`${kind} "${t}" → ${pick(e) || "(선택자 못 만듦)"}`);
        if (out.length >= limit) break;
      }
      return { title: document.title, count: out.length, items: out };
    }, { filter: P.filter || "", full: !!P.full, limit: P.limit || 60 });
  }
  // 닫은 페이지에 주소를 물으면 'page was closed' 오류(11-19 실환경 시험) → 닫기는 주소 없이
  out({ ok: true, value, url: a === "close" ? null : await page.url(), page: page.label, space: task.spaceId });
} catch (e) {
  out({ ok: false, error: String((e && (e.code ? e.code + " " : "") + e.message) || e) });
}
"""


class WebError(Exception):
    pass


def find_cli() -> Optional[str]:
    p = shutil.which("ego-browser")
    if p:
        return p
    cand = os.path.expanduser("~/.local/share/ego/active_version_dir/ego-browser")
    for ext in ("", ".exe", ".cmd"):
        if os.path.exists(cand + ext):
            return cand + ext
    return None


class EgoWeb:
    """에고라이트 CLI 로 한 동작씩 실행. 동작마다 새 Node 프로세스(작업 공간·탭은 유지됨)."""

    def __init__(self, space: str = DEFAULT_SPACE, cli: Optional[str] = None, workdir: Optional[str] = None):
        self.space = space
        self.cli = cli or find_cli()
        self.workdir = workdir or os.path.join(tempfile.gettempdir(), "macro_web")
        self._proc: Optional[subprocess.Popen] = None

    def run(self, action: str, *, selector: str = "", url: str = "", text: str = "", page: str = DEFAULT_PAGE,
            timeout_ms: int = 5000, state: str = "visible", path: str = "", label: str = "", args=None, files=None,
            should_stop=None, filter: str = "", limit: int = 60, full: bool = False) -> Dict[str, Any]:
        if action not in ACTIONS:
            raise WebError(t("모르는 웹 동작 '{action}'", action=action))
        if not self.cli:
            raise WebError(t("웹 자동화 브라우저를 찾지 못함 — 설치 필요(설정 → 환경 점검)"))
        os.makedirs(self.workdir, exist_ok=True)
        params = {"space": self.space, "page": page, "action": action, "selector": selector, "url": url,
                  "text": text, "timeout": int(timeout_ms), "state": state, "path": path.replace("\\", "/"),
                  "label": label, "filter": filter, "limit": int(limit), "full": bool(full),
                  "args": args or {}, "files": [f.replace("\\", "/") for f in (files or [])]}
        js = _JS.replace("__PARAMS__", json.dumps(params, ensure_ascii=False)).replace("__MARK__", MARK)
        fp = os.path.join(self.workdir, f"step_{os.getpid()}_{int(time.time() * 1000)}.mjs")
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(js)
        url_ = "file:///" + fp.replace("\\", "/")
        limit = max(30, timeout_ms / 1000 + 25)
        try:
            self._proc = subprocess.Popen([self.cli, "nodejs", "-e", f"await import('{url_}')"],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=NOWIN if os.name == "nt" else 0)
            t0 = time.time()
            while self._proc.poll() is None:          # 비상 정지면 바로 끊음
                if should_stop is not None and should_stop():
                    self.cancel()
                    raise WebError(t("정지 요청"))
                if time.time() - t0 > limit:
                    self.cancel()
                    raise WebError(t("웹 자동화 브라우저가 응답하지 않음(시간 초과)"))
                time.sleep(0.05)
            out, err = self._proc.communicate()
        finally:
            self._proc = None
            try:
                os.remove(fp)
            except OSError:
                pass
        text_out = out.decode("utf-8", "replace") + "\n" + err.decode("utf-8", "replace")   # console.log 가 stderr 로 올 때도 있음
        for line in text_out.splitlines():
            if line.startswith(MARK):
                return localize_js(json.loads(line[len(MARK):]))
        raise WebError(t("웹 자동화 브라우저 결과를 못 읽음: {detail}",
                         detail=(err.decode("utf-8", "replace") or text_out)[-300:]))

    def cancel(self):
        """비상 정지 때 돌고 있는 에고라이트 프로세스를 끊는다(브라우저 자체는 그대로)."""
        p = self._proc
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
