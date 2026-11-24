"""
실행 한 곳에서만(2026-11-17, 글로벌판 2-3): 화면 프로그램(GUI·실행 파일)이 켜져 있으면 AI의 MCP 요청을 그 프로그램이 대신 처리한다.

왜: 화면 프로그램과 MCP 서버는 서로 다른 프로세스라, 둘이 같은 대상 프로그램을 동시에 '뒤에서 실행'으로 다루면
서로 꼬여 AI의 클릭이 안 먹었다. 요청을 화면 프로그램 안에서 처리하면 한 곳에서만 다룬다.

구조
- 화면 프로그램: start_server() → 127.0.0.1 임의 포트에 작은 HTTP 서버. logs/control.json 에 {port, token, pid} 기록.
  요청 POST /call {"tool": 이름, "args": {...}} 를 받으면 같은 프로세스 안의 engine.mcp_server 도구 함수를 그대로 부른다.
- MCP 서버: relay(이름, 인자) → control.json 이 있고 그 프로세스가 살아 있고 ping 이 되면 넘기고 결과를 돌려받는다.
  안 되면 None → 지금처럼 MCP 서버가 직접 실행.
- 입력 잠금 INPUT_LOCK 하나를 화면 프로그램의 매크로 실행(run_thread)과 MCP 도구가 같이 쓴다:
  화면에서 매크로가 도는 동안 AI의 스텝 시험·실행은 '다른 실행이 진행 중' 으로 거절(입력이 두 줄기로 섞이지 않게).
  화면 보기·픽셀·이미지 찾기는 입력이 없어서 그대로 된다.
- 바깥 접속 없음(127.0.0.1 + 토큰).
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional

INPUT_LOCK = threading.Lock()          # 실제 입력은 한 번에 하나만(화면 프로그램 실행 + MCP 도구가 같이 씀)
IN_SERVER = False                      # 이 프로세스가 화면 프로그램(서버 쪽)이면 True → relay 하지 않음

RELAY_TOOLS = ("macro_screenshot", "macro_find_image", "macro_capture_template", "macro_pixel",
               "macro_test_step", "macro_reset_session", "macro_run", "macro_stop")


def control_file() -> str:
    from .real import PROJECT_ROOT
    return os.path.join(PROJECT_ROOT, "logs", "control.json")


# ---------------------------------------------------------------- 결과 주고받기(그림은 base64)

def _pack(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_pack(x) for x in v]
    if isinstance(v, dict):
        return {k: _pack(x) for k, x in v.items()}
    if hasattr(v, "to_image_content"):              # mcp Image
        ic = v.to_image_content()
        return {"__image__": ic.data, "mime": getattr(ic, "mime_type", None) or getattr(ic, "mimeType", "image/png")}
    return str(v)


def _unpack(v: Any) -> Any:
    if isinstance(v, list):
        return [_unpack(x) for x in v]
    if isinstance(v, dict):
        if "__image__" in v:
            from mcp.server.mcpserver import Image
            fmt = str(v.get("mime") or "image/png").split("/")[-1]
            return Image(data=base64.b64decode(v["__image__"]), format=fmt)
        return {k: _unpack(x) for k, x in v.items()}
    return v


# ---------------------------------------------------------------- 서버(화면 프로그램 쪽)

class _Handler(BaseHTTPRequestHandler):
    server_version = "MacroControl/1"

    def log_message(self, *a):          # 콘솔에 접속 기록 안 찍음
        pass

    def _reply(self, code: int, obj: Any):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Token", ""), self.server.token)

    def do_GET(self):
        if not self._authorized():
            return self._reply(403, {"error": "token"})
        if self.path == "/ping":
            return self._reply(200, {"ok": True, "pid": os.getpid(), "busy": INPUT_LOCK.locked()})
        self._reply(404, {"error": "path"})

    def do_POST(self):
        if not self._authorized():
            return self._reply(403, {"error": "token"})
        if self.path != "/call":
            return self._reply(404, {"error": "path"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n).decode("utf-8"))
            tool, args = req.get("tool"), req.get("args") or {}
            if tool not in RELAY_TOOLS:
                return self._reply(400, {"error": "tool"})
            from . import i18n
            tok = i18n.use_language(req.get("lang"))          # 요청한 AI 쪽 언어로 답함
            try:
                result = self.server.call(tool, args)
            finally:
                i18n._override.reset(tok)
            self._reply(200, {"result": _pack(result)})
        except Exception as e:
            self._reply(500, {"error": f"{type(e).__name__}: {e}"})


def _default_call(tool: str, args: Dict[str, Any]) -> Any:
    import asyncio
    import inspect
    from . import mcp_server
    fn = getattr(mcp_server, tool)
    out = fn(**args)
    if inspect.isawaitable(out):
        out = asyncio.run(out)
    return out


class ControlServer:
    def __init__(self, call: Optional[Callable[[str, Dict[str, Any]], Any]] = None, path: Optional[str] = None):
        self.path = path or control_file()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.token = secrets.token_hex(16)
        self.httpd.call = call or _default_call
        self.port = self.httpd.server_address[1]
        self._thread: Optional[threading.Thread] = None

    def start(self) -> "ControlServer":
        global IN_SERVER
        IN_SERVER = True
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="macro-control", daemon=True)
        self._thread.start()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"port": self.port, "token": self.httpd.token, "pid": os.getpid()}, fh)
        os.replace(tmp, self.path)
        return self

    def stop(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                mine = json.load(fh).get("pid") == os.getpid()
            if mine:
                os.remove(self.path)
        except Exception:
            pass
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


def start_server() -> Optional[ControlServer]:
    """화면 프로그램이 켤 때 부른다. 실패해도 프로그램은 그대로(AI는 직접 실행으로 돌아감)."""
    try:
        return ControlServer().start()
    except Exception as e:
        print(f"[control] start failed: {e}")
        return None


# ---------------------------------------------------------------- 중계(MCP 서버 쪽)

def _pid_alive(pid: int) -> bool:
    try:
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259                                 # STILL_ACTIVE
    except Exception:
        return False


def _target(path: Optional[str] = None) -> Optional[dict]:
    try:
        with open(path or control_file(), encoding="utf-8") as fh:
            info = json.load(fh)
    except Exception:
        return None
    if not isinstance(info, dict) or info.get("pid") == os.getpid() or not _pid_alive(info.get("pid", 0)):
        return None
    return info


def _request(info: dict, method: str, path: str, body: Optional[dict], timeout: float) -> dict:
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", int(info["port"]), timeout=timeout)
    try:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"X-Token": str(info.get("token", ""))}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        conn.request(method, path, body=data, headers=headers)
        r = conn.getresponse()
        out = json.loads(r.read().decode("utf-8") or "{}")
        out["_status"] = r.status
        return out
    finally:
        conn.close()


def live(path: Optional[str] = None) -> Optional[dict]:
    """화면 프로그램이 살아 있고 응답하면 그 정보, 아니면 None."""
    if IN_SERVER:
        return None
    info = _target(path)
    if not info:
        return None
    try:
        r = _request(info, "GET", "/ping", None, 2.0)
        return info if r.get("_status") == 200 and r.get("ok") else None
    except Exception:
        return None


def relay(tool: str, args: Dict[str, Any], timeout: float = 120.0, path: Optional[str] = None) -> Optional[Any]:
    """화면 프로그램에 도구 호출을 넘긴다. 넘길 곳이 없거나 연결이 안 되면 None(직접 실행하면 됨)."""
    if IN_SERVER or tool not in RELAY_TOOLS:
        return None
    info = live(path)
    if not info:
        return None
    try:
        from .i18n import current
        r = _request(info, "POST", "/call", {"tool": tool, "args": args, "lang": current()}, timeout)
    except Exception:
        return None
    if r.get("_status") != 200:
        from .i18n import t
        return t("오류: 화면 프로그램이 요청을 처리하지 못함: {e}", e=r.get("error", r.get("_status")))
    return _unpack(r.get("result"))
