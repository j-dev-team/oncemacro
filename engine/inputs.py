"""이 매크로가 진짜 마우스·키보드를 쓰는지(2026-11-19 'AI 에게 시키기' 실전에서 나온 막힘).

입력 잠금(INPUT_LOCK)은 마우스·키보드가 두 줄기로 섞이지 않게 하려는 것이다. 그런데 파일 정리·엑셀·PDF·메일처럼
입력이 없는 매크로까지 막으면, 자동운영이 도는 동안 AI 가 사무 매크로를 시험조차 못 한다.
그래서 입력을 쓰지 않는 매크로는 잠금 없이 같이 돌게 한다.
"""
from __future__ import annotations

from typing import Callable, Optional, Set

INPUT_STEPS = {"click", "move", "drag", "scroll", "mouse_down", "mouse_up", "key", "type_text", "menu",
               "remember"}                       # remember(마우스 위치)는 입력은 아니지만 사람 마우스와 엮여서 같이 둠
INPUT_CLIPBOARD = {"copy", "paste"}             # 클립보드 복사·붙여넣기는 Ctrl+C/V 키를 보냄


def uses_input(macro: dict, load: Optional[Callable[[str], dict]] = None, _seen: Optional[Set[str]] = None) -> bool:
    """매크로(와 부르는 매크로)가 진짜 입력을 쓰면 True. 모르는 매크로를 부르면 안전하게 True."""
    seen = _seen if _seen is not None else set()

    def walk(steps) -> bool:
        for s in steps or []:
            if not isinstance(s, dict):
                continue
            t = s.get("type")
            if t in INPUT_STEPS:
                return True
            if t == "clipboard" and s.get("action") in INPUT_CLIPBOARD:
                return True
            if t == "call":
                name = s.get("macro")
                if name in seen:
                    continue
                seen.add(name)
                if load is None:
                    return True
                try:
                    if uses_input(load(name), load, seen):
                        return True
                except Exception:
                    return True
            for k in ("steps", "then", "else"):
                if isinstance(s.get(k), list) and walk(s[k]):
                    return True
        return False
    return walk(macro.get("steps"))
