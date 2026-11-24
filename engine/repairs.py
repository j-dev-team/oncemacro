"""
고침 기록(2026-11-17, 스스로 고치기): 알아챈 신호·고친 것·결과를 매크로별 logs/repairs/<매크로>.jsonl 에 한 줄씩.
화면의 '보기 → 고침 기록'이 이것을 읽는다. 상태: notified(알림만) / trial(시험 반영) / applied(확정) /
reverted(되돌림) / pending(승인 대기) / approved / rejected.
"""
from __future__ import annotations

import glob
import json
import os
import time
from typing import List, Optional


def _safe(name: str) -> str:
    return "".join(ch for ch in name if ch not in '\\/:*?"<>|')


def append(root: str, macro: str, kind: str, status: str, detail: Optional[dict] = None, **extra) -> dict:
    rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "macro": macro, "kind": kind, "status": status,
           "detail": detail or {}, **extra}
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, _safe(macro) + ".jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return rec


def load_all(root: str, limit: int = 500) -> List[dict]:
    out: List[dict] = []
    for fp in glob.glob(os.path.join(root, "*.jsonl")):
        try:
            with open(fp, encoding="utf-8") as fh:
                out += [json.loads(x) for x in fh if x.strip()]
        except Exception:
            pass
    out.sort(key=lambda r: r.get("at", ""), reverse=True)
    return out[:limit]
