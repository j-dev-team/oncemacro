"""막히면 AI 한 번 부르기(engine/rescue.py) 시험. 가짜 화면·가짜 AI, 실제 입력 없음."""
import copy
import json

import numpy as np
import pytest

from engine import Runner, new_macro
from engine.backends import FakeClock, FakeInput, FakeVision, FakeWindow
from engine.library import DictLibrary
from engine.rescue import SAME_SCREEN as SAME, Limits, Rescuer, check_safe, distance, fingerprint, parse_answer

OK = "test/ok.png"
CLOSE_AT = (10, 10)


class SaveLibrary(DictLibrary):
    def save(self, macro):
        self.macros[macro["name"]] = copy.deepcopy(macro)
        return macro["name"]

    def load(self, name):
        return copy.deepcopy(super().load(name))


class PopupVision(FakeVision):
    """안내창이 떠 있으면 'ok' 버튼이 안 보임. 화면 그림도 안내창 유무에 따라 다름."""

    def __init__(self, clock, world):
        super().__init__(clock)
        self.world = world

    def grab(self, region):
        img = np.zeros((80, 120), np.uint8)
        img[:, :60] = 200                                  # 바탕: 왼쪽 밝음
        if self.world.popup:
            img[20:60, 30:90] = 255 - img[20:60, 30:90]    # 가운데 안내창(밝기 뒤집힘)
            img[25:30, 80:88] = 90
        return img

    def save_region(self, region, path):
        open(path, "wb").write(b"png")
        return path

    def screen_rect(self):
        return (0, 0, 120, 80)


class FakeAI:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.prompts = []

    def available(self):
        return True

    def consented(self):
        return self.consent

    consent = True

    def ask(self, prompt, image, workdir):
        self.calls += 1
        self.prompts.append(prompt)
        return self.answer


class World:
    def __init__(self, tmp_path, answer='{"steps": [{"type": "click", "target": {"point": [10, 10]}}], "why": "닫기"}',
                 ai_on=True, **cfg):
        self.popup = True
        self.clock = FakeClock()
        self.vision = PopupVision(self.clock, self)
        self.input = FakeInput(self.clock)
        self.input.on_click = self._clicked
        self.library = SaveLibrary()
        self.ai = FakeAI(answer)
        self.rescuer = Rescuer(str(tmp_path / "rescue"), ai=self.ai, library=self.library,
                               image_exists=lambda p: False, now=lambda: 1_000_000.0)
        self.events = []
        m = new_macro("m", [{"type": "click", "id": "ok", "target": {"image": OK}, "timeout": 1}],
                      description="안내창을 닫고 확인 누르기",
                      ai_rescue={"on": ai_on, **cfg})
        self.library.add(m)

    def _clicked(self, pos, button):
        if pos == CLOSE_AT and self.popup:
            self.popup = False
            self.vision.show(OK, (50, 50), start=self.clock.now())

    def reset_popup(self):
        self.popup = True
        self.vision.items.clear()

    def run(self):
        r = Runner(self.library.load("m"), vision=self.vision, input=self.input, clock=self.clock,
                   library=self.library, on_event=self.events.append, rescuer=self.rescuer)
        return r.run()


def test_ai_fix_saved_then_reused_without_ai(tmp_path):
    w = World(tmp_path)
    res = w.run()
    assert res.status == "ok" and w.ai.calls == 1
    saved = w.library.macros["m"]["rescues"]
    assert len(saved) == 1 and saved[0]["step"] == "ok" and saved[0]["steps"][0]["target"]["point"] == [10, 10]
    assert "안내창을 닫고 확인 누르기" in w.ai.prompts[0]          # 목적이 AI 에게 감
    # 같은 상황 재현 → AI 없이 통과
    w.reset_popup()
    res = w.run()
    assert res.status == "ok" and w.ai.calls == 1
    assert any(e.get("event") == "rescue" and e.get("how") == "rule" for e in w.events)
    log = [json.loads(x) for x in open(tmp_path / "rescue" / "log.jsonl", encoding="utf-8")]
    assert [x["how"] for x in log] == ["ai_saved", "rule"]


def test_off_by_default_fails_like_before(tmp_path):
    w = World(tmp_path, ai_on=False)
    res = w.run()
    assert res.status == "failed" and w.ai.calls == 0


def test_forbidden_suggestion_discarded(tmp_path):
    w = World(tmp_path, answer='{"steps": [{"type": "click", "target": {"point": [10, 10]}, "note": "보석 구매"}]}')
    res = w.run()
    assert res.status == "failed" and w.ai.calls == 1
    assert "rescues" not in w.library.macros["m"]
    log = [json.loads(x) for x in open(tmp_path / "rescue" / "log.jsonl", encoding="utf-8")]
    assert log[0]["how"] == "ai_rejected" and {x["how"] for x in log[1:]} <= {"blocked"}   # 다음 회차는 같은 화면이라 안 부름


def test_forbidden_region(tmp_path):
    w = World(tmp_path, forbid_regions=[[0, 0, 20, 20]])
    assert w.run().status == "failed" and "rescues" not in w.library.macros["m"]


def test_same_screen_not_called_twice(tmp_path):
    w = World(tmp_path, answer='{"steps": [{"type": "key", "keys": "esc"}]}')    # 안 풀리는 답
    assert w.run().status == "failed"
    calls = w.ai.calls
    w.run()
    assert w.ai.calls == calls                     # 같은 스텝·같은 화면 → 다시 안 부름


def test_hourly_limit(tmp_path):
    lim = Limits(str(tmp_path / "c.json"), now=lambda: 5000.0)
    lim.record("a", "0" * 16, False)
    assert lim.blocked({"per_hour": 1, "per_day": 10}, "b", "f" * 16)
    assert lim.blocked({"per_hour": 5, "per_day": 10}, "b", "f" * 16) is None


def test_ai_missing_keeps_old_behavior(tmp_path):
    w = World(tmp_path)
    w.ai.available = lambda: False
    res = w.run()
    assert res.status == "failed" and w.ai.calls == 0


def test_ai_crash_keeps_old_behavior(tmp_path):
    w = World(tmp_path)

    def boom(*a):
        raise RuntimeError("연결 끊김")
    w.ai.ask = boom
    assert w.run().status == "failed"


def test_parse_and_safety_helpers():
    steps, why = parse_answer('설명…\n```json\n{"steps": [{"type": "key", "keys": "esc"}], "why": "x"}\n```')
    assert steps == [{"type": "key", "keys": "esc"}] and why == "x"
    assert check_safe([{"type": "launch", "target": "a.exe"}], {})
    assert check_safe([{"type": "web", "action": "fill", "selector": "#password", "text": "x"}], {})
    assert not check_safe([{"type": "key", "keys": "esc"}], {})
    a = np.zeros((40, 40), np.uint8)
    b = a.copy()
    b[:, 20:] = 255
    assert distance(fingerprint(a), fingerprint(a)) == 0 and distance(fingerprint(a), fingerprint(b)) > 0


def test_no_consent_no_call(tmp_path):
    w = World(tmp_path)
    w.ai.consent = False
    assert w.run().status == "failed" and w.ai.calls == 0


def test_allowlist_and_limits():
    assert check_safe([{"type": "web", "action": "goto", "url": "https://x"}], {})           # 웹 이동 금지
    assert check_safe([{"type": "type_text", "text": "x" * 31}], {})                         # 대량 입력 금지
    assert check_safe([{"type": "delay", "seconds": 1}] * 6, {})                              # 5개까지
    assert not check_safe([{"type": "type_text", "text": "short"}, {"type": "delay", "seconds": 1}], {})


def test_saved_rule_turned_off_after_repeated_failure(tmp_path):
    w = World(tmp_path)
    assert w.run().status == "ok"                  # AI 해결 저장
    w.ai.answer = '{"steps": []}'
    w.input.on_click = lambda pos, b: None         # 이제 그 해결이 안 통하는 화면
    for _ in range(3):
        w.reset_popup()
        w.run()
    rule = w.library.macros["m"]["rescues"][0]
    assert rule.get("off") is True and rule.get("fails") == 3
    log = [json.loads(x) for x in open(tmp_path / "rescue" / "log.jsonl", encoding="utf-8")]
    assert any(x["how"] == "rule_off" for x in log)


def test_fingerprint_tolerates_small_changes_but_not_other_screens():
    rng = np.random.default_rng(1)
    base = np.full((600, 800), 230, np.uint8)
    base[150:450, 200:600] = 120                    # 가운데 창
    base[180:200, 220:580] = 40                     # 창 제목줄
    clock = base.copy()
    clock[560:590, 700:790] = rng.integers(0, 255, (30, 90))     # 시계·숫자 변함
    anim = base.copy()
    anim[300:340, 380:420] = 255                    # 작은 반짝임
    noisy = np.clip(base.astype(int) + rng.integers(-6, 7, base.shape), 0, 255).astype(np.uint8)
    other = np.full((600, 800), 230, np.uint8)
    other[50:250, 450:780] = 90                     # 다른 자리의 다른 창
    fb = fingerprint(base)
    for img in (clock, anim, noisy):
        assert distance(fb, fingerprint(img)) <= SAME
    assert distance(fb, fingerprint(other)) > SAME


def test_rule_skipped_when_window_size_differs(tmp_path):
    w = World(tmp_path)
    assert w.run().status == "ok" and w.ai.calls == 1
    assert w.library.macros["m"]["rescues"][0]["size"] == [120, 80]
    w.reset_popup()
    w.vision.screen_rect = lambda: (0, 0, 100, 80)      # 창 크기가 바뀜 → 저장된 고정 좌표 규칙은 안 씀
    assert w.run().status == "ok" and w.ai.calls == 2  # 한도 안에서 AI 를 다시 부름


def test_ai_gets_only_its_own_folder(tmp_path):
    w = World(tmp_path)
    seen = {}

    def ask(prompt, image, workdir):
        import os
        seen["files"] = os.listdir(workdir)
        seen["image_in_dir"] = os.path.dirname(image) == workdir
        return '{"steps": [{"type": "click", "target": {"point": [10, 10]}}]}'
    w.ai.ask = ask
    assert w.run().status == "ok"
    assert seen["files"] == ["screen.png"] and seen["image_in_dir"]
