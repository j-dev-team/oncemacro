"""멈춤 지킴이(제품 기능): 오래 도는 매크로가 멈추거나 프로그램이 죽으면 알아채고 알림·다시 켜기. Qt 없음.

- 매크로 프로그램이 logs/guard/state.json 에 지금 상태를 적는다:
  {macro, pid, started, guard: true, ended?, status?, user_stopped?}
- 지킴이(별도 프로세스, `MacroManager.exe --guard`)가 20초마다 본다(decide):
  · 사용자가 멈추거나 닫음(user_stopped) → 아무것도 안 함(알림도 없음)
  · 프로그램이 없는데 사용자가 끈 게 아님 → 알림 + 다시 켜기(1시간에 최대 3번)
  · 실행 기록(logs/runs)이 stall 분 넘게 안 늘어남 → 알림(멈춤 의심), 다시 켜기는 '멈춤 때도 다시 켜기'를 켰을 때만
- 하루 실적 요약(summary): 그날 실행 횟수·완료·실패·멈춤·다시 켬.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from typing import List, Optional

from .i18n import t

RESTART_PER_HOUR = 3


def _root(root: Optional[str] = None) -> str:
    if root:
        return root
    from .real import PROJECT_ROOT
    return PROJECT_ROOT


def state_path(root=None) -> str:
    return os.path.join(_root(root), "logs", "guard", "state.json")


def read_state(root=None) -> dict:
    try:
        with open(state_path(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(d: dict, root=None):
    if os.environ.get("MACRO_NO_GUARD") and root is None:     # 시험 중엔 진짜 기록을 건드리지 않음
        return
    p = state_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def mark_started(macro: str, pid: int, guard: bool, stall_min: float = 10, restart_on_stall: bool = False, root=None):
    write_state({"macro": macro, "pid": pid, "started": time.time(), "guard": bool(guard),
                 "stall_min": stall_min, "restart_on_stall": restart_on_stall,
                 "restarts": read_state(root).get("restarts", []) if guard else []}, root)


def mark_ended(status: str, user_stopped: bool, root=None):
    d = read_state(root)
    if not d:
        return
    d.update(ended=time.time(), status=status, user_stopped=bool(user_stopped))
    write_state(d, root)


def mark_app_closed(root=None):
    """사람이 프로그램을 닫음 → 지킴이는 다시 켜지 않는다."""
    d = read_state(root)
    if d:
        d.update(user_stopped=True, ended=d.get("ended") or time.time(), status=d.get("status") or "closed")
        write_state(d, root)


def log_event(kind: str, detail: str = "", root=None):
    p = os.path.join(_root(root), "logs", "guard", "events.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "at": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "detail": detail},
                           ensure_ascii=False) + "\n")


def latest_run_mtime(macro: str, root=None) -> Optional[float]:
    files = glob.glob(os.path.join(_root(root), "logs", "runs", f"*_{macro}.jsonl"))
    return max((os.path.getmtime(f) for f in files), default=None)


def decide(state: dict, alive: bool, log_mtime: Optional[float], now: float) -> str:
    """'없음' | '사용자가끔' | '다시켬' | '멈춤알림' | '멈춤다시켬' | '다시켜기잦음'"""
    if not state or not state.get("guard"):
        return "없음"
    if state.get("user_stopped"):
        return "사용자가끔"
    recent = [t for t in state.get("restarts", []) if now - t < 3600]
    if not alive:
        return "다시켜기잦음" if len(recent) >= RESTART_PER_HOUR else "다시켬"
    if state.get("ended"):
        return "없음"                                  # 정상으로 끝남(한 번 도는 매크로)
    stall = float(state.get("stall_min", 10)) * 60
    if log_mtime is not None and now - log_mtime > stall and now - state.get("started", now) > stall:
        if state.get("restart_on_stall") and len(recent) < RESTART_PER_HOUR:
            return "멈춤다시켬"
        return "멈춤알림"
    return "없음"


def summary(day: Optional[str] = None, root=None) -> dict:
    """그날(YYYYMMDD) 실행 실적: {runs, ok, failed, stopped, restarts, stalls}."""
    day = day or time.strftime("%Y%m%d")
    out = {"runs": 0, "ok": 0, "failed": 0, "stopped": 0, "restarts": 0, "stalls": 0}
    for f in glob.glob(os.path.join(_root(root), "logs", "runs", f"{day}_*.jsonl")):
        out["runs"] += 1
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                last = None
                for line in fh:
                    if '"run_end"' in line and '"depth": 0' in line:
                        last = line
            if last:
                st = json.loads(last).get("result", {}).get("status")
                if st in ("ok", "failed", "stopped"):
                    out[st] += 1
        except (OSError, ValueError):
            pass
    try:
        with open(os.path.join(_root(root), "logs", "guard", "events.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if time.strftime("%Y%m%d", time.localtime(d.get("t", 0))) == day:
                    if d.get("kind") in ("다시켬", "멈춤다시켬"):
                        out["restarts"] += 1
                    if d.get("kind") in ("멈춤알림", "멈춤다시켬"):
                        out["stalls"] += 1
    except (OSError, ValueError):
        pass
    return out


def run_loop(start_app, stop_app, notify, alive_fn, root=None, every: float = 20, until=lambda: False):
    """지킴이 본체. start_app(macro), stop_app(pid), notify(title, msg), alive_fn(pid)."""
    last_alert = {}
    while not until():
        st = read_state(root)
        now = time.time()
        act = decide(st, alive_fn(st.get("pid")) if st else False,
                     latest_run_mtime(st.get("macro", ""), root) if st else None, now)
        if act in ("다시켬", "멈춤다시켬"):
            if act == "멈춤다시켬":
                stop_app(st.get("pid"))
            st.setdefault("restarts", []).append(now)
            write_state(st, root)
            log_event(act, st.get("macro", ""), root)
            notify(t("멈춤 지킴이"), (t("'{m}' 이(가) 멈춰서 다시 켰어요") if act == "멈춤다시켬" else
                                       t("'{m}' 프로그램이 꺼져서 다시 켰어요")).format(m=st.get("macro")))
            start_app(st.get("macro"))
        elif act in ("멈춤알림", "다시켜기잦음") and now - last_alert.get(act, 0) > 1800:
            last_alert[act] = now
            log_event(act, st.get("macro", ""), root)
            notify(t("멈춤 지킴이"), (t("'{m}' 실행 기록이 멈췄어요(멈춤 의심)") if act == "멈춤알림" else
                                       t("'{m}' 이(가) 1시간에 3번 넘게 꺼져서 다시 켜기를 멈췄어요")).format(m=st.get("macro")))
        elif act == "사용자가끔":
            return                                      # 사람이 끔 → 지킴이도 끝
        time.sleep(every)



# ------------------------------------------------------------ 설정(매크로별)
def settings_path(root=None) -> str:
    return os.path.join(_root(root), "settings", "guard.json")


def load_settings(root=None) -> dict:
    try:
        with open(settings_path(root), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_setting(macro: str, cfg: Optional[dict], root=None):
    d = load_settings(root)
    if cfg:
        d[macro] = cfg
    else:
        d.pop(macro, None)
    p = settings_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def guard_pid_path(root=None) -> str:
    return os.path.join(_root(root), "logs", "guard", "guard.pid")


def guard_running(root=None) -> bool:
    try:
        with open(guard_pid_path(root), encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return False
    from .memsafe import alive
    return alive(pid)


def spawn_guard(root=None) -> Optional[int]:
    """지킴이 프로세스를 이 프로그램과 떨어뜨려 띄움(이미 돌면 그대로)."""
    import subprocess
    if guard_running(root):
        return None
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--guard"]
    else:
        cmd = [sys.executable, os.path.join(_root(root), "main.py"), "--guard"]
    p = subprocess.Popen(cmd, cwd=_root(root), creationflags=0x08000000 | 0x00000008,   # 창 없음 · 떨어진 프로세스
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.dirname(guard_pid_path(root)), exist_ok=True)
    with open(guard_pid_path(root), "w", encoding="utf-8") as f:
        f.write(str(p.pid))
    return p.pid


def main_guard():
    """`MacroManager.exe --guard` 진입점."""
    import subprocess
    from .memsafe import alive

    def start_app(macro):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--run", macro]
        else:
            cmd = [sys.executable, os.path.join(_root(), "main.py"), "--v3", "--run", macro]
        subprocess.Popen(cmd, cwd=_root(), creationflags=0x00000008)

    def stop_app(pid):
        try:                                            # 창 닫기 요청(강제 종료 안 함)
            from .office_guard import post_close, windows
            for w in windows(int(pid)):
                if w["visible"]:
                    post_close(w["hwnd"])
            time.sleep(10)
        except Exception:
            pass

    def notify(title, msg):
        try:
            from . import notify as nt
            nt.send(title, msg, channels=("toast", "log"), source=t("멈춤 지킴이"))
        except Exception:
            pass
    with open(guard_pid_path(), "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    run_loop(start_app, stop_app, notify, lambda pid: bool(pid) and alive(int(pid)))
