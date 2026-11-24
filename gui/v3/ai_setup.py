"""AI 연결 한 번에(11-18): 이 컴퓨터에 깔린 AI 프로그램을 찾아, 사람이 [연결하기]를 누르면 설정 파일에 macro 연결을 대신 써 준다.

- 원래 설정은 그대로 두고 'macro' 한 칸만 넣거나 바꾼다. 쓰기 전에 원래 파일을 '이름.bak-날짜시각'으로 남긴다.
- 원래 파일이 깨져 있으면(JSON/TOML 을 못 읽으면) 덮어쓰지 않고 멈춘다.
- Claude Code 는 설정 파일이 크고 자주 바뀌므로 파일을 직접 고치지 않고 `claude mcp add-json -s user` 명령으로 넣는다.
Qt 없음(화면은 ai_connect.py).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional

from gui.v2.i18n import tr

SERVER = "macro"
NOWIN = 0x08000000


def _home(env: Optional[dict] = None) -> str:
    e = env or os.environ
    return e.get("USERPROFILE") or os.path.expanduser("~")


def _appdata(env: Optional[dict] = None) -> str:
    e = env or os.environ
    return e.get("APPDATA") or os.path.join(_home(env), "AppData", "Roaming")


def clients(env: Optional[dict] = None) -> List[dict]:
    """알고 있는 AI 프로그램들: {key, name, kind(json/toml/cli), path?, installed}"""
    h, a = _home(env), _appdata(env)
    out = [
        {"key": "claude_desktop", "name": tr("Claude 데스크톱"), "kind": "json",
         "path": os.path.join(a, "Claude", "claude_desktop_config.json"), "dir": os.path.join(a, "Claude")},
        {"key": "claude_code", "name": "Claude Code", "kind": "cli", "cli": "claude"},
        {"key": "codex", "name": tr("Codex (CLI·데스크톱)"), "kind": "toml",
         "path": os.path.join(h, ".codex", "config.toml"), "dir": os.path.join(h, ".codex")},
        {"key": "gemini", "name": tr("제미나이 CLI"), "kind": "json", "cwd": True,
         "path": os.path.join(h, ".gemini", "settings.json"), "dir": os.path.join(h, ".gemini")},
        {"key": "cursor", "name": "Cursor", "kind": "json", "cursor": True,
         "path": os.path.join(h, ".cursor", "mcp.json"), "dir": os.path.join(h, ".cursor")},
    ]
    for c in out:
        if c["kind"] == "cli":
            c["installed"] = shutil.which(c["cli"]) is not None
        else:
            c["installed"] = os.path.isdir(c["dir"])
    return out


def entry_for(c: dict, spec: dict) -> dict:
    """그 프로그램 형식의 macro 한 칸."""
    e: dict = {}
    if c.get("cursor"):
        e["type"] = "stdio"
    e["command"] = spec["command"]
    e["args"] = list(spec["args"])
    if spec.get("env"):
        e["env"] = dict(spec["env"])
    if c.get("cwd") or c["kind"] == "toml":
        e["cwd"] = spec["cwd"]
    return e


# ------------------------------------------------------------ 상태
def status(c: dict, spec: dict) -> str:
    """'connected'(같은 것이 들어 있음) / 'different'(macro 가 있는데 다름) / 'absent'(없음) / 'broken'(파일을 못 읽음) / 'missing'(프로그램 없음)"""
    if not c.get("installed"):
        return "missing"
    want = entry_for(c, spec)
    try:
        if c["kind"] == "json":
            cur = (_read_json(c["path"]).get("mcpServers") or {}).get(SERVER)
        elif c["kind"] == "toml":
            cur = _toml_entry(_read_text(c["path"]))
        else:
            cur = _cli_entry(c)
    except ValueError:
        return "broken"
    if not cur:
        return "absent"
    same = cur.get("command") == want["command"] and list(cur.get("args") or []) == want["args"]
    return "connected" if same else "different"


def _read_text(p: str) -> str:
    try:
        with open(p, encoding="utf-8-sig") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _read_json(p: str) -> dict:
    t = _read_text(p).strip()
    if not t:
        return {}
    d = json.loads(t)                         # ValueError → 깨진 파일
    if not isinstance(d, dict):
        raise ValueError("not an object")
    return d


_TOML_HEAD = re.compile(r"^\s*\[mcp_servers\.(\"?)" + SERVER + r"\1(\.env)?\]\s*$")


def _toml_split(text: str):
    """(macro 칸 앞 줄들, macro 칸 줄들, 뒤 줄들)."""
    lines = text.splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if _TOML_HEAD.match(ln):
            if start is None:
                start = i
            end = None
        elif start is not None and end is None and re.match(r"^\s*\[", ln):
            end = i
    if start is None:
        return lines, [], []
    end = len(lines) if end is None else end
    return lines[:start], lines[start:end], lines[end:]


def _toml_entry(text: str) -> Optional[dict]:
    _, block, _ = _toml_split(text)
    if not block:
        return None
    e: dict = {}
    for ln in block:
        m = re.match(r"^\s*(command|cwd)\s*=\s*(\".*\")\s*$", ln)
        if m:
            e[m.group(1)] = json.loads(m.group(2))
        m = re.match(r"^\s*args\s*=\s*(\[.*\])\s*$", ln)
        if m:
            e["args"] = json.loads(m.group(1))
    return e


def _toml_block(e: dict) -> List[str]:
    q = lambda v: json.dumps(v, ensure_ascii=False)   # noqa: E731  TOML 기본 문자열 = JSON 문자열 꼴
    out = [f"[mcp_servers.{SERVER}]", f"command = {q(e['command'])}",
           f"args = [{', '.join(q(x) for x in e['args'])}]", f"cwd = {q(e['cwd'])}"]
    if e.get("env"):
        out += ["", f"[mcp_servers.{SERVER}.env]"] + [f"{k} = {q(v)}" for k, v in e["env"].items()]
    return out


def _cli_entry(c: dict) -> Optional[dict]:
    try:
        r = subprocess.run([shutil.which(c["cli"]) or c["cli"], "mcp", "get", SERVER], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30, creationflags=NOWIN)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    e: dict = {}
    for ln in r.stdout.splitlines():
        m = re.match(r"^\s*Command:\s*(.+)$", ln)
        if m:
            e["command"] = m.group(1).strip()
        m = re.match(r"^\s*Args:\s*(.*)$", ln)
        if m:
            e["args"] = m.group(1).split()
    return e or {"command": "?"}


# ------------------------------------------------------------ 쓰기
def _backup(p: str) -> Optional[str]:
    if not os.path.exists(p):
        return None
    b = p + ".bak-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, b)
    return b


def _write(p: str, text: str):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, p)


def connect(c: dict, spec: dict) -> dict:
    """연결 써 넣기. 돌려줌: {ok, message, backup?}"""
    if not c.get("installed"):
        return {"ok": False, "message": tr("{name} 이(가) 이 컴퓨터에 없음").format(name=c["name"])}
    e = entry_for(c, spec)
    if c["kind"] == "json":
        try:
            d = _read_json(c["path"])
        except ValueError:
            return {"ok": False, "message": tr("설정 파일을 읽을 수 없어 고치지 않았습니다(파일이 깨져 있음): {p}").format(p=c["path"])}
        servers = d.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
        servers[SERVER] = e
        d["mcpServers"] = servers
        b = _backup(c["path"])
        _write(c["path"], json.dumps(d, ensure_ascii=False, indent=2) + "\n")
        return {"ok": True, "backup": b, "message": tr("{name}: 연결을 넣었습니다").format(name=c["name"])}
    if c["kind"] == "toml":
        text = _read_text(c["path"])
        before, _, after = _toml_split(text)
        while before and not before[-1].strip():
            before.pop()
        new = before + ([""] if before else []) + _toml_block(e) + ([""] + after if after else [])
        b = _backup(c["path"])
        _write(c["path"], "\n".join(new) + "\n")
        return {"ok": True, "backup": b, "message": tr("{name}: 연결을 넣었습니다").format(name=c["name"])}
    exe = shutil.which(c["cli"]) or c["cli"]
    try:
        subprocess.run([exe, "mcp", "remove", SERVER, "-s", "user"], capture_output=True, text=True, timeout=30,
                       creationflags=NOWIN)
        r = subprocess.run([exe, "mcp", "add-json", "-s", "user", SERVER, json.dumps(e, ensure_ascii=False)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                           creationflags=NOWIN)
    except Exception as ex:
        return {"ok": False, "message": str(ex)}
    if r.returncode != 0:
        return {"ok": False, "message": (r.stderr or r.stdout or "").strip()[:300]}
    return {"ok": True, "message": tr("{name}: 연결을 넣었습니다(모든 폴더에서 쓰임)").format(name=c["name"])}


AFTER = {"claude_desktop": "Claude 데스크톱을 완전히 끄고(알림 영역 아이콘까지) 다시 켜세요.",
         "claude_code": "Claude Code 새 대화부터 macro 도구가 보입니다.",
         "codex": "Codex 를 다시 켜면 macro 도구가 보입니다.",
         "gemini": "제미나이 CLI 를 다시 켜면 macro 도구가 보입니다.",
         "cursor": "Cursor 설정 → MCP 목록에서 macro 가 켜졌는지 확인하세요."}


# ------------------------------------------------------------ AI에게 시키기
def request(task: str, name: str = "") -> str:
    """할 일 한 줄 → AI에게 줄 요청 글."""
    task = (task or "").strip() or tr("(할 일을 적어 주세요)")
    head = tr("macro MCP 도구만 써서 매크로를 만들어 줘. 코드를 새로 짜지 말고 이미 있는 스텝을 붙여.\n"
              "순서: macro_reference 읽기 → (웹이면) macro_web_view 로 페이지 보기 / (프로그램이면) macro_list_windows·"
              "macro_screenshot 으로 화면 보기 → macro_test_step 으로 한 스텝씩 시험 → macro_save → macro_run 으로 확인.")
    return head + "\n" + tr("할 일: ") + task + ("\n" + tr("매크로 이름: ") + name if name.strip() else "")


def start_cli(key: str, prompt: str, cwd: str) -> bool:
    """Claude Code·Codex·제미나이 CLI 를 새 터미널 창에서 그 요청으로 시작(사람이 단추를 눌렀을 때만)."""
    cli = {"claude_code": "claude", "codex": "codex", "gemini": "gemini"}.get(key)
    exe = shutil.which(cli) if cli else None
    if not exe:
        return False
    one_line = " ".join(prompt.split())        # 터미널 명령 줄에는 줄바꿈을 못 넣음
    subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", exe, one_line], cwd=cwd, creationflags=NOWIN)
    return True
