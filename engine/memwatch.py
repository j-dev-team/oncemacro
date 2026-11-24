"""메모리 매크로 5번: 값 지켜보기·기록·조건 실행. Qt 없음.

규칙(memory/watch.json): [{name(저장한 값 이름), every(초), when: {op: ge|le|gt|lt|eq|ne|changed, value}, do: {macro?, notify?}, on}]
- 지켜보는 값은 logs/memory/watch/<이름>.jsonl 에 {t, v} 로 쌓인다(그래프·시간당 변화).
- 조건이 '거짓 → 참'으로 바뀌는 순간 한 번 실행(계속 참이면 다시 안 함).
읽기만 한다(값 쓰기 없음).
"""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List, Optional

from .memory import MemoryError_, load_values, pid_of_process, ProcessReader, _root


def rules_path(root: Optional[str] = None) -> str:
    return os.path.join(_root(root), "memory", "watch.json")


def load_rules(root: Optional[str] = None) -> List[dict]:
    try:
        with open(rules_path(root), encoding="utf-8") as f:
            d = json.load(f)
        return [r for r in d if isinstance(r, dict) and r.get("name")] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def save_rules(rules: List[dict], root: Optional[str] = None):
    p = rules_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=1)


def history_path(name: str, root: Optional[str] = None) -> str:
    safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in name)
    return os.path.join(_root(root), "logs", "memory", "watch", safe + ".jsonl")


def history(name: str, since: float = 0, root: Optional[str] = None) -> List[tuple]:
    out = []
    try:
        with open(history_path(name, root), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("t", 0) >= since:
                    out.append((d["t"], d["v"]))
    except OSError:
        pass
    return out


def per_hour(points: List[tuple]) -> Optional[float]:
    """처음과 마지막 값으로 시간당 변화(값이 숫자일 때)."""
    pts = [(t_, v) for t_, v in points if isinstance(v, (int, float))]
    if len(pts) < 2 or pts[-1][0] - pts[0][0] < 60:
        return None
    return (pts[-1][1] - pts[0][1]) / ((pts[-1][0] - pts[0][0]) / 3600.0)


def _test(op: str, cur, ref, prev) -> bool:
    if op == "changed":
        return prev is not None and cur != prev
    try:
        a, b = float(cur), float(ref)
    except (TypeError, ValueError):
        return op == "eq" and cur == ref or op == "ne" and cur != ref
    return {"ge": a >= b, "le": a <= b, "gt": a > b, "lt": a < b, "eq": a == b, "ne": a != b}.get(op, False)


class Watcher:
    """규칙대로 값을 읽고(정한 간격) 기록·조건 실행. tick() 을 자주(1~2초) 부르면 된다."""

    def __init__(self, run_macro: Callable[[str], None] = lambda n: None,
                 notify: Callable[[str, str], None] = lambda title, msg: None, root: Optional[str] = None,
                 clock: Callable[[], float] = time.time, reader_for: Optional[Callable] = None):
        self.run_macro, self.notify, self.root, self.clock = run_macro, notify, root, clock
        self.reader_for = reader_for or self._reader
        self.readers: Dict[int, ProcessReader] = {}
        self.last_read: Dict[str, float] = {}
        self.last_val: Dict[str, object] = {}
        self.last_hit: Dict[str, bool] = {}

    def _reader(self, spec):
        pid = pid_of_process(spec["process"]) if spec.get("process") else None
        if not pid:
            return None
        r = self.readers.get(pid)
        if r is None:
            r = self.readers[pid] = ProcessReader(pid)
        return r

    def tick(self) -> Dict[str, object]:
        """돌려줌: {이름: 지금 값} (이번에 읽은 것)."""
        now = self.clock()
        rules = [r for r in load_rules(self.root) if r.get("on", True)]
        vals = load_values(self.root)
        got = {}
        for rule in rules:
            name = rule["name"]
            if now - self.last_read.get(name, 0) < float(rule.get("every", 5)):
                continue
            self.last_read[name] = now
            spec = vals.get(name)
            if not spec:
                continue
            try:
                r = self.reader_for(spec)
                if r is None:
                    continue
                v = r.value(spec)
            except MemoryError_:
                continue
            got[name] = v
            p = history_path(name, self.root)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(now, 1), "v": v}, ensure_ascii=False) + "\n")
            when = rule.get("when") or {}
            if when.get("op"):
                hit = _test(when["op"], v, when.get("value"), self.last_val.get(name))
                if hit and not self.last_hit.get(name, False):
                    do = rule.get("do") or {}
                    if do.get("macro"):
                        self.run_macro(do["macro"])
                    if do.get("notify", True):
                        self.notify(name, f"{name} = {v}")
                self.last_hit[name] = hit
            self.last_val[name] = v
        return got

    def close(self):
        for r in self.readers.values():
            try:
                r.close()
            except Exception:
                pass
        self.readers.clear()
