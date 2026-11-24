"""
실행 기록. 이벤트를 JSONL 파일로 남기고, 사람이 읽을 요약을 콘솔에 찍는다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Callable, List, Optional, TextIO

from .i18n import t


class JsonlTrace:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self._f = open(path, "a", encoding="utf-8")

    def __call__(self, ev: dict):
        self._f.write(json.dumps({"wall": round(time.time(), 3), **ev}, ensure_ascii=False,
                                 default=str) + "\n")
        self._f.flush()

    def close(self):
        self._f.close()


def trace_path(root: str, macro_name: str) -> str:
    safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in macro_name)
    return os.path.join(root, f"{time.strftime('%Y%m%d_%H%M%S')}_{safe}.jsonl")


class ConsoleTrace:
    """주요 이벤트만 한 줄씩."""

    def __init__(self, out: Optional[TextIO] = None, verbose: bool = False):
        self.out = out or sys.stdout
        self.verbose = verbose

    def __call__(self, ev: dict):
        e = ev["event"]
        pad = "  " * ev.get("depth", 0)
        ts = f"[{ev['t']:8.2f}]"
        line = None
        if e == "run_start":
            line = f"{ts} {pad}▶ " + t("{macro} 시작 (반복 {repeat})", macro=ev['macro'], repeat=ev.get('repeat'))
        elif e == "run_end":
            r = ev["result"]
            line = f"{ts} {pad}■ " + t("{macro} 끝: {status} 값={value} 성공 {ok}회 / 실패 {failed}회", macro=ev['macro'], status=r['status'], value=repr(r['value']), ok=r['iterations'], failed=r['failed_iterations'])
            if r.get("error"):
                line += "\n" + " " * 11 + pad + "  " + t("오류 {path}: {reason}", path=r['error']['path'], reason=r['error']['reason'])
        elif e == "iteration_start" and self.verbose:
            line = f"{ts} {pad}── " + t("회차 {n}", n=ev['iteration'])
        elif e == "iteration_end" and ev.get("status") == "failed":
            line = f"{ts} {pad}" + t("회차 {n} 실패:{path} — {reason}", n=ev['iteration'], path=ev['error']['path'], reason=ev['error']['reason'])
        elif e == "step_end":
            if ev["status"] != "ok" or self.verbose:
                mark = {"ok": "OK  ", "skipped": t("건너뜀"), "failed": t("실패")}.get(ev["status"], "?")
                line = f"{ts} {pad}{mark} {ev['path']} {ev['type']} {ev['ms']}ms"
                if ev.get("reason"):
                    line += f" — {ev['reason']}"
        elif e == "input" and self.verbose:
            line = f"{ts} {pad}  >> {ev['kind']} " + " ".join(
                f"{k}={v}" for k, v in ev.items() if k in ("x", "y", "x2", "y2", "keys", "button"))
        elif e == "poll" and self.verbose:
            line = f"{ts} {pad}  … {ev['path']} {ev['result']} {ev['detail']}"
        elif e in ("warning", "verify_failed", "step_retry", "internal_error"):
            line = f"{ts} {pad}!! {e}: " + str(ev.get("message") or ev.get("reason") or ev.get("detail")
                                              or ev.get("error"))
        elif e == "window":
            line = f"{ts} {pad}" + t("[창] 대상: {target}", target=ev['target'])
        if line:
            print(line, file=self.out, flush=True)


def fanout(*cbs: Callable[[dict], None]) -> Callable[[dict], None]:
    live: List[Callable] = [c for c in cbs if c]

    def f(ev):
        for c in live:
            c(ev)
    return f
