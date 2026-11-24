"""대상·조건 입력칸: 실제 매크로에 쓰인 값을 넣었다 빼면 그대로, 고치면 반영."""
import glob
import json
import os

import pytest

from gui.v3.editor.cond_editor import CondEditor
from gui.v3.editor.target_editor import TargetEditor
from gui.v3.editor.widgets import ABSENT, OptValue, parse_hues, hues_text

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "macros_v2")


def _collect():
    targets, conds = [], []

    def scan(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("target", "from", "to") and isinstance(v, dict):
                    targets.append(v)
                elif k == "what" and isinstance(v, dict):
                    targets.append(v)
                elif k in ("cond", "until", "while") and isinstance(v, dict):
                    conds.append(v)
                scan(v)
        elif isinstance(o, list):
            for x in o:
                scan(x)
    for f in glob.glob(os.path.join(ROOT, "*.json")):
        if not os.path.basename(f).startswith("_"):
            scan(json.load(open(f, encoding="utf-8")))
    return targets, conds


TARGETS, CONDS = _collect()


def test_found_real_values():
    import pytest
    if not TARGETS:
        pytest.skip("실제 매크로 폴더가 없음(공개 사본 등)")
    assert len(TARGETS) > 30 and len(CONDS) > 30


def test_targets_round_trip(qapp):
    te = TargetEditor()
    for t in TARGETS:
        te.set_target(t)
        assert te.target() == t, t


def test_conds_round_trip(qapp):
    ce = CondEditor()
    for c in CONDS:
        ce.set_cond(c)
        assert ce.cond() == c, c


def test_target_edit_image_region_and_color_check(qapp):
    te = TargetEditor()
    te.set_target({"image": "a.png", "color_check": None, "x_keep": 1})
    te.img_region_on.setChecked(True)
    te.img_region.set_region([1, 2, 30, 40])
    te.img_cc.set_value(ABSENT)
    out = te.target()
    assert out == {"image": "a.png", "x_keep": 1, "region": [1, 2, 30, 40]}


def test_target_kind_change_resets(qapp):
    te = TargetEditor()
    te.set_target({"image": "a.png", "offset": [0, -5]})
    te.kind.setCurrentIndex(te.kind.findData("point"))
    te.pt.set_xy([7, 8])
    assert te.target() == {"point": [7, 8], "offset": [0, -5]}


def test_cond_kind_change_wraps_existing(qapp):
    ce = CondEditor()
    ce.set_cond({"exists": {"image": "a.png"}})
    ce.kind.setCurrentIndex(ce.kind.findData("any"))
    assert ce.cond() == {"any": [{"exists": {"image": "a.png"}}]}
    ce.set_cond({"var": "n", "ge": 3})
    ce.var_op.setCurrentIndex(ce.var_op.findData("is_set_true"))
    assert ce.cond() == {"var": "n", "is_set": True}


def test_optvalue_modes(qapp):
    w = OptValue("기본", "무한", 0, 100, 1, 1, 5)
    w.set_value(ABSENT)
    assert w.value() is ABSENT
    w.set_value(None)
    assert w.value() is None
    w.set_value(12.5)
    assert w.value() == 12.5


def test_hues_text():
    assert parse_hues("0-10, 160-180") == [[0, 10], [160, 180]]
    assert hues_text([[0, 10], [160, 180]]) == "0-10, 160-180"
    assert parse_hues("") is None
