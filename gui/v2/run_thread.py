"""
GUI 에서 v2 매크로를 실행하는 작업 스레드.

- 엔진 Runner 를 이 스레드에서 돌리고, 정지는 엔진의 stop 이벤트로만 한다(강제 종료 안 함).
- 비상 정지 핫키(Ctrl+Shift+F12)는 CLI 와 똑같이 실행하는 동안 듣는다.
- 실행 기록은 전부 logs/runs/*.jsonl 에 쓰고, 화면에는 필요한 이벤트만 보낸다
  (poll 은 100ms 마다 나와서 화면으로 보내지 않는다).
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable, Optional

from PyQt5.QtCore import QThread, pyqtSignal

SHOW_EVENTS = {"run_start", "step_start", "step_end", "branch", "warning", "window_activated",
               "verify_failed", "step_retry", "iteration_start", "iteration_end", "run_end",
               "internal_error", "set"}


def default_env():
    from engine.real import RealEnv
    return RealEnv()


class RunThread(QThread):
    event = pyqtSignal(dict)          # 화면에 보여줄 실행 이벤트
    run_finished = pyqtSignal(dict)   # Result.to_dict() + {"trace": 경로}

    def __init__(self, macro: dict, env_factory: Optional[Callable] = None,
                 emergency_hotkey: Optional[str] = "ctrl+shift+f12",
                 write_trace: bool = True, parent=None):
        super().__init__(parent)
        self.macro = macro
        self.env_factory = env_factory or default_env
        self.emergency_hotkey = emergency_hotkey
        self.write_trace = write_trace
        self._stop = threading.Event()
        self.trace_path: Optional[str] = None
        self.result: Optional[dict] = None

    def stop(self) -> None:
        self._stop.set()

    def is_stopping(self) -> bool:
        return self._stop.is_set()

    def run(self) -> None:
        # AI(MCP)의 스텝 시험·실행과 입력이 섞이지 않게 같은 잠금을 쓴다(engine/control.py)
        from engine.control import INPUT_LOCK
        from gui.v2.i18n import tr
        if not INPUT_LOCK.acquire(timeout=5):
            out = {"status": "failed", "value": None, "iterations": 0, "failed_iterations": 0,
                   "error": {"path": "", "type": "",
                             "reason": tr("AI가 이 프로그램으로 스텝을 시험하는 중이라 실행하지 않음 — 끝난 뒤 다시 실행")},
                   "duration": 0.0, "trace": None}
            self.result = out
            self.run_finished.emit(out)
            return
        try:
            self._run_locked()
        finally:
            INPUT_LOCK.release()

    def _run_locked(self) -> None:
        jt = None
        try:
            env = self.env_factory()
            if self.write_trace:
                from engine.real import TRACE_ROOT
                from engine.trace import JsonlTrace, trace_path
                jt = JsonlTrace(trace_path(TRACE_ROOT, self.macro.get("name", "매크로")))
                self.trace_path = jt.path

            def on_event(ev: dict) -> None:
                if jt is not None:
                    jt(ev)
                if ev.get("event") in SHOW_EVENTS:
                    self.event.emit(dict(ev))

            runner = env.runner(self.macro, on_event=on_event)
            if self.emergency_hotkey:
                from engine.win_input import EmergencyStop
                with EmergencyStop(self._stop, self.emergency_hotkey):
                    res = runner.run(self._stop)
            else:
                res = runner.run(self._stop)
            out = res.to_dict()
        except Exception as e:  # 실행 준비 중 오류(창 못 찾음 등은 엔진 결과로 나옴)
            out = {"status": "failed", "value": None, "iterations": 0, "failed_iterations": 0,
                   "error": {"path": "", "type": "", "reason": f"{type(e).__name__}: {e}",
                             "traceback": traceback.format_exc()},
                   "duration": 0.0}
        finally:
            if jt is not None:
                jt.close()
        out["trace"] = self.trace_path
        self.result = out
        self.run_finished.emit(out)
