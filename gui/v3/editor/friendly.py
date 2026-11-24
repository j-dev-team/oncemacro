"""엔진 검사 오류(경로·개발자 말)를 처음 쓰는 사람이 읽을 수 있는 말로. Qt 없음.

엔진 검사는 그대로 두고(저장·실행·시험을 막는 기준), 보여 주는 글만 바꾼다. 원래 글은 툴팁에 남긴다.
"""
from __future__ import annotations

import re
from typing import Optional

from gui.v2.describe import step_name
from gui.v2.i18n import tr
from gui.v2.model import walk_dict



def _step_path(err: str):
    """'steps[0].then[1].target.image: 메시지' → ('steps[0].then[1]', '.target.image', '메시지')."""
    m = re.match(r"^(steps\[\d+\](?:\.(?:steps|then|else)\[\d+\])*)((?:\.\w+)*(?:\[\d+\])?(?:\.\w+)*)\s*:\s*(.*)$", err)
    if not m:
        return None, "", err
    return m.group(1), m.group(2) or "", m.group(3)


def step_number(path: str) -> str:
    """'steps[2].then[0]' → '3-1'."""
    return "-".join(str(int(n) + 1) for n in re.findall(r"\[(\d+)\]", path))


def _find(macro: dict, path: str) -> Optional[dict]:
    for p, s in walk_dict(macro.get("steps") or []):
        if p == path:
            return s if isinstance(s, dict) else None
    return None


def _what(step_type: str, field: str) -> str:
    """빈 대상이 무엇을 뜻하는지 스텝 종류별로."""
    if field.startswith(".from"):
        return tr("끌기 시작할 곳을 아직 안 정했어요 — 오른쪽 '화면에서 찍기'를 누르세요")
    if field.startswith(".to"):
        return tr("끌어다 놓을 곳을 아직 안 정했어요 — 오른쪽 '화면에서 찍기'를 누르세요")
    if step_type == "move":
        return tr("마우스를 옮길 곳을 아직 안 정했어요 — 오른쪽 '화면에서 찍기'를 누르세요")
    return tr("누를 곳을 아직 안 정했어요 — 오른쪽 '화면에서 찍기'를 누르세요")


def friendly(err: str, macro: dict) -> str:
    """오류 한 줄 → 쉬운 말 한 줄. 모르는 오류는 '몇 번 스텝: 원래 설명' 으로."""
    path, field, msg = _step_path(err)
    if path is None:
        return err
    step = _find(macro, path) or {}
    typ = step.get("type", "")
    head = tr("{n}번 {name}").format(n=step_number(path), name=step_name(typ) if typ else tr("스텝"))
    last = field.rsplit(".", 1)[-1] if field else ""
    if field in (".target", ".from", ".to") and ("객체" in msg or "object" in msg.lower()):
        return f"{head}: {_what(typ, field)}"
    if last == "image" and ("비어" in msg or "empty" in msg.lower()):
        return f"{head}: " + tr("찾을 그림을 아직 안 정했어요 — 오른쪽 '화면에서 자르기'를 누르세요")
    if last in ("macro",) and ("비어" in msg or "필요" in msg):
        return f"{head}: " + tr("부를 매크로를 고르세요")
    return f"{head}: {msg}"


def friendly_list(errs, macro: dict, limit: int = 4) -> str:
    """여러 줄을 <br> 로. 넘치면 '…외 n개'."""
    lines = [friendly(e, macro) for e in errs[:limit]]
    if len(errs) > limit:
        lines.append(tr("…외 {n}개").format(n=len(errs) - limit))
    return lines


_BRANCH = {"then": "그러면 ", "else": "아니면 "}


def where(macro: dict, path: str) -> str:
    """실행 기록용 쉬운 위치: 'steps[11].steps[8].then[2]' → "12번 › 9번 › 그러면 3번 '이름'".
    이름은 스텝 메모(note)가 있으면 그것, 없으면 스텝 종류 이름. 모르는 모양이면 그대로."""
    parts = re.findall(r"(\w+)\[(\d+)\]", path or "")
    if not parts:
        return path or ""
    out = [tr(_BRANCH.get(k, "")) + tr("{n}번").format(n=int(n) + 1) for k, n in parts]
    step = _find(macro, path) if macro else None
    label = ""
    if step:
        label = (step.get("note") or "").strip() or step_name(step.get("type", ""))
    return " › ".join(out) + (f" '{label}'" if label else "")
