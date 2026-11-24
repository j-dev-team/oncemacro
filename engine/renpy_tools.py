"""렌파이(Ren'Py) 게임: 게임이 공식으로 가진 개발자 콘솔 켜기/끄기(혼자 하는 게임용). Qt 없음.

원본 파일은 고치지 않고, game 폴더에 작은 파일 하나(zz_macro_console.rpy)만 넣는다.
- 켜기: 그 파일을 만든다 → 게임을 다시 켜면 Shift+O 로 콘솔, 콘솔에서 `money = 100000` 처럼 변수를 바꾼다.
- 끄기: 그 파일(과 게임이 만든 .rpyc)을 지운다 → 원래대로.
"""
from __future__ import annotations

import os
from typing import Optional

from .i18n import K, t
from .memory import MemoryError_

FILE = "zz_macro_console.rpy"
BODY = K("# 매크로 프로그램이 넣은 파일: 렌파이 개발자 콘솔(Shift+O) 켜기. 이 파일을 지우면 원래대로 돌아갑니다.\ninit 999 python:\n    config.console = True\n")


def game_dir(path: str) -> Optional[str]:
    """실행 파일이나 폴더 → 그 렌파이 게임의 game 폴더(아니면 None)."""
    d = path if os.path.isdir(path) else os.path.dirname(os.path.abspath(path))
    for _ in range(3):
        g = os.path.join(d, "game")
        if os.path.isdir(g) and (os.path.isdir(os.path.join(d, "renpy")) or os.path.isdir(os.path.join(d, "lib"))
                                 or any(f.endswith((".rpa", ".rpyc", ".rpy")) for f in os.listdir(g))):
            return g
        d = os.path.dirname(d)
    return None


def console_on(path: str) -> bool:
    g = game_dir(path)
    return bool(g and os.path.exists(os.path.join(g, FILE)))


def set_console(path: str, on: bool) -> str:
    """돌려줌: game 폴더. 렌파이 게임이 아니면 MemoryError_."""
    g = game_dir(path)
    if not g:
        raise MemoryError_(t("렌파이 게임 폴더가 아니에요(game 폴더를 찾지 못함)"))
    f = os.path.join(g, FILE)
    if on:
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(t(BODY))
    else:
        for x in (f, f + "c"):
            if os.path.exists(x):
                os.remove(x)
    return g
