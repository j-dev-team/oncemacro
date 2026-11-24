"""구조 수정 제안·승인 대기함(스스로 고치기 4단계). 실제 입력 없음."""
import copy
import json

from engine import proposals as P
from engine.library import DictLibrary
from engine.model import new_macro


class Lib(DictLibrary):
    def save(self, m):
        self.macros[m["name"]] = copy.deepcopy(m)

    def load(self, name):
        return copy.deepcopy(super().load(name))


FIX = [{"type": "click", "target": {"point": [10, 10]}}, {"type": "delay", "seconds": 1}]


def test_add_dedupe_and_reject_not_repeated(tmp_path):
    r = str(tmp_path)
    p = P.add(r, "m", "insert_before", "steps[0]", FIX, "이유", "rule")
    assert p and P.pending_count(r) == 1
    assert P.add(r, "m", "insert_before", "steps[0]", FIX, "이유", "rule") is None      # 같은 내용 대기 중
    lib = Lib()
    lib.add(new_macro("m", [{"type": "click", "target": {"image": "a.png"}}]))
    P.decide(r, lib, p["id"], approve=False)
    assert P.add(r, "m", "insert_before", "steps[0]", FIX, "이유", "rule") is None      # 거절한 것은 다시 안 올림
    assert lib.macros["m"]["steps"][0]["type"] == "click" and len(lib.macros["m"]["steps"]) == 1   # 원본 그대로


def test_approve_inserts_before_step(tmp_path):
    r = str(tmp_path)
    lib = Lib()
    lib.add(new_macro("m", [{"type": "delay", "seconds": 1},
                            {"type": "if", "cond": {"exists": {"image": "x.png"}},
                             "then": [{"type": "click", "target": {"image": "a.png"}}]}]))
    p = P.add(r, "m", "insert_before", "steps[1].then[0]", FIX, "이유", "rule")
    out = P.decide(r, lib, p["id"], approve=True)
    assert out["status"] == "approved"
    then = lib.macros["m"]["steps"][1]["then"]
    assert [s["type"] for s in then] == ["click", "delay", "click"] and then[0]["target"] == {"point": [10, 10]}
    assert P.pending_count(r) == 0


def test_rule_used_often_becomes_proposal(tmp_path):
    import sys
    sys.path.insert(0, "tests/engine")
    from test_rescue import World
    w = World(tmp_path)
    m = w.library.macros["m"]
    m["self_heal"] = {"mode": "propose", "propose_after_uses": 2}
    w.library.macros["m"] = m
    from engine import Runner
    from engine.health import HealthRecorder

    def run():
        r = Runner(w.library.load("m"), vision=w.vision, input=w.input, clock=w.clock, library=w.library,
                   rescuer=w.rescuer, health=HealthRecorder(str(tmp_path / "h"), str(tmp_path / "rep")))
        r.tuning_root = str(tmp_path)
        r.tuning_allowed = True
        return r.run()
    assert run().status == "ok" and w.ai.calls == 1           # 처음: AI 가 풀고 규칙 저장
    for _ in range(2):
        w.reset_popup()
        assert run().status == "ok"                           # 규칙으로 풂(2번)
    assert w.ai.calls == 1
    pend = [p for p in P.load_all(str(tmp_path)) if p["status"] == "pending"]
    assert len(pend) == 1 and pend[0]["path"] == "steps[0]"
    w0 = pend[0]["steps"][0]                                  # 막히던 대상이 안 보일 때만 하도록 감쌈
    assert w0["type"] == "if" and w0["then"][0]["target"]["point"] == [10, 10]
    assert w0["cond"] == {"all": [{"not": {"exists": {"image": "test/ok.png"}}}, {"window_size": [120, 80]}]}   # 배운 창 크기에서만
    assert "rescues" in w.library.macros["m"] and len(w.library.macros["m"]["steps"]) == 1     # 승인 전엔 원본 그대로
