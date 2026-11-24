"""렌파이 콘솔 켜기/끄기: game 폴더 찾기, 파일 하나만 넣고 빼기(원본 그대로)."""
import os

import pytest

from engine import renpy_tools as rt
from engine.memory import MemoryError_


def test_toggle(tmp_path):
    g = tmp_path / "MyVN" / "game"
    g.mkdir(parents=True)
    (tmp_path / "MyVN" / "renpy").mkdir()
    (g / "script.rpyc").write_bytes(b"x")
    exe = tmp_path / "MyVN" / "MyVN.exe"
    exe.write_bytes(b"MZ")
    assert rt.game_dir(str(exe)) == str(g)
    assert not rt.console_on(str(exe))
    rt.set_console(str(exe), True)
    assert rt.console_on(str(exe)) and "config.console = True" in (g / rt.FILE).read_text(encoding="utf-8")
    (g / (rt.FILE + "c")).write_bytes(b"compiled")        # 게임이 만든 것
    rt.set_console(str(tmp_path / "MyVN"), False)
    assert not os.path.exists(g / rt.FILE) and not os.path.exists(g / (rt.FILE + "c"))
    assert (g / "script.rpyc").read_bytes() == b"x"


def test_not_renpy(tmp_path):
    with pytest.raises(MemoryError_):
        rt.set_console(str(tmp_path), True)
