"""영어 모드에서 엔진 글에 한글이 하나도 안 나오는지 검사.

범위: 형식 오류(스텝 종류마다 틀린 값), 실행 실패 이유·실행 기록(on_event) 글, MCP 서버(안내·도구 설명·설명서 전 분야),
CLI 도움말, 헛돎 풀기 사건 글, 정적 검사(t() 로 안 감싼 한글 글).
사용자가 준 값(매크로 이름·변수 이름 등)은 영어 이름으로 써서 섞이지 않게 한다.
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

import pytest

from engine import i18n, new_macro, validate_macro
from engine.backends import FakeClock, FakeInput, FakeVision, FakeWindow
from engine.library import DictLibrary
from engine.model import DEFAULT_SETTINGS, STEP_SPECS
from engine.runner import Runner

KO = re.compile(r"[가-힣]")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 값 후보: 틀린 값 위주(형식 검사용)
BAD = [None, "", "x", " ", 0, -1, 1.5, 99999, True, False, [], [1], ["a"], {}, {"a": 1},
       {"image": ""}, {"image": 5}, {"image": "a.png", "zzz": 1}, {"color": "x"}, {"color": [1, 2]},
       {"color": [1, 2, 3], "at": [1]}, {"point": "x"}, {"var": ""}, {"element": {}}, {"element": {"name": ""}},
       {"element": {"name": "a", "match": "zz"}}, {"element": {"name": "a", "index": -1}},
       {"element": {"name": "a", "type": 5}}, {"element": {"x": 1}}, {"element": 5},
       {"exists": {}}, {"gone": {"image": "a.png"}, "for": -1}, {"var": "a", "eq": 1, "ne": 2}, {"not": 5},
       {"all": []}, {"any": 5}, {"file": 5}, {"memory": 5},
       [1, 2, 3, 4], [1, 2], ["x", "y", "z", "w"], {"from": 1}, {"rows": 5}, {"range": {}}, {"files": {}}]


def _ko(strings):
    return sorted({s for s in strings if isinstance(s, str) and KO.search(s)})


def _walk_strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_strings(v, out)


@pytest.fixture(autouse=True)
def english(monkeypatch):
    monkeypatch.setenv("MACRO_LANG", "en")
    i18n.set_language("en")
    yield
    i18n.set_language("ko")


# ---------------------------------------------------------------- 형식 오류

_CRASHES = []


def _validation_messages():
    msgs = []
    crashes = _CRASHES

    def check(m):
        try:
            msgs.extend(validate_macro(m))
        except Exception as e:                     # 검사기가 죽으면 그것도 고칠 일
            crashes.append(f"{type(e).__name__}: {e} <- {json.dumps(m, ensure_ascii=False, default=str)[:150]}")

    keys = set(DEFAULT_SETTINGS) | {"type", "id", "note", "on_fail", "retries", "foreground", "button", "timeout"}
    for typ, spec in STEP_SPECS.items():
        check(new_macro("m", [{"type": typ}]))
        for key in sorted(spec | keys):
            for v in BAD:
                check(new_macro("m", [{"type": typ, key: v}]))
                check(new_macro("m", [{"type": "group", "steps": [{"type": typ, key: v}]}]))
        for combo in ({"action": "zz"}, {"action": ""}, {"action": 5}, {"action": "zz", "var": "a", "path": 5}):
            check(new_macro("m", [{"type": typ, **combo}]))
    for key in ("name", "description", "window", "repeat", "on_iteration_fail", "settings", "run_hotkey",
                "stop_hotkey", "steps", "ai_rescue", "rescues", "self_heal", "unstick", "version", "zzz"):
        for v in BAD + [{"on": "x"}, {"times": -1}, {"forever": 1}, {"action": "zz"}, {"title": 5}, {"title": ""},
                        {"size": 1}, {"process": 5}, {"background": 1}, {"mode": "zz"}]:
            m = new_macro("m", [{"type": "delay", "seconds": 1}])
            m[key] = v
            check(m)
    check("not a dict")
    check({"version": 1, "name": "m", "steps": []})
    check({"version": 2, "steps": []})
    return msgs


def test_validation_messages_english():
    msgs = _validation_messages()
    assert msgs
    assert not _CRASHES, "검사기 오류 %d개:" % len(_CRASHES) + chr(10).join(_CRASHES[:15])
    bad = _ko(msgs)
    assert not bad, f"형식 오류 한글 {len(bad)}개:\n" + "\n".join(bad)


# ---------------------------------------------------------------- 실행 실패 이유 + 기록

class _World:
    def __init__(self):
        self.clock = FakeClock()
        self.vision = FakeVision(self.clock)
        self.input = FakeInput(self.clock)
        self.window = FakeWindow()
        self.events = []

    def run(self, macro):
        r = Runner(macro, vision=self.vision, input=self.input, clock=self.clock,
                   library=DictLibrary(), window_factory=lambda cfg: self.window,
                   on_event=self.events.append, snapshot_dir=tempfile.mkdtemp(),
                   web=_NoWeb(), office=_NoOffice(), clipboard=_FakeClip(),
                   notifier=lambda *a, **k: None, asker=lambda req, stop: ("timeout", None))
        try:
            return r.run()
        except Exception as e:                     # 엔진 밖 오류도 글은 모은다
            return e


class _NoWeb:
    def __getattr__(self, name):
        def f(*a, **k):
            raise RuntimeError("stub")
        return f


class _NoOffice(_NoWeb):
    def shutdown(self):
        pass


class _FakeClip:
    text = ""

    def __getattr__(self, name):
        def f(*a, **k):
            return ""
        return f


SAFE_TYPES = ["click", "move", "scroll", "drag", "mouse_down", "mouse_up", "key", "type_text", "wait", "delay",
              "remember", "if", "repeat", "group", "each", "for_each", "break", "continue", "call", "set_result",
              "set", "text", "date", "calc", "list", "ask", "notify", "return", "stop", "snapshot", "comment",
              "read_number", "wait_window", "close_window", "menu"]

RUN_VALUES = ["x", "", "abc", "{nope}", "5", "-3", 0, 3, True, None, [], ["a", "b"], [1, 2, 3], {},
              {"image": "nope.png"}, {"image": "nope.png", "region": [0, 0, 5, 5]}, {"var": "nope"},
              {"color": [1, 2, 3], "at": [3, 3]}, {"point": [5, 5]}, {"element": {"name": "zz"}},
              {"var": "nope", "eq": 1}, {"var": "v", "gt": 5}, {"exists": {"image": "nope.png"}},
              {"gone": {"image": "nope.png"}, "for": 1}, {"not": {"var": "nope", "is_set": True}},
              {"from": 1, "to": 3}, {"rows": {"path": "nope.xlsx"}}, {"files": {"path": "nope-dir"}}]


def _runtime_strings():
    texts = []
    w = _World()
    results = []

    def go(steps, **fields):
        w2 = _World()
        m = new_macro("m", steps, settings={"timeout": 0.2, "poll_ms": 100}, **fields) if False else new_macro("m", steps, **fields)
        try:
            from engine import validate_macro as vm
            if vm(m):
                return
        except Exception:
            return
        res = w2.run(m)
        results.append(res)
        for e in w2.events:
            _walk_strings(e, texts)

    for typ in SAFE_TYPES:
        spec = STEP_SPECS[typ]
        go([{"type": typ}])
        keys = sorted(spec - {"steps", "then", "else"})
        for key in keys:
            for v in RUN_VALUES:
                base = {"type": typ, key: v, "timeout": 0.3}
                if typ in ("repeat",) and key in ("forever", "while"):
                    continue
                if typ == "delay":
                    base = {"type": typ, "seconds": 0.1}
                go([dict(base, timeout=0.3) if "timeout" in spec else {k: x for k, x in base.items() if k != "timeout"}])
    # 직접 짠 실패들
    cases = [
        [{"type": "click", "target": {"image": "nope.png"}, "timeout": 0.3}],
        [{"type": "click", "target": {"image": "nope.png"}, "timeout": 0.3, "on_fail": "skip"}],
        [{"type": "click", "target": {"var": "q"}}],
        [{"type": "wait", "until": {"exists": {"image": "a.png"}}, "timeout": 0.3}],
        [{"type": "wait", "until": {"gone": {"image": "a.png"}, "for": 1}, "timeout": 0.3}],
        [{"type": "key", "keys": "ctrl+nonsense"}], [{"type": "key", "keys": "!!!"}],
        [{"type": "set", "var": "a", "value": "{b}"}, {"type": "calc", "var": "c", "expr": "a + 1"}],
        [{"type": "calc", "var": "c", "expr": "1 / 0"}], [{"type": "calc", "var": "c", "expr": "import os"}],
        [{"type": "calc", "var": "c", "expr": "zz + 1"}],
        [{"type": "text", "var": "a", "text": "abc", "action": "extract", "pattern": "(\\d+)"}],
        [{"type": "text", "var": "a", "text": "abc", "action": "number"}],
        [{"type": "text", "var": "a", "text": "abc", "action": "split", "sep": ",", "index": 5}],
        [{"type": "text", "var": "a", "text": "abc", "action": "extract", "pattern": "(["}],
        [{"type": "date", "var": "d", "from": "garbage"}],
        [{"type": "date", "var": "d", "action": "diff", "from": "2026-01-01", "to": "garbage"}],
        [{"type": "date", "var": "d", "from": "2026-11-18", "format": "yyyy.MM.dd ddd"}],
        [{"type": "list", "var": "l", "action": "get", "value": 3}],
        [{"type": "list", "var": "l", "action": "append", "value": 1}, {"type": "list", "var": "l", "action": "pop"}],
        [{"type": "list", "var": "l", "action": "sort"}],
        [{"type": "each", "var": "i", "list": "nolist", "steps": [{"type": "comment", "text": "x"}]}],
        [{"type": "each", "var": "i", "range": {"from": 1, "to": 3}, "steps": [{"type": "stop", "reason": "bye"}]}],
        [{"type": "each", "var": "i", "files": {"path": "no-such-dir-xyz"}, "steps": []}],
        [{"type": "each", "var": "i", "rows": {"path": "no-such.xlsx"}, "steps": []}],
        [{"type": "call", "macro": "nothere"}],
        [{"type": "set_result", "value": "r"}, {"type": "return", "value": 1}],
        [{"type": "stop", "reason": "done"}],
        [{"type": "if", "cond": {"var": "zz", "is_set": True}, "then": [{"type": "comment", "text": "a"}],
          "else": [{"type": "comment", "text": "b"}]}],
        [{"type": "repeat", "times": 2, "steps": [{"type": "break"}]}],
        [{"type": "repeat", "until": {"var": "zz", "is_set": True}, "max_times": 2, "steps": [{"type": "delay", "seconds": 1}]}],
        [{"type": "repeat", "while": {"var": "zz", "ne": 1}, "max_seconds": 1, "steps": [{"type": "delay", "seconds": 1}]}],
        [{"type": "snapshot", "name": "s1"}],
        [{"type": "ask", "kind": "yesno", "var": "a", "message": "ok?", "timeout": 1}],
        [{"type": "ask", "kind": "text", "var": "a", "message": "name?"}],
        [{"type": "notify", "channels": ["log"], "title": "t", "message": "m", "must": True}],
        [{"type": "read_number", "var": "n", "region": [0, 0, 10, 10]}],
        [{"type": "launch", "target": "nope-program-xyz.exe"}] if False else [{"type": "comment", "text": "c"}],
        [{"type": "wait_window", "timeout": 0.3}], [{"type": "close_window", "timeout": 0.3}],
        [{"type": "menu", "path": "A > B"}],
        [{"type": "type_text", "text": "hi {nope}"}],
        [{"type": "drag", "from": {"point": [1, 1]}, "to": {"image": "nope.png"}, "timeout": 0.3}],
        [{"type": "remember", "var": "p", "what": {"image": "nope.png"}, "timeout": 0.3}],
        [{"type": "scroll", "target": {"image": "nope.png"}, "timeout": 0.3}],
        [{"type": "for_each", "var": "p", "target": {"image": "nope.png"}, "steps": []}],
    ]
    for c in cases:
        go(c)
    # 파일(임시 폴더 안에서만)
    d = tempfile.mkdtemp()
    fp = lambda n: os.path.join(d, n)
    for c in [
        {"action": "read_text", "path": fp("none.txt"), "var": "a"},
        {"action": "copy", "path": fp("none.txt"), "to": fp("b.txt")},
        {"action": "move", "path": fp("none.txt"), "to": fp("b.txt")},
        {"action": "delete", "path": fp("none.txt")},
        {"action": "rename", "path": fp("none.txt"), "name": "z.txt"},
        {"action": "list", "path": fp("nodir"), "var": "l"},
        {"action": "info", "path": fp("none.txt"), "var": "i"},
        {"action": "exists", "path": fp("none.txt"), "var": "e"},
        {"action": "unzip", "path": fp("none.zip"), "to": d},
        {"action": "zip", "path": fp("none"), "to": fp("a.zip")},
        {"action": "read_csv", "path": fp("none.csv"), "var": "c"},
        {"action": "write_csv", "path": fp("o.csv"), "data": "nolist"},
        {"action": "write_text", "path": fp("w.txt"), "text": "a"},
        {"action": "mkdir", "path": fp("sub")},
        {"action": "delete", "path": "C:\\"},
        {"action": "move", "path": "C:\\Windows", "to": fp("zz")},
    ]:
        go([{"type": "file", **c}])
        go([{"type": "file", **c}, {"type": "file", **c, "overwrite": "fail"}])
    w.events = []
    return texts, results


def test_runtime_texts_english():
    texts, results = _runtime_strings()
    reasons = []
    for r in results:
        if isinstance(r, Exception):
            reasons.append(str(r))
        else:
            if r.error:
                reasons.append(r.error.get("reason", ""))
            if isinstance(r.value, str):
                reasons.append(r.value)
    bad = _ko(texts + reasons)
    assert not bad, f"실행 글 한글 {len(bad)}개:\n" + "\n".join(bad[:200])


# ---------------------------------------------------------------- MCP 서버

_MCP_DUMP = r"""
import asyncio, json, sys
sys.path.insert(0, %r)
from engine import mcp_server as m
out = {"instructions": m.INSTRUCTIONS, "title": m.mcp.title if hasattr(m.mcp, "title") else "",
       "name_instr": getattr(m.mcp, "instructions", "")}
cats = [c[0] for c in m.REF_CATS] + ["all", "", "zzz"]
out["ref"] = {c: m.reference_text(c) for c in cats}
async def tools():
    r = await m.mcp.list_tools()
    return [t.model_dump(mode="json") if hasattr(t, "model_dump") else dict(t) for t in (getattr(r, "tools", r))]
out["tools"] = asyncio.run(tools())
import inspect
def call(fn, **kw):
    try:
        r = fn(**kw)
        if inspect.iscoroutine(r):
            r = asyncio.run(r)
        return r if isinstance(r, str) else json.dumps(r, ensure_ascii=False, default=lambda o: getattr(o, "text", str(o)))
    except Exception as e:
        return "EXC " + type(e).__name__ + ": " + str(e)
bad = {"version": 2, "name": "m", "steps": [{"type": "click"}, {"type": "zzz"}, {"type": "delay", "seconds": -1}]}
out["calls"] = [
    call(m.macro_validate, macro=bad), call(m.macro_validate, macro={"version": 2, "name": "m", "steps": []}),
    call(m.macro_save, macro=bad), call(m.macro_get, name="no_such_macro_zz"),
    call(m.macro_run, name="no_such_macro_zz"), call(m.macro_run, macro=bad), call(m.macro_run),
    call(m.macro_test_step, step={"type": "click"}), call(m.macro_test_step),
    call(m.macro_reset_session), call(m.macro_stop), call(m.macro_list, query="zzzzzz_none"),
    call(m.macro_find_image, image="no/such_image_zz.png"), call(m.macro_reference, category="zzz"),
]
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
"""


def _mcp_dump(lang="en"):
    env = dict(os.environ, MACRO_LANG=lang, PYTHONUTF8="1")
    p = subprocess.run([sys.executable, "-I", "-c", _MCP_DUMP % ROOT], capture_output=True, env=env, cwd=ROOT, timeout=120)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[-2000:]
    return json.loads(p.stdout.decode("utf-8"))


def test_mcp_english():
    d = _mcp_dump("en")
    strings = []
    _walk_strings(d, strings)
    bad = _ko(strings)
    # 설명서 본문은 길어서 줄 단위로 쪼개 보여 줌
    lines = []
    for s in bad:
        for ln in s.splitlines():
            if KO.search(ln):
                lines.append(ln.strip()[:200])
    assert not lines, f"MCP 한글 {len(lines)}줄:\n" + "\n".join(sorted(set(lines))[:300])


def test_mcp_korean_still_works():
    d = _mcp_dump("ko")
    assert KO.search(d["instructions"])
    assert KO.search(d["ref"]["input"])
    assert len(d["tools"]) >= 10


# ---------------------------------------------------------------- CLI 도움말

def test_cli_help_english():
    from engine import __main__ as cli
    texts = []
    for argv in ([], ["windows"], ["validate"], ["run"], ["find"], ["step"], ["convert"]):
        for extra in (["--help"], ["-h"]):
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                try:
                    cli.main(argv + extra)
                except SystemExit:
                    pass
            texts.append(buf.getvalue() + err.getvalue())
    # 잘못된 사용
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        try:
            cli.main(["find", "x.png", "--region", "1,2"])
        except SystemExit as e:
            texts.append(str(e.code))
        except Exception:
            pass
    bad = []
    for tx in texts:
        bad += [ln.strip() for ln in tx.splitlines() if KO.search(ln)]
    assert not bad, f"CLI 도움말 한글 {len(bad)}줄:\n" + "\n".join(sorted(set(bad)))


# ---------------------------------------------------------------- 정적 검사: t() 로 안 감싼 사람용 한글

# 코드가 비교하거나 파일·열쇠로 쓰는 값, 또는 한국어 모드에서만 쓰이는 글(사람에게 직접 보이는 글이 아님).
# 파일: 시작 글 목록. 이 목록은 줄이는 방향으로만 고친다.
_ALLOW_KEYS = {
    "fileops.py": ["이름", "확장자", "폴더", "크기", "수정", "행"],            # 한국어 별칭 열쇠(영어 열쇠와 늘 같이 둠)
    "guard.py": ["없음", "사용자가끔", "멈춤알림", "다시켜기잦음", "다시켬", "멈춤다시켬"],   # 지킴이 사건 종류(기록·비교용 값)
    "mail.py": ["받은편지함"], "mailserver.py": ["받은편지함"],              # 입력 값(영어 inbox 도 됨)
    "numread.py": ["옆검사", "쉼표", "빗금", "점"],                          # 글꼴 폴더 설정 열쇠·파일 이름(영어 이름도 됨)
    "office.py": ["엑셀", "워드", "한글", "행"],                             # 내부 이름(t() 로 번역해 보임)
    "office_guard.py": ["엑셀", "워드", "한글"],
    "rescue.py": ["결제", "구매", "충전", "로그인", "비밀번호", "카드", "계정", "보석", "잠금", "할인", "너는 "],  # 금지 낱말(영어도 같이 있음)·한국어 AI 지시문(영어판 PROMPT_EN)
    "runner.py": ["전역_", "줄", "줄수", ":찾음", "막힘", "대기 초과", "예", "첨부", "닫기", "취소", "안 통함", r"__(?:고침|fix)\d+"],
    "selfheal.py": ["닫기", "확인", "계속", "취소", "막힘", "통함", "안 통함", "시각", "매크로", "저장된해결", "사건", "결과", "단계"],
    "textops.py": ["월화수목금토일", "요일", "^("],                          # 한국어 날짜 낱말
    "webmail.py": ["로그인", "보안문자", "2단계 인증", "본인 확인"],            # 로그인 화면 감지 낱말(영어도 같이 있음)
    "mcp_server.py": ["Windows 화면", "## 메모리", "## 팁", "[가-힣]", "# 매크로 v2 형식", "입력:", "기다림·", "변수·", "파일·",
                      "웹 요소", "오피스:", "막히면", "## 분야", "모르는 분야", "'. 다음"],   # 한국어 모드 글(영어판이 따로 있음)
    "web.py": ["행"],
}
_SKIP_FILES = ("i18n.py", "fsnames.py")     # fsnames: 파일·폴더 이름(경로 담당 몫)
# t() 열쇠로 넘기는 제목(도구 제목)
_TITLE_LINES = ("@_tool(", "title=")


def test_static_no_untranslated_korean():
    import ast
    import glob
    offenders = []
    for fp in sorted(glob.glob(os.path.join(ROOT, "engine", "*.py"))):
        if os.path.basename(fp) in _SKIP_FILES:
            continue
        text = open(fp, encoding="utf-8").read()
        src_lines = text.splitlines()
        tree = ast.parse(text)
        parents = {}
        for n in ast.walk(tree):
            for c in ast.iter_child_nodes(n):
                parents[c] = n
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and KO.search(n.value):
                p = parents.get(n)
                if isinstance(p, ast.Expr):         # 설명문
                    continue
                q, wrapped = n, False
                while q in parents:
                    q = parents[q]
                    if isinstance(q, ast.Call) and isinstance(q.func, ast.Name) and q.func.id in ("t", "tr_", "K", "_d"):
                        wrapped = True
                        break
                src_line = src_lines[n.lineno - 1]
                base = os.path.basename(fp)
                if wrapped or "ko-key" in src_line or "ko-only" in src_line:
                    continue
                if any(a in n.value for a in _ALLOW_KEYS.get(base, [])):
                    continue
                if "const " in n.value or "let " in n.value:
                    continue                              # 웹 페이지 안에서 도는 JS 조각: 아래 test_js_texts_covered 가 따로 검사
                if base == "mcp_server.py" and any(x in src_line for x in _TITLE_LINES):
                    continue
                if any(a in n.value for a in ("_고침", "_제안", "_헛돎", "_원래위치", "_백업_", "_값조정전", "_AI규칙전", "_변환보고서",
                                              "fonts/numbers", "설정.json", "_웹보기.png", "logs/health", "_예약.json")):
                    continue                                  # 파일·폴더 이름은 경로 담당 몫
                offenders.append(f"{os.path.basename(fp)}:{n.lineno}: {n.value[:70]!r}")
    assert not offenders, f"t() 로 안 감싼 한글 {len(offenders)}개:\n" + "\n".join(offenders)


# ---------------------------------------------------------------- 헛돎 풀기·멈춤 지킴이 글

def _all_text_files(root):
    out = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            if f.endswith((".jsonl", ".json", ".txt", ".md")):
                out.append(os.path.join(dp, f))
    return out


def test_unstick_texts_english(tmp_path, monkeypatch):
    """헛돎 풀기: 닫기 대상으로 푸는 길과 해결 못 하고 쉬는 길 둘 다. 사건 글·경고 글에 한글 없어야 함(사건 열쇠는 예외)."""
    from tests.engine.test_selfheal import PopupVision, X_AT, X_IMG
    monkeypatch.setenv("MACRO_SELFHEAL_DIR", str(tmp_path))
    texts = []
    for close in (True, False):
        class W:
            popup = True
            n = 0
        w = W()
        clock = FakeClock()
        vision = PopupVision(clock, w)
        if close:
            vision.show(X_IMG, X_AT)
        inp = FakeInput(clock)

        def clicked(pos, button, w=w, vision=vision):
            w.n += 1
            if pos == X_AT:
                w.popup = False
                vision.hide(X_IMG)
        inp.on_click = clicked
        events = []
        un = {"on": True, "repeat_n": 10, "window_s": 1000, "ai": False, "rest_min": 0.1}
        if close:
            un["close_targets"] = [{"image": X_IMG}]
        m = new_macro("m", [{"type": "repeat", "times": 40, "steps": [
            {"type": "click", "target": {"point": [5, 5]}}, {"type": "delay", "seconds": 1}]}], unstick=un)
        res = Runner(m, vision=vision, input=inp, clock=clock, library=DictLibrary(), on_event=events.append).run()
        for e in events:
            _walk_strings(e, texts)
        if res.error:
            texts.append(str(res.error))
    # 닫기 단추 이름(닫기·취소)은 대상 프로그램의 글이라 두 언어를 다 찾는다 → 그 이름만 든 글은 뺌
    bad = [x for x in _ko(texts) if not all(w in ("닫기", "취소") for w in re.findall("[가-힣]+", x))]
    assert not bad, "헛돎 사건 글 한글:\n" + "\n".join(bad)
    # 기록 파일의 사람용 글(열쇠·분류 값은 코드가 읽으므로 제외)
    ev = tmp_path / "events.jsonl"
    if ev.exists():
        for ln in ev.read_text(encoding="utf-8").splitlines():
            rec = json.loads(ln)
            for k in ("증거", "이유", "evidence"):
                vals = []
                _walk_strings(rec.get(k), vals)
                assert not _ko(vals), (k, vals)


def test_guard_messages_english(tmp_path):
    from engine import guard
    root = str(tmp_path)
    guard.mark_started("m", 4242, True, root=root)
    notes = []
    calls = {"n": 0}

    def until():
        calls["n"] += 1
        return calls["n"] > 2
    guard.run_loop(lambda name: None, lambda name: None, lambda a, b: notes.append(a + " " + b), lambda pid: False,
                   root=root, every=0, until=until)
    st = guard.read_state(root)
    st["guard"], st["ended"] = True, None
    assert notes, "알림이 없음"
    assert not _ko(notes), notes


def test_notify_and_misc_english(tmp_path):
    from engine import notify
    texts = []
    try:
        texts.append(str(notify.send("t", "m", channels=("log",), root=str(tmp_path))))
    except Exception as e:
        texts.append(str(e))
    try:
        notify.send("t", "m", channels=("zzz",), root=str(tmp_path))
    except Exception as e:
        texts.append(str(e))
    try:
        notify.send("t", "m", channels=("webhook",), root=str(tmp_path))
    except Exception as e:
        texts.append(str(e))
    r = None
    try:
        r = notify.send("t", "m", channels=("webhook",), root=str(tmp_path))
    except Exception:
        pass
    if r:
        _walk_strings(r, texts)
    assert not _ko(texts), _ko(texts)


def test_js_texts_covered():
    """웹·웹메일 JS 조각 안에서 사용자에게 돌아가는 한글 글(따옴표 안, 주석 제외)은 모두 web.JS_TEXTS 에 있어야 영어 모드에서 바뀐다."""
    from engine import web, webmail, win_background
    frags = list(web.JS_TEXTS) + ["행"]
    missing = []
    for mod in (web, webmail, win_background):
        for name, val in vars(mod).items():
            if not (isinstance(val, str) and ("const " in val or "let " in val)):
                continue
            for line in val.splitlines():
                code = line
                k = code.find("//")
                while k >= 0:
                    if code[:k].count(chr(34)) % 2 == 0 and code[:k].count(chr(96)) % 2 == 0:
                        code = code[:k]
                        break
                    k = code.find("//", k + 2)
                for lit in re.findall(r'"[^"]*"|`[^`]*`', code):
                    if KO.search(lit) and not any(f in lit for f in frags):
                        missing.append(f"{mod.__name__}.{name}: {lit}")
    assert not missing, "JS 글이 web.JS_TEXTS 에 없음: " + chr(10).join(missing)
