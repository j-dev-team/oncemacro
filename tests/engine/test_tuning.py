"""값 조정 시험 반영(스스로 고치기 3단계): 시작 조건·확정·되돌림·매크로 반영·잘못 맞힘 검사. 실제 입력 없음."""
import json
import os

import cv2
import numpy as np

from engine.tuning import Tuner, apply_to_macro, false_match_check, metrics, step_key, TUNE_DEFAULTS

CFG = dict(TUNE_DEFAULTS, trial_iterations=4, baseline_min=4)


def its(n, ok=True, sec=2.0, reason=""):
    return [{"ok": ok, "seconds": sec, "reason": reason, "fail_path": "" if ok else "steps[0]", "warnings": []}
            for _ in range(n)]


def test_no_trial_without_enough_baseline(tmp_path):
    tu = Tuner(str(tmp_path), "m")
    assert tu.start("timeout", "k", 15, 10, its(2), CFG, "x", 0) is None
    assert tu.start("timeout", "k", 15, 10, its(5), CFG, "x", 0) is not None
    assert tu.start("timeout", "k2", 15, 10, its(5), CFG, "x", 0) is None          # 한 번에 하나만


def test_applied_when_same_or_better(tmp_path):
    tu = Tuner(str(tmp_path), "m")
    tu.start("confidence", "a.png", 0.74, 0.8, its(6) + its(2, ok=False, reason="못 찾음 0.76"), CFG, "x", 0)
    res = None
    for it in its(4):
        res = tu.on_iteration(it, CFG)
    assert res[0] == "applied" and tu.trial is None
    assert Tuner(str(tmp_path), "m").state["history"][-1]["status"] == "applied"     # 파일에 남음


def test_stays_on_trial_until_enough_samples(tmp_path):
    tu = Tuner(str(tmp_path), "m")
    tu.start("timeout", "k", 15, 10, its(6), CFG, "x", 0)
    assert tu.on_iteration(its(1)[0], CFG) is None and tu.trial is not None


def test_revert_on_new_consecutive_failures(tmp_path):
    tu = Tuner(str(tmp_path), "m")
    tu.start("timeout", "k", 15, 10, its(6), CFG, "x", 0)
    tu.on_iteration(its(1, ok=False, reason="오류 A")[0], CFG)
    status, t = tu.on_iteration(its(1, ok=False, reason="오류 A")[0], CFG)
    assert status == "reverted"


def test_revert_on_new_failure_kind(tmp_path):
    tu = Tuner(str(tmp_path), "m")
    base = its(5) + its(1, ok=False, reason="대기 초과 3초")
    tu.start("timeout", "k", 15, 10, base, CFG, "x", 0)
    res = None
    for it in its(3) + [{"ok": False, "seconds": 2, "reason": "전혀 다른 실패", "fail_path": "steps[2]", "warnings": []}]:
        res = tu.on_iteration(it, CFG)
    assert res[0] == "reverted"


def test_digits_do_not_make_new_failure_kinds():
    a = metrics(its(1, ok=False, reason="3초 대기 초과 — 점수 0.71"))
    b = metrics(its(1, ok=False, reason="5초 대기 초과 — 점수 0.66"))
    assert a["fail_kinds"] == b["fail_kinds"]


def test_macro_file_change_cancels_trial(tmp_path):
    mp = tmp_path / "m.json"
    mp.write_text("{}", encoding="utf-8")
    tu = Tuner(str(tmp_path), "m", str(mp))
    tu.start("timeout", "k", 15, 10, its(6), CFG, "x", 0)
    mp.write_text('{"x":1}', encoding="utf-8")
    assert tu.on_iteration(its(1)[0], CFG)[0] == "reverted"


def test_apply_recapture_keeps_old_as_fallback():
    m = {"name": "m", "steps": [{"type": "click", "target": {"image": "a.png"}},
                                {"type": "wait", "until": {"exists": {"image": "a.png"}}}]}
    out = apply_to_macro(m, {"kind": "recapture", "target": "a.png", "new": "a__고침.png"})
    assert out["steps"][0]["target"] == {"image": "a__고침.png", "fallback_images": ["a.png"]}
    assert out["steps"][1]["until"]["exists"]["image"] == "a__고침.png"
    assert m["steps"][0]["target"] == {"image": "a.png"}                              # 원본은 그대로


def test_apply_timeout_by_path_hash():
    st = {"type": "wait", "until": {"exists": {"image": "a.png"}}, "timeout": 10}
    m = {"name": "m", "steps": [{"type": "delay", "seconds": 1}, st]}
    key = step_key(st, "steps[1]")
    out = apply_to_macro(m, {"kind": "timeout", "target": key, "new": 15.0})
    assert out["steps"][1]["timeout"] == 15.0


def _png(path, img):
    cv2.imencode(".png", img)[1].tofile(str(path))


def test_false_match_check(tmp_path):
    rng = np.random.default_rng(3)
    tpl = rng.integers(0, 255, (20, 30), dtype=np.uint8)
    _png(tmp_path / "t.png", tpl)
    scr = rng.integers(0, 255, (200, 300), dtype=np.uint8)
    noisy = np.clip(tpl.astype(int) + rng.integers(-60, 60, tpl.shape), 0, 255).astype(np.uint8)
    scr[50:70, 100:130] = noisy                                       # 알던 자리(가운데 115,60)에 흐린 대상
    _png(tmp_path / "s1.png", scr)
    score = float(cv2.matchTemplate(scr, tpl, cv2.TM_CCOEFF_NORMED).max())
    ok, why = false_match_check(str(tmp_path / "t.png"), [(str(tmp_path / "s1.png"), (0, 0))],
                                round(score - 0.05, 2), round(score + 0.05, 2), (115, 60))
    assert ok, why                                                    # 알던 자리만 맞음 → 통과
    ok, why = false_match_check(str(tmp_path / "t.png"), [(str(tmp_path / "s1.png"), (0, 0))],
                                round(score - 0.05, 2), round(score + 0.05, 2), (10, 10))
    assert not ok                                                     # 알던 자리가 아니면 잘못 맞힘
    ok, why = false_match_check(str(tmp_path / "t.png"), [], 0.7, 0.8, (1, 1))
    assert not ok                                                     # 사진이 없으면 검사 불가 → 거절


def test_confidence_trial_ignores_its_own_marginal_warning(tmp_path):
    tu = Tuner(str(tmp_path), "m")
    tu.start("confidence", "a.png", 0.77, 0.8, its(6) + its(2, ok=False, reason="못 찾음"), CFG, "x", 0)
    res = None
    for it in its(4):
        it["warnings"] = ["score_low:a.png"]
        res = tu.on_iteration(it, CFG)
    assert res[0] == "applied"


def test_needs_minimum_watch_time(tmp_path):
    import time as _t
    tu = Tuner(str(tmp_path), "m")
    tu.start("timeout", "k", 15, 10, its(6), CFG, "x", _t.time())     # 방금 시작
    res = None
    for it in its(6):
        res = tu.on_iteration(it, CFG)
    assert res is None and tu.trial is not None                       # 회차는 찼어도 10분이 안 지나면 시험 반영 중
    tu.state["trial"]["started_ts"] = _t.time() - 601
    assert tu.on_iteration(its(1)[0], CFG)[0] == "applied"


def test_repair_sentence_plain_words():
    from engine.runner import repair_sentence
    s = repair_sentence("confidence", "applied", "시험/고침_확인버튼.png", 0.8, 0.77)
    assert "확정" in s and "고침_확인버튼" in s and "0.80 → 0.77" in s and "confidence" not in s
    assert "recapture" not in repair_sentence("recapture", "applied", "a/b__고침1117.png")
