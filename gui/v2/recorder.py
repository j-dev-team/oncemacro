"""
마우스·키보드 녹화 → v2 스텝 목록(2026-11-17).

녹화하는 동안 진짜 마우스 클릭·끌기·키 입력을 받아 적고, 끝나면 스텝으로 바꾼다.
- 클릭 = click {point}(화면 좌표), 누른 채 움직여 놓으면 drag, 사이 시간은 delay(0.2초 미만은 버림)
- 글자 키는 모아서 type_text, 특수 키(Enter·Tab·F1·Ctrl+C 등)는 key
- 끝내기 키(F9)는 기록하지 않음
엔진·Qt 없이도 쓰도록 변환(events_to_steps)은 순수 함수.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

STOP_KEY = "f9"
MIN_DELAY = 0.2          # 이보다 짧은 쉬는 시간은 스텝으로 안 만듦
DRAG_PX = 6              # 누른 곳과 뗀 곳이 이만큼 넘게 떨어지면 끌기

_SPECIAL = {"enter": "enter", "tab": "tab", "esc": "esc", "backspace": "backspace", "delete": "delete",
            "space": "space", "up": "up", "down": "down", "left": "left", "right": "right",
            "home": "home", "end": "end", "page_up": "pageup", "page_down": "pagedown", "insert": "insert"}
_MODS = {"ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl", "shift": "shift", "shift_l": "shift",
         "shift_r": "shift", "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
         "cmd": "win", "cmd_l": "win", "cmd_r": "win"}


def events_to_steps(events: List[tuple]) -> List[dict]:
    """events: (시각, 종류, 값) 목록. 종류: 'down'(x, y, 버튼) / 'up'(x, y, 버튼) / 'key'(이름, 조합키 목록)."""
    steps: List[dict] = []
    last_t: Optional[float] = None
    pending_down = None
    text_buf = ""

    def flush_text():
        nonlocal text_buf
        if text_buf:
            steps.append({"type": "type_text", "text": text_buf})
            text_buf = ""

    def gap(t):
        nonlocal last_t
        if last_t is not None and t - last_t >= MIN_DELAY:
            flush_text()
            steps.append({"type": "delay", "seconds": round(t - last_t, 1)})
        last_t = t

    for t, kind, val in events:
        if kind == "down":
            pending_down = (t, val)
            continue
        if kind == "up":
            if pending_down is None:
                continue
            t0, (x0, y0, btn) = pending_down
            pending_down = None
            x1, y1, _ = val
            gap(t0)
            flush_text()
            if abs(x1 - x0) > DRAG_PX or abs(y1 - y0) > DRAG_PX:
                steps.append({"type": "drag", "from": {"point": [int(x0), int(y0)]},
                              "to": {"point": [int(x1), int(y1)]},
                              "duration_ms": int(max(100, (t - t0) * 1000))})
            else:
                s = {"type": "click", "target": {"point": [int(x0), int(y0)]}}
                if btn != "left":
                    s["button"] = btn
                if steps and steps[-1].get("type") == "click" and steps[-1]["target"] == s["target"] \
                        and steps[-1].get("button", "left") == btn and steps[-1].get("count", 1) == 1:
                    steps[-1]["count"] = 2          # 더블클릭
                else:
                    steps.append(s)
            last_t = t
            continue
        if kind == "key":
            name, mods = val
            gap(t)
            if len(name) == 1 and not (set(mods) - {"shift"}):
                text_buf += name
            else:
                flush_text()
                keys = "+".join(list(dict.fromkeys(mods)) + [name])
                if steps and steps[-1].get("type") == "key" and steps[-1]["keys"] == keys:
                    steps[-1]["count"] = steps[-1].get("count", 1) + 1
                else:
                    steps.append({"type": "key", "keys": keys})
    flush_text()
    return steps


class Recorder:
    """pynput 로 진짜 입력을 받아 적는다. stop() 또는 F9 로 끝."""

    def __init__(self, on_stop: Optional[Callable[[List[dict]], None]] = None):
        self.on_stop = on_stop
        self.events: List[tuple] = []
        self._mods: List[str] = []
        self._mouse = None
        self._kb = None
        self._done = threading.Event()

    def start(self):
        from pynput import keyboard, mouse

        def on_click(x, y, button, pressed):
            b = {"left": "left", "right": "right", "middle": "middle"}.get(getattr(button, "name", ""), "left")
            self.events.append((time.time(), "down" if pressed else "up", (x, y, b)))

        def key_name(key):
            n = getattr(key, "char", None)
            if n:
                return n
            n = getattr(key, "name", None) or ""
            return n

        def on_press(key):
            n = key_name(key)
            if n.lower() == STOP_KEY:
                self.stop()
                return False
            if n in _MODS:
                m = _MODS[n]
                if m not in self._mods:
                    self._mods.append(m)
                return
            if len(n) == 1 and self._mods and set(self._mods) - {"shift"} and ord(n) < 32:
                n = chr(ord(n) + 96)                  # Ctrl+글자는 제어 문자로 옴 → 글자로
            if n in _SPECIAL:
                n = _SPECIAL[n]
            elif n.startswith("f") and n[1:].isdigit():
                pass
            elif len(n) != 1:
                return
            self.events.append((time.time(), "key", (n, list(self._mods))))

        def on_release(key):
            n = key_name(key)
            if n in _MODS and _MODS[n] in self._mods:
                self._mods.remove(_MODS[n])

        self._mouse = mouse.Listener(on_click=on_click)
        self._kb = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse.start()
        self._kb.start()

    def stop(self):
        if self._done.is_set():
            return
        self._done.set()
        for l in (self._mouse, self._kb):
            try:
                l.stop()
            except Exception:
                pass
        if self.on_stop:
            self.on_stop(events_to_steps(self.events))
