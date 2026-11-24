"""저장 파일에서 숫자 칸 찾기·고치기: 언리얼(GVAS) 숫자 칸 이름으로, JSON, 이름=숫자 글자. 원본 백업·기록."""
import json
import os
import struct

import pytest

from engine import savefile as sf
from engine.memory import MemoryError_


def _gvas_prop(name, typ, fmt, value, ue5=True):
    nb, tb = name.encode() + b"\x00", typ.encode() + b"\x00"
    size = struct.calcsize(fmt)
    head = struct.pack("<i", len(nb)) + nb + struct.pack("<i", len(tb)) + tb
    head += (struct.pack("<ii", 0, size) if ue5 else struct.pack("<q", size)) + b"\x00"
    return head + struct.pack(fmt, value)


@pytest.fixture
def gvas(tmp_path):
    d = tmp_path / "SaveGames"
    d.mkdir()
    b = b"GVAS" + b"\x00" * 40 + _gvas_prop("Day", "IntProperty", "<i", 13) + _gvas_prop("Money", "IntProperty", "<i", 9455) \
        + _gvas_prop("Speed", "FloatProperty", "<f", 1.5, ue5=False) + _gvas_prop("Money", "IntProperty", "<i", 7) + b"\x00" * 8
    p = d / "Slot.sav"
    p.write_bytes(b)
    return str(p)


def test_gvas_fields_and_set(gvas, tmp_path):
    fs = {f["name"]: f["value"] for f in sf.fields(gvas)}
    assert fs == {"Day": 13, "Money": 9455, "Speed": 1.5, "Money#2": 7}
    assert [f["name"] for f in sf.find(gvas, "money")] == ["Money", "Money#2"]
    r = sf.set_value(gvas, "Money", 100000, root=str(tmp_path))
    assert r["old"] == 9455 and os.path.exists(os.path.join(r["backup"], "Slot.sav"))
    fs = {f["name"]: f["value"] for f in sf.fields(gvas)}
    assert fs["Money"] == 100000 and fs["Day"] == 13 and fs["Money#2"] == 7
    assert "Slot.sav" in open(os.path.join(tmp_path, "logs", "memory", "writes.jsonl"), encoding="utf-8").read()
    with pytest.raises(MemoryError_):
        sf.set_value(gvas, "없는칸", 1, root=str(tmp_path))


def test_json_and_text(tmp_path):
    j = tmp_path / "s" / "save.json"
    j.parent.mkdir()
    j.write_text(json.dumps({"player": {"gold": 50, "hp": 9.5, "name": "a"}, "items": [1, 2]}), encoding="utf-8")
    assert {f["name"] for f in sf.fields(str(j))} == {"player.gold", "player.hp", "items[0]", "items[1]"}
    sf.set_value(str(j), "player.gold", 999, root=str(tmp_path))
    sf.set_value(str(j), "items[1]", 5, root=str(tmp_path))
    d = json.loads(j.read_text(encoding="utf-8"))
    assert d["player"]["gold"] == 999 and d["items"] == [1, 5] and d["player"]["name"] == "a"
    t = tmp_path / "c" / "game.ini"
    t.parent.mkdir()
    t.write_text("[p]\ngold = 120\nname=x\n", encoding="utf-8")
    assert [f["name"] for f in sf.fields(str(t))] == ["gold"]
    sf.set_value(str(t), "gold", 5000, root=str(tmp_path))
    assert "gold = 5000" in t.read_text(encoding="utf-8")


def test_renpy_refused(tmp_path):
    p = tmp_path / "1-1-LT1.save"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 60)
    with pytest.raises(MemoryError_, match="렌파이"):
        sf.fields(str(p))
