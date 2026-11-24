"""
v1 → v2 변환 규칙 테스트 (docs/engine_v2_design.md §10).
변환 결과를 가짜 화면에서 실제로 돌려서 v1 과 같은 동작인지도 확인한다.
"""
import json
import os

import pytest

from engine import validate_macro
from engine.convert_v1 import INF_WITHIN, Converter, convert_folder
from tests.engine.test_runner import World

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMG_ROOT = os.path.join(ROOT, "image")


def v1(actions, **kw):
    d = {"name": "t", "actions": actions, "repeat_count": 1, "infinite_repeat": False,
         "run_hotkey": "", "stop_hotkey": ""}
    d.update(kw)
    return d


def img(name="a.png", **p):
    return {"type": "image", "params": {"template": os.path.join(IMG_ROOT, "x", name), "confidence": 0.8,
                                        "timeout": 0, **p}}


def mm(x, y, **p):
    return {"type": "mouse_move", "params": {"x": x, "y": y, "button": "left", "action": "click",
                                             "double": False, "move_only": False, **p}}


def conv(acts, origin=(0, 0), **kw):
    out, rep = Converter(IMG_ROOT, origin).convert(v1(acts, **kw))
    assert rep.errors == [], rep.errors
    return out, rep


def test_image_then_click_pair_merges():
    out, rep = conv([img(result_var="p"), mm("p", "p")])
    assert out["steps"] == [{"type": "click", "timeout": None, "target": {
        "image": "x/a.png", "multiscale": True}}]
    assert rep.merged_clicks == 1 and rep.infinite_waits == 1


def test_pair_not_merged_when_var_used_twice():
    out, _ = conv([img(result_var="p", timeout=5), mm("p", "p"), {"type": "delay", "params": {"delay": 1}},
                   mm("p", "p")])
    types = [s["type"] for s in out["steps"]]
    assert types == ["remember", "click", "delay", "click"]
    assert out["steps"][0]["what"]["image"] == "x/a.png" and out["steps"][0]["timeout"] == 5.0


def test_save_position_var_before_click_and_save_only():
    out, _ = conv([mm(0, 0, save_position_var="s"), img(result_var="p"),
                   mm("p", "p", save_position_var="s2"), mm("s", "s", move_only=True)])
    assert [s["type"] for s in out["steps"]] == ["remember", "remember", "click", "move"]
    assert out["steps"][1] == {"type": "remember", "var": "s2"}
    assert out["steps"][3]["target"] == {"var": "s"}


def test_image_alone_becomes_wait_and_disappear_becomes_gone():
    out, _ = conv([img(timeout=2), img("b.png", wait_until_disappear=True, disappear_duration=3.0)])
    a, b = out["steps"]
    assert a["type"] == "wait" and a["until"] == {"exists": {"image": "x/a.png", "multiscale": True}}
    assert a["timeout"] == 2.0
    assert b["until"]["gone"]["image"] == "x/b.png" and b["until"]["for"] == 3.0 and b["timeout"] is None


def test_branches_become_if_with_within_and_skip_group():
    out, rep = conv([img(result_var="p", timeout=3, on_success=[mm("p", "p")],
                         on_failure=[{"type": "delay", "params": {"delay": 1}}, mm(10, 20)])])
    s = out["steps"][0]
    assert s["type"] == "if" and s["within"] == 3.0
    assert s["then"] == [{"type": "click", "target": {"image": "x/a.png", "multiscale": True}}]
    g = s["else"][0]
    assert g["type"] == "group" and g["on_fail"] == "skip"
    assert [x["type"] for x in g["steps"]] == ["delay", "click"]


def test_infinite_wait_with_failure_branch_is_flagged():
    out, rep = conv([img(timeout=0, on_failure=[mm(1, 1)])])
    assert out["steps"][0]["within"] == INF_WITHIN
    assert any("실패 분기가 실행될 수 없었음" in w for w in rep.warnings)


def test_repeat_flags():
    out, _ = conv([img(timeout=1, repeat_success_until_fail=True, on_success=[mm(1, 1)], on_failure=[mm(2, 2)]),
                   img("b.png", timeout=1, repeat_failure_until_success=True, on_failure=[mm(3, 3)])])
    a, b = out["steps"]
    assert a["then"][0]["type"] == "repeat" and "while" in a["then"][0]
    assert b["else"][0]["type"] == "repeat" and "until" in b["else"][0]
    assert b["then"] == []


def test_success_only_no_failure_requires_found():
    out, _ = conv([img(timeout=2, on_success=[mm(1, 1)], on_success_repeat=3)])
    w, r = out["steps"]
    assert w["type"] == "wait" and r == {"type": "repeat", "times": 3, "steps": [
        {"type": "click", "target": {"point": [1, 1]}}]}


def test_mouse_variants():
    out, _ = conv([mm(5, 6, double=True), mm("7", "8", button="right"), mm(1, 2, action="press"),
                   mm(1, 2, action="release"), mm(3, 4, move_only=True)])
    s = out["steps"]
    assert s[0] == {"type": "click", "target": {"point": [5, 6]}, "count": 2}
    assert s[1] == {"type": "click", "target": {"point": [7, 8]}, "button": "right"}
    assert s[2]["type"] == "mouse_down" and s[3]["type"] == "mouse_up"
    assert s[4] == {"type": "move", "target": {"point": [3, 4]}}


def test_mixed_coordinates_left_as_comment_with_warning():
    out, rep = conv([mm("p", 10)])
    assert out["steps"][0]["type"] == "comment" and rep.warnings


def test_keyboard_and_aliases():
    out, rep = conv([{"type": "keyboard", "params": {"hotkey_type": "combo", "combo_key": "Ctrl+Shift+Esc"}},
                     {"type": "keyboard", "params": {"key": "winleft"}},
                     {"type": "keyboard", "params": {"key": "numpad_5"}}])
    assert [s["keys"] for s in out["steps"]] == ["ctrl+shift+esc", "win", "num5"]
    assert rep.warnings == []


def test_color_and_logic_branch():
    out, _ = conv([{"type": "color", "params": {"color": [1, 2, 3], "x": 10, "y": 20, "tolerance": 5,
                                                "timeout": 2}},
                   {"type": "logic_branch", "params": {"condition_type": "color",
                                                       "condition_data": {"color": "#ff0000", "x": 1, "y": 1,
                                                                          "timeout": 1}}}])
    a, b = out["steps"]
    assert a["until"] == {"exists": {"color": [1, 2, 3], "at": [10, 20], "tolerance": 5}}
    assert b["cond"]["exists"]["color"] == [255, 0, 0]
    assert b["then"] == [{"type": "set_result", "value": 1}]


def test_confidence_mapping():
    out, _ = conv([img(timeout=1, confidence=0.7, color_confidence=0.9, use_multiscale=False)])
    assert out["steps"][0]["until"]["exists"] == {"image": "x/a.png", "confidence": 0.7, "color_check": 0.9}


def test_window_origin_shifts_coordinates():
    out, _ = conv([img(timeout=1, region=[110, 220, 50, 50]), mm(130, 240)], origin=(100, 200))
    assert out["steps"][0]["until"]["exists"]["region"] == [10, 20, 50, 50]
    assert out["steps"][1]["target"] == {"point": [30, 40]}


def test_macro_level_repeat_and_iteration_policy():
    out, rep = conv([mm(1, 1)], infinite_repeat=True, repeat_count=10, run_hotkey="f2")
    assert out["repeat"] == {"forever": True}
    assert out["on_iteration_fail"]["max_consecutive"] is None
    assert out["run_hotkey"] == "f2" and "stop_hotkey" not in out
    out, rep = conv([mm(1, 1)], repeat_count=5)
    assert out["repeat"] == {"times": 5} and out["on_iteration_fail"]["max_consecutive"] == 3
    assert rep.changes


def test_unknown_action_kept_as_comment():
    out, rep = conv([{"type": "teleport", "params": {}}])
    assert out["steps"][0]["type"] == "comment" and rep.warnings


# ---------------------------------------------------------------- 변환 결과를 실제로 돌려보기

def _run(out, world):
    out = json.loads(json.dumps(out).replace(IMG_ROOT.replace("\\", "/"), ""))
    return world.runner(out).run()


def test_converted_branch_runs_failure_branch_and_continues():
    """v1 '줄기캐기' 형태: 3초 안에 못 찾으면 실패 분기 실행 후 계속."""
    out, _ = conv([img("go.png", result_var="g", timeout=3, on_success=[mm("g", "g")],
                       on_failure=[img("stem.png", result_var="s"), mm("s", "s")]),
                   {"type": "keyboard", "params": {"key": "f"}}])
    w = World()
    w.vision.show("x/stem.png", (50, 60))
    res = _run(out, w)
    assert res.status == "ok"
    assert w.input.clicks() == [(50, 60)]
    assert ("key_down", "f") in [e[1:] for e in w.input.events]


def test_converted_failure_branch_inner_failure_is_skipped():
    out, _ = conv([img("go.png", timeout=1, on_failure=[img("never.png", result_var="n", timeout=1),
                                                        mm("n", "n"), mm(9, 9)]),
                   {"type": "keyboard", "params": {"key": "f"}}])
    w = World()
    res = _run(out, w)
    assert res.status == "ok"
    assert w.input.clicks() == []                 # 실패 뒤 나머지(9,9 클릭)는 v1 처럼 건너뜀
    assert ("key_down", "f") in [e[1:] for e in w.input.events]


# ---------------------------------------------------------------- 실제 v1 매크로 전부

V1_DIR = os.path.join(ROOT, "macros")


@pytest.mark.skipif(not os.path.isdir(V1_DIR), reason="v1 macros 폴더 없음")
def test_all_real_v1_macros_convert_and_validate(tmp_path):
    reports = convert_folder(V1_DIR, str(tmp_path), IMG_ROOT)
    assert reports
    for r in reports:
        assert r.errors == [], (r.name, r.errors)
        assert r.skipped is None
        with open(r.output, encoding="utf-8") as f:
            assert validate_macro(json.load(f)) == []
    assert os.path.exists(tmp_path / "_groups.json")
