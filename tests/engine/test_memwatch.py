"""값 지켜보기: 규칙대로 읽어 기록·시간당 변화·조건이 거짓→참으로 바뀔 때 한 번만 실행."""
import pytest

from engine import memory as mm
from engine import memwatch as mw


class R:
    def __init__(self):
        self.v = 100

    def value(self, spec):
        return self.v


def test_watch_records_and_fires_once(tmp_path):
    root = str(tmp_path)
    mm.save_value("돈", {"process": "g.exe", "offset": 1, "kind": "int32"}, root=root)
    mw.save_rules([{"name": "돈", "every": 1, "on": True, "when": {"op": "ge", "value": 120},
                    "do": {"macro": "팔기", "notify": True}}], root=root)
    now = [1000.0]
    ran, told = [], []
    r = R()
    w = mw.Watcher(run_macro=ran.append, notify=lambda a, b: told.append(b), root=root, clock=lambda: now[0],
                   reader_for=lambda spec: r)
    for v in (100, 110, 125, 130, 90, 140):
        r.v = v
        now[0] += 900
        w.tick()
    assert ran == ["팔기", "팔기"]                    # 125 에서 한 번, 90 으로 내려갔다 140 에서 다시 한 번
    pts = mw.history("돈", root=root)
    assert [v for _, v in pts] == [100, 110, 125, 130, 90, 140]
    assert mw.per_hour(pts) == pytest.approx(40 / (4500 / 3600))


def test_changed_rule_and_off(tmp_path):
    root = str(tmp_path)
    mm.save_value("hp", {"offset": 1}, root=root)
    mw.save_rules([{"name": "hp", "every": 1, "when": {"op": "changed"}, "do": {"notify": True}}], root=root)
    now = [0.0]
    told = []
    r = R()
    w = mw.Watcher(notify=lambda a, b: told.append(b), root=root, clock=lambda: now[0], reader_for=lambda s: r)
    for v in (5, 5, 6):
        r.v = v
        now[0] += 2
        w.tick()
    assert told == ["hp = 6"]
    mw.save_rules([{"name": "hp", "every": 1, "on": False}], root=root)
    now[0] += 2
    assert w.tick() == {}
