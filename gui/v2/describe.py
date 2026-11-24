"""
스텝·대상·조건을 사람이 읽는 한 줄로 (Qt 없음). 스텝 트리·실행 기록 표시에 쓴다.
"""
from __future__ import annotations

from typing import Any

from .i18n import tr

STEP_NAMES = {
    "click": "클릭", "move": "마우스 이동", "drag": "드래그", "scroll": "휠 굴리기", "mouse_down": "마우스 누르기",
    "mouse_up": "마우스 떼기", "key": "키 입력", "type_text": "글자 입력", "wait": "기다리기",
    "delay": "잠깐 쉬기", "remember": "좌표 기억", "if": "만약", "repeat": "반복", "group": "묶음", "for_each": "찾은 것마다",
    "launch": "프로그램 실행", "menu": "메뉴 고르기", "close_window": "창 닫기", "wait_window": "창 기다리기", "snapshot": "화면 저장",
    "break": "반복 끝내기", "continue": "다음 회차로", "call": "매크로 호출", "set_result": "결과값 정하기",
    "set": "변수 정하기", "return": "매크로 끝내기", "stop": "실행 정지", "comment": "메모",
    "web": "웹 요소", "read_number": "숫자 읽기",
    "text": "글자 만들기", "date": "날짜", "calc": "계산", "clipboard": "클립보드", "file": "파일·폴더", "each": "목록마다", "ask": "사람에게 묻기", "notify": "알림 보내기", "pdf": "PDF 읽기", "mail": "메일", "list": "목록", "memory": "메모리 값 읽기",
    "excel": "엑셀", "word": "워드", "hwp": "한글 문서",
}
# 오피스 스텝 동작 이름
OFFICE_ACTIONS = {
    "open": "파일 열기", "read": "읽기", "write": "쓰기", "last_row": "마지막 행 번호", "run_macro": "엑셀 매크로 실행",
    "save": "저장", "save_as": "다른 이름으로 저장(PDF 가능)", "close": "닫기",
    "replace": "글자 바꾸기", "fill_bookmark": "책갈피 채우기", "fill_field": "누름틀 채우기", "read_field": "누름틀 읽기",
    "print": "인쇄(PDF 파일 가능)", "new": "새 파일 만들기",
}
# 웹 요소 스텝의 동작 이름
WEB_ACTIONS = {"close": "페이지 닫기", "goto": "주소 열기", "click": "누르기", "fill": "입력하기", "select": "목록에서 고르기",
               "press": "키 누르기", "wait": "나타날 때까지 기다리기", "read": "글자 읽기", "url": "지금 주소 읽기",
               "screenshot": "페이지 사진", "table": "표 읽기", "download": "파일 내려받기"}
# 편집기 '스텝 추가' 메뉴 순서
STEP_ORDER = ["click", "move", "drag", "scroll", "menu", "mouse_down", "mouse_up", "key", "type_text",
              "wait", "delay", "if", "repeat", "for_each", "group", "break", "continue",
              "remember", "set", "call", "set_result", "return", "stop", "comment",
              "launch", "close_window", "wait_window", "snapshot", "web", "excel", "hwp", "word"]

# 새 화면(v3) 편집기 순서: 사무 기능 단계를 '변수 정하기' 뒤에(옛 화면 STEP_ORDER 는 그대로)
STEP_ORDER_V3 = (STEP_ORDER[:STEP_ORDER.index("set") + 1] + ["text", "date", "calc", "clipboard", "file"]
                 + STEP_ORDER[STEP_ORDER.index("set") + 1:])
STEP_ORDER_V3.insert(STEP_ORDER_V3.index("for_each"), "each")
STEP_ORDER_V3.insert(STEP_ORDER_V3.index("text"), "list")
STEP_ORDER_V3.append("pdf")
LIST_ACTIONS = {"add": "하나 더하기", "sort": "정렬", "unique": "같은 것 빼기", "clear": "비우기", "count": "개수 세기"}
STEP_ORDER_V3.append("mail")
MAIL_ACTIONS = {"find": "메일 찾기", "read": "본문 읽기", "save_attachments": "첨부 저장", "mark_read": "읽음 표시",
                "move": "다른 폴더로 옮기기", "send": "메일 쓰기·보내기"}
MAIL_VIAS = {"outlook": "아웃룩(이 컴퓨터)", "web": "웹메일(브라우저)", "server": "메일 서버 직접(IMAP·SMTP)"}
MAIL_SERVICES = {"naver": "네이버", "daum": "다음", "nate": "네이트", "gmail": "구글(지메일)"}
STEP_ORDER_V3[STEP_ORDER_V3.index("stop") + 1:STEP_ORDER_V3.index("stop") + 1] = ["ask", "notify"]
# 사람에게 묻기 종류
ASK_KINDS = {"input": "글 입력받기", "confirm": "예/아니 묻기", "choose": "목록에서 고르기", "file": "파일 고르기",
             "folder": "폴더 고르기"}
NOTIFY_CHANNELS = {"toast": "윈도우 알림", "sound": "소리", "webhook": "메신저(웹훅)"}
# 목록마다: 무엇을 도는지
EACH_SOURCES = {"list": "목록 변수", "rows": "엑셀 표의 줄", "files": "폴더 안 파일", "lines": "글의 줄", "range": "숫자 범위"}
# 파일·폴더 동작 이름
FILE_ACTIONS = {"copy": "복사", "move": "옮기기", "rename": "이름 바꾸기", "delete": "지우기(휴지통으로)",
                "mkdir": "폴더 만들기", "list": "폴더 안 파일 목록", "exists": "있는지 보기", "info": "파일 정보",
                "read_text": "글 파일 읽기", "write_text": "글 파일 쓰기", "zip": "압축하기", "unzip": "압축 풀기",
                "read_csv": "CSV 읽기(표로)", "write_csv": "CSV 쓰기(표에서)"}
OVERWRITE_NAMES = {"fail": "멈춤(실패로)", "skip": "건너뛰기", "number": "번호 붙여 새로 (2)", "replace": "바꾸기(원래 것은 휴지통)"}
# 클립보드 동작 이름
CLIPBOARD_ACTIONS = {"copy": "복사해서 읽기(Ctrl+C)", "read": "지금 글 읽기", "write": "글 넣기", "clear": "비우기",
                     "files": "복사한 파일 목록 읽기", "save_image": "복사한 그림 저장"}
# 글자 만들기 동작 이름
TEXT_ACTIONS = {"set": "그대로 만들기({변수} 넣기)", "replace": "바꾸기", "extract": "찾아서 뽑기(규칙)",
                "split": "나누기", "slice": "일부만 자르기", "trim": "앞뒤 빈칸 빼기", "upper": "대문자로",
                "lower": "소문자로", "length": "글자 수", "number": "숫자로 바꾸기", "join": "목록 합치기",
                "pad": "앞에 0 채우기"}

BRANCH_NAMES = {"then": "그러면", "else": "아니면", "steps": "할 일"}


def step_name(k: str) -> str:
    return tr(STEP_NAMES.get(k, k))


def office_action_name(a: str) -> str:
    return tr(OFFICE_ACTIONS.get(a, a))


def web_action_name(a: str) -> str:
    return tr(WEB_ACTIONS.get(a, a))


def branch_name(k: str) -> str:
    return tr(BRANCH_NAMES.get(k, k))


def _short(v: Any, n: int = 40) -> str:
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _xy(v) -> str:
    try:
        return f"({int(v[0])}, {int(v[1])})"
    except Exception:
        return str(v)


def target_text(t: Any) -> str:
    if t == "mouse":
        return tr("현재 마우스 위치")
    if not isinstance(t, dict):
        return "?"
    if "image" in t:
        name = str(t.get("image") or tr("(이미지 없음)")).replace("\\", "/").split("/")[-1]
        s = tr("이미지 {name}").format(name=name)
    elif "color" in t:
        c = t.get("color")
        col = tr("색{c}").format(c=tuple(c)) if isinstance(c, (list, tuple)) else tr("색")
        if "at" in t:
            s = f"{col} @ {_xy(t['at'])}"
        else:
            s = tr("{col} 영역").format(col=col)
            if "blob_depth" in t:
                s += tr(" 덩어리")
    elif "vivid" in t:
        s = tr("선명한 색 영역")
    elif "point" in t:
        s = tr("좌표 {xy}").format(xy=_xy(t["point"]))
    elif "var" in t:
        s = tr("변수 {v}").format(v=t.get("var"))
    elif "element" in t:
        e = t["element"] if isinstance(t["element"], dict) else {}
        s = tr("버튼 '{name}'").format(name=e.get("name") or e.get("id") or "?")
        if e.get("index"):
            s += f" #{e['index']}"
    else:
        s = "?"
    if t.get("offset"):
        s += f" +{_xy(t['offset'])}"
    if t.get("anchor"):
        s += tr(" (기준 {a})").format(a=t["anchor"])
    return s


_OPS = {"eq": "==", "ne": "!=", "gt": ">", "lt": "<", "ge": ">=", "le": "<="}
_TEXT_OPS = {"contains": "포함", "not_contains": "포함 안 함", "starts_with": "로 시작", "ends_with": "로 끝남",
             "matches": "규칙에 맞음"}


def cond_text(c: Any, depth: int = 0) -> str:
    if not isinstance(c, dict):
        return "?"
    if "exists" in c:
        return tr("{t} 보임").format(t=target_text(c["exists"]))
    if "gone" in c:
        s = tr("{t} 사라짐").format(t=target_text(c["gone"]))
        if c.get("for"):
            s += tr(" ({n}초 동안)").format(n=c["for"])
        return s
    if "var" in c:
        if "is_set" in c:
            return tr("변수 {v} {state}").format(v=c["var"], state=tr("있음") if c["is_set"] else tr("없음"))
        if "is_empty" in c:
            return tr("변수 {v} {state}").format(v=c["var"], state=tr("비었음") if c["is_empty"] else tr("안 비었음"))
        for op, word in _TEXT_OPS.items():
            if op in c:
                return f"{c['var']} {tr(word)} {c[op]!r}"
        for op, sym in _OPS.items():
            if op in c:
                v = c[op]
                rhs = v["var"] if isinstance(v, dict) and "var" in v else repr(v)     # 변수끼리 비교면 변수 이름
                return f"{c['var']} {sym} {rhs}"
        return tr("변수 {v}").format(v=c["var"])
    if "memory" in c:
        mc = c.get("memory") or {}
        v = mc.get("value")
        nm = v if isinstance(v, str) else (str((v or {}).get("offset", "?")))
        if mc.get("changed"):
            return tr("메모리 {n} 바뀌면").format(n=nm)
        for op, sym in _OPS.items():
            if op in mc:
                return tr("메모리 {n}").format(n=nm) + f" {sym} {mc[op]!r}"
        return tr("메모리 {n}").format(n=nm)
    if "file" in c:
        f = c.get("file") or {}
        return tr("파일 {p} {state}").format(p=f.get("path", ""), state=tr("있음") if f.get("exists", True) else tr("없음"))
    if "window_size" in c:
        ws = c.get("window_size") or [0, 0]
        return tr("창 크기 {w}x{h}").format(w=ws[0], h=ws[1])
    if "web" in c:
        w = c.get("web") or {}
        return tr("웹 요소 {s} 보임").format(s=_short(w.get("selector", "?"), 30))
    if "not" in c:
        return tr("아님({c})").format(c=cond_text(c["not"], depth + 1))
    for k, word in (("all", tr("모두")), ("any", tr("하나라도"))):
        if k in c:
            parts = [cond_text(x, depth + 1) for x in (c.get(k) or [])]
            if depth >= 1 and len(parts) > 2:
                return tr("{w}({p}, … {n}개)").format(w=word, p=parts[0], n=len(parts))
            return f"{word}({', '.join(parts)})"
    return "?"


def step_text(s: dict) -> str:
    """스텝 한 줄 설명(메모 포함)."""
    t = s.get("type", "?")
    name = step_name(t)
    if t == "click":
        if s.get("button") == "right":
            name = tr("우클릭")
        elif s.get("button") == "middle":
            name = tr("가운데 클릭")
        if s.get("count") == 2:
            name = tr("더블{name}").format(name=name)
        body = f"{name}: {target_text(s.get('target'))}"
        if s.get("verify"):
            body += tr(" (확인)")
    elif t in ("move", "mouse_down", "mouse_up"):
        body = name + (f": {target_text(s['target'])}" if s.get("target") else "")
    elif t == "drag":
        body = f"{name}: {target_text(s.get('from'))} → {target_text(s.get('to'))}"
    elif t == "scroll":
        body = tr("{name} {n}칸").format(name=name, n=s.get("amount", -3)) + (
            f" @ {target_text(s['target'])}" if s.get("target") else "")
    elif t == "key":
        body = f"{name}: {s.get('keys', '')}" + (f" ×{s['count']}" if s.get("count", 1) != 1 else "")
    elif t == "type_text":
        body = f"{name}: '{_short(s.get('text', ''), 30)}'"
    elif t == "wait":
        to = s.get("timeout", "기본")
        if to is None:
            lim = tr("무한")
        elif to == "기본":
            lim = tr("기본")
        else:
            lim = tr("{n}초").format(n=to)
        body = tr("{name}: {c} (최대 {lim})").format(name=name, c=cond_text(s.get("until")), lim=lim)
    elif t == "delay":
        body = tr("{name} {n}초").format(name=name, n=s.get("seconds", "?"))
    elif t == "remember":
        body = f"{name}: {s.get('var')} ← {target_text(s.get('what', 'mouse'))}"
    elif t == "if":
        body = tr("만약 {c}").format(c=cond_text(s.get("cond")))
        if s.get("within"):
            body += tr(" ({n}초 안에)").format(n=s["within"])
    elif t == "menu":
        body = f"{name}: {s.get('path', '')}"
    elif t == "launch":
        body = f"{name}: {s.get('target', '')}"
    elif t in ("close_window", "wait_window"):
        body = tr("{name} (최대 {n}초)").format(name=name, n=s.get("timeout", 30 if t == "close_window" else 120))
    elif t == "snapshot":
        body = f"{name}: {s.get('name', '')}"
    elif t in ("excel", "word", "hwp"):
        a = s.get("action", "?")
        body = tr("{name} {a}").format(name=name, a=office_action_name(a))
        if a in ("open", "save_as"):
            body += f": {_short(s.get('path', ''), 40)}"
        elif a in ("read", "write"):
            body += f": {s.get('sheet', '') + '!' if s.get('sheet') else ''}{s.get('cell', '')}"
            if a == "write":
                body += f" ← {s['value']['var'] if isinstance(s.get('value'), dict) else repr(_short(s.get('value'), 20))}"
        elif a in ("fill_field", "fill_bookmark", "read_field"):
            body += f": {s.get('name', '')}" + (f" ← {_short(s.get('text', ''), 20)!r}" if "text" in s else "")
        elif a == "replace":
            body += f": {_short(s.get('find', ''), 15)!r} → {_short(s.get('text', ''), 15)!r}"
        elif a == "run_macro":
            body += f": {s.get('name', '')}"
        if s.get("var") and a in ("read", "last_row", "read_field", "run_macro"):
            body += f" → {s['var']}"
        elif a == "read" and t == "word" and s.get("var"):
            body += f" → {s['var']}"
    elif t == "web":
        a = s.get("action", "?")
        what = s.get("url") if a == "goto" else s.get("selector", "")
        body = tr("웹 {a}: {w}").format(a=web_action_name(a), w=_short(what or "", 40))
        if a in ("fill", "select", "press"):
            v = s.get("text")
            body += " ← " + (tr("변수 {v}").format(v=v["var"]) if isinstance(v, dict) else repr(_short(v, 20)))
        if a in ("read", "url") and s.get("var"):
            body += f" → {s['var']}"
    elif t == "for_each":
        body = tr("찾은 것마다: {t} → {v}").format(t=target_text(s.get("target")), v=s.get("var"))
    elif t == "repeat":
        if s.get("forever"):
            body = tr("계속 반복")
        elif "times" in s:
            body = tr("{n}번 반복").format(n=s["times"])
        elif "until" in s:
            body = tr("반복: {c} 될 때까지").format(c=cond_text(s["until"]))
        elif "while" in s:
            body = tr("반복: {c} 인 동안").format(c=cond_text(s["while"]))
        else:
            body = tr("반복")
        if s.get("max_times"):
            body += tr(" (최대 {n}번)").format(n=s["max_times"])
    elif t == "call":
        body = f"{name}: {s.get('macro', '')}" + (f" → {s['result_var']}" if s.get("result_var") else "")
    elif t == "set_result":
        body = tr("결과값 = {v}").format(v=repr(s.get("value")))
    elif t == "text":
        a = s.get("action") or "set"
        src = s.get("list") if a == "join" else _short(str(s.get("text", "")), 40)
        body = f"{name}: {s.get('var')} ← {tr(TEXT_ACTIONS.get(a, a))} {src!r}"
    elif t == "date":
        if (s.get("action") or "format") == "diff":
            body = f"{name}: {s.get('var')} ← {s.get('from') or tr('지금')} ~ {s.get('to') or tr('지금')}"
        else:
            body = f"{name}: {s.get('var')} ← {s.get('from') or tr('지금')} ({s.get('format') or 'yyyy-MM-dd'})"
    elif t == "calc":
        body = f"{name}: {s.get('var')} = {s.get('expr', '')}"
    elif t == "mail":
        a = s.get("action", "find")
        via = s.get("via", "outlook")
        where = tr(MAIL_SERVICES.get(s.get("service"), "")) if via == "web" else tr(MAIL_VIAS.get(via, via)).split("(")[0]
        what = tr(MAIL_ACTIONS.get(a, a))
        if a == "send":
            what += f" → {s.get('to', '')}" + (tr(" (바로 보냄)") if s.get("send_now") else tr(" (임시 보관함)"))
        elif a == "find":
            what += " " + " ".join(x for x in (s.get("from", ""), s.get("subject", "")) if x)
        body = f"{name}[{where}]: {what}" + (f" → {s['var']}" if s.get("var") else "")
    elif t == "list":
        a = s.get("action", "add")
        what = tr(LIST_ACTIONS.get(a, a))
        if a == "sort":
            by = s.get("by")
            by = by if isinstance(by, str) else ", ".join(k.get("key", "") for k in (by or []))
            what += f" ({by or tr('값')}{', ' + tr('내림') if s.get('order') == 'desc' else ''})"
        body = f"{name} {s.get('var')}: {what}"
    elif t == "memory":
        v = s.get("value")
        nm = v if isinstance(v, str) else tr("주소 {a}").format(a=(v or {}).get("offset", "?"))
        a = s.get("action", "read")
        if a == "write":
            body = f"{tr('메모리 값 바꾸기')}: {nm} = {s.get('set')!r}"
        elif a == "freeze":
            body = f"{tr('메모리 값 고정')}: {nm} = {s.get('set')!r}"
        elif a == "unfreeze":
            body = f"{tr('메모리 값 고정 끄기')}: {nm}"
        else:
            body = f"{name}: {nm} → {s.get('var')}"
    elif t == "pdf":
        a = s.get("action", "text")
        what = {"text": tr("글 전체"), "extract": tr("규칙으로 뽑기"), "table": tr("표")}.get(a, a)
        body = f"{name}: {s.get('path', '')} {what} → {s.get('var')}"
    elif t == "ask":
        body = f"{name}: {tr(ASK_KINDS.get(s.get('kind', 'input'), ''))} {_short(str(s.get('message', '')), 40)!r} → {s.get('var')}"
    elif t == "notify":
        ch = s.get("channels") or ["toast"]
        ch = [ch] if isinstance(ch, str) else ch
        body = f"{name}: {_short(str(s.get('message', '')), 40)!r} ({', '.join(tr(NOTIFY_CHANNELS.get(c, c)) for c in ch)})"
    elif t == "each":
        src = next((k for k in EACH_SOURCES if k in s), "list")
        v = s.get(src)
        if src == "range" and isinstance(v, dict):
            what = f"{v.get('from', 1)}~{v.get('to', '')}"
        elif src == "rows" and isinstance(v, dict):
            what = v.get("sheet") or v.get("path") or tr("열린 엑셀")
        elif src == "files" and isinstance(v, dict):
            what = f"{v.get('path', '')} {v.get('pattern', '')}".strip()
        else:
            what = v if isinstance(v, str) else tr("{n}개").format(n=len(v or []))
        body = f"{name}: {tr(EACH_SOURCES[src])} {what} → {s.get('var')}"
    elif t == "file":
        a = s.get("action", "copy")
        what = tr(FILE_ACTIONS.get(a, a))
        if a == "delete" and s.get("permanent"):
            what = tr("영구 삭제")
        tail = s.get("to") or s.get("name") or s.get("pattern") or ""
        body = f"{name}: {what} {s.get('path', '')}" + (f" → {tail}" if tail else "") + \
            (f" → {s['var']}" if s.get("var") else "")
    elif t == "clipboard":
        a = s.get("action", "read")
        what = tr(CLIPBOARD_ACTIONS.get(a, a))
        if a == "write":
            body = f"{name}: {what} {_short(str(s.get('text', '')), 40)!r}"
        elif a == "save_image":
            body = f"{name}: {what} → {s.get('path', '')}"
        elif a == "clear":
            body = f"{name}: {what}"
        else:
            body = f"{name}: {what} → {s.get('var')}"
    elif t == "set":
        body = tr("변수 {v} += {x}").format(v=s.get("var"), x=s["add"]) if "add" in s else tr("변수 {v} = {x}").format(v=s.get("var"), x=repr(s.get("value")))
    elif t == "return":
        body = name + (tr(" (값 {v})").format(v=repr(s["value"])) if "value" in s else "")
    elif t == "stop":
        body = name + (f": {s['reason']}" if s.get("reason") else "")
    elif t == "comment":
        body = tr("메모: {t}").format(t=_short(s.get("text", ""), 60))
    else:
        body = name
    if s.get("foreground"):
        body += tr(" [잠깐 앞에서]")
    of = s.get("on_fail")
    if of == "skip":
        body += tr(" [실패 시 건너뜀]")
    elif of == "retry":
        body += tr(" [실패 시 다시]")
    elif isinstance(of, dict):
        body += tr(" [실패 시 끝내기 {v}]").format(v=repr(of.get("return")))
    if s.get("note") and t != "comment":
        body += f"  — {s['note']}"
    return body
