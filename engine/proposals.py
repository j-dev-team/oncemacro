"""
구조 수정 제안과 승인 대기함(2026-11-17, 스스로 고치기 4단계).

매크로 구조(스텝 추가 등)를 바꾸는 고침은 절대 자동으로 반영하지 않는다. 제안으로만 쌓고, 사람이 승인해야 반영한다.
승인 전에는 원본 매크로가 그대로 돈다. 거절한 제안과 같은 내용(지문)은 다시 올리지 않는다.

지금 만드는 제안: '자주 쓰이는 막힘 해결 규칙을 매크로에 붙박이 스텝으로' —
막혔을 때마다 저장된 해결(rescues)이 N번 이상 쓰였으면, 그 해결 스텝을 막히던 스텝 앞에 넣자고 제안한다.
(그 해결은 처음 한 번 AI가 내고 검증된 것. 허용 동작·금지 검사를 이미 통과했다.)

저장: <매크로 폴더>/_fixes/<매크로>_proposals.json (예전 판: _고침/<매크로>_제안.json, 있으면 그대로 씀)  [{id, macro, kind, path, steps, why, source, status, created, fp}]
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import time
from typing import Any, List, Optional


def _file(root: str, macro: str) -> str:
    safe = "".join(ch for ch in macro if ch not in '\\/:*?"<>|')
    from .fsnames import pick
    d = pick(root, "_고침")                              # 11-24: 새로 쓰는 곳은 _fixes(예전 _고침 이 있으면 그대로)
    old = os.path.join(d, safe + "_제안.json")
    return old if os.path.exists(old) else os.path.join(d, safe + "_proposals.json")


def load(root: str, macro: str) -> List[dict]:
    try:
        with open(_file(root, macro), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def save(root: str, macro: str, items: List[dict]) -> None:
    p = _file(root, macro)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def load_all(root: str) -> List[dict]:
    import glob
    out: List[dict] = []
    from .fsnames import glob_both
    for fp in glob_both(root, "_고침", ["*_제안.json", "*_proposals.json"]):
        try:
            with open(fp, encoding="utf-8") as fh:
                out += json.load(fh)
        except Exception:
            pass
    out.sort(key=lambda p: p.get("created", ""), reverse=True)
    return out


def pending_count(root: str) -> int:
    return sum(1 for p in load_all(root) if p.get("status") == "pending")


def fingerprint(kind: str, path: str, steps: Any) -> str:
    return hashlib.sha1(json.dumps([kind, path, steps], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def add(root: str, macro: str, kind: str, path: str, steps: list, why: str, source: str,
        summary: str = "") -> Optional[dict]:
    """제안 추가. 같은 내용이 대기 중이거나, 거절됐거나, 이미 승인됐으면 올리지 않음(None)."""
    items = load(root, macro)
    fp = fingerprint(kind, path, steps)
    if any(p.get("fp") == fp for p in items):
        return None
    p = {"id": f"{int(time.time() * 1000)}", "macro": macro, "kind": kind, "path": path, "steps": steps,
         "why": why, "summary": summary, "source": source, "status": "pending", "created": time.strftime("%Y-%m-%d %H:%M:%S"), "fp": fp}
    items.append(p)
    save(root, macro, items)
    return p


def _locate(macro: dict, path: str):
    """'steps[2].then[0]' → (그 스텝이 든 목록, 번호)."""
    parts = re.findall(r"(\w+)\[(\d+)\]", path)
    if not parts:
        return None, None
    cur: Any = macro
    lst = None
    idx = None
    for i, (key, num) in enumerate(parts):
        lst = cur.get(key) if isinstance(cur, dict) else None
        if not isinstance(lst, list):
            return None, None
        idx = int(num)
        if idx >= len(lst):
            return None, None
        if i < len(parts) - 1:
            cur = lst[idx]
    return lst, idx


def apply(macro: dict, proposal: dict) -> dict:
    """제안을 반영한 새 매크로(원본은 그대로)."""
    m = copy.deepcopy(macro)
    lst, idx = _locate(m, proposal["path"])
    if lst is None:
        raise ValueError("path")
    new = copy.deepcopy(proposal["steps"])
    for s in new:
        from .i18n import t
        s.setdefault("note", t("자동 제안으로 추가"))
    if proposal["kind"] == "insert_before":
        lst[idx:idx] = new
    elif proposal["kind"] == "insert_after":
        lst[idx + 1:idx + 1] = new
    else:
        raise ValueError(proposal["kind"])
    return m


def decide(root: str, library, proposal_id: str, approve: bool) -> dict:
    """승인(백업 뒤 반영) 또는 거절. 돌려줌: 바뀐 제안."""
    from .model import ensure_valid
    for macro in {p["macro"] for p in load_all(root) if p.get("id") == proposal_id}:
        items = load(root, macro)
        for p in items:
            if p.get("id") != proposal_id:
                continue
            if p.get("status") != "pending":
                return p
            if approve:
                cur = library.load(macro)
                new = ensure_valid(apply(cur, p))
                path_for = getattr(library, "path_for", None)
                if path_for and os.path.exists(path_for(macro)):
                    src = path_for(macro)
                    bdir = os.path.join(os.path.dirname(src), "_backup")
                    os.makedirs(bdir, exist_ok=True)
                    safe = "".join(ch for ch in macro if ch not in '\\/:*?"<>|')
                    p["backup"] = os.path.join(bdir, f"{safe}_{time.strftime('%Y%m%d_%H%M%S')}_before_proposal.json")
                    shutil.copy2(src, p["backup"])
                library.save(new)
                p["status"] = "approved"
            else:
                p["status"] = "rejected"
            p["decided"] = time.strftime("%Y-%m-%d %H:%M:%S")
            save(root, macro, items)
            return p
    raise KeyError(proposal_id)
