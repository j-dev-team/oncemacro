"""
편집기용 매크로 모델 (Qt 없음).

원칙: 원본 JSON 을 깊은 복사해 들고 있고, 편집기는 자기가 아는 키만 덮어쓴다.
모르는 키·null 값·키 순서는 그대로 유지되므로, 아무것도 안 고치고 저장하면 원본과 똑같다.

- StepNode: 스텝 하나. 자식 스텝 목록(if 의 then/else, repeat·group 의 steps)은 branches 로 따로 둔다.
- MacroModel: 매크로 전체(steps 를 뺀 나머지 = meta).
- 경로(path)는 엔진 실행 기록과 같은 형식: steps[0].then[1].steps[2]
"""
from __future__ import annotations

import copy
from typing import Dict, Iterator, List, Tuple

from .i18n import tr

# 스텝 종류별 자식 목록 키
CHILD_KEYS: Dict[str, Tuple[str, ...]] = {
    "if": ("then", "else"),
    "repeat": ("steps",),
    "group": ("steps",),
    "for_each": ("steps",),
    "each": ("steps",),
}
# 새로 만들 때 반드시 있어야 하는 자식 목록
REQUIRED_CHILDREN: Dict[str, Tuple[str, ...]] = {
    "if": ("then",),
    "repeat": ("steps",),
    "group": ("steps",),
    "for_each": ("steps",),
    "each": ("steps",),
}


class StepNode:
    __slots__ = ("data", "branches", "order")

    def __init__(self, step: dict):
        step = copy.deepcopy(step)
        self.order: List[str] = list(step.keys())
        keys = CHILD_KEYS.get(step.get("type"), ())
        self.branches: Dict[str, List["StepNode"]] = {}
        for k in keys:
            if k in step and isinstance(step[k], list):
                self.branches[k] = [StepNode(s) for s in step.pop(k)]
        self.data: dict = step

    # ------------------------------------------------------------ 기본
    @property
    def type(self) -> str:
        return self.data.get("type", "")

    def child_keys(self) -> Tuple[str, ...]:
        return CHILD_KEYS.get(self.type, ())

    def is_container(self) -> bool:
        return bool(self.child_keys())

    def children(self, key: str, create: bool = False) -> List["StepNode"]:
        if key not in self.branches:
            if not create:
                return []
            self.branches[key] = []
        return self.branches[key]

    def to_dict(self) -> dict:
        keys = list(self.order)
        for k in list(self.data) + list(self.branches):
            if k not in keys:
                keys.append(k)
        out = {}
        for k in keys:
            if k in self.branches:
                out[k] = [c.to_dict() for c in self.branches[k]]
            elif k in self.data:
                out[k] = copy.deepcopy(self.data[k])
        return out

    def clone(self) -> "StepNode":
        return StepNode(self.to_dict())

    # ------------------------------------------------------------ 편집
    def set_field(self, key: str, value) -> None:
        """값 넣기. 자식 목록 키는 여기서 다루지 않는다."""
        self.data[key] = copy.deepcopy(value)

    def remove_field(self, key: str) -> None:
        self.data.pop(key, None)

    def set_type(self, new_type: str) -> List["StepNode"]:
        """종류 바꾸기. 새 종류에 맞지 않는 자식 목록은 버리고, 버린 자식들을 돌려준다(호출 쪽에서 경고용)."""
        if new_type == self.type:
            return []
        dropped: List[StepNode] = []
        keep = CHILD_KEYS.get(new_type, ())
        # repeat ↔ group 은 steps 를 그대로 둔다. if → repeat/group 은 then 을 steps 로, 반대는 steps 를 then 으로.
        if "steps" in keep and "steps" not in self.branches and "then" in self.branches:
            self.branches["steps"] = self.branches.pop("then")
        if "then" in keep and "then" not in self.branches and "steps" in self.branches:
            self.branches["then"] = self.branches.pop("steps")
        for k in list(self.branches):
            if k not in keep:
                dropped.extend(self.branches.pop(k))
        for k in REQUIRED_CHILDREN.get(new_type, ()):
            self.branches.setdefault(k, [])
        self.data["type"] = new_type
        return dropped


class MacroModel:
    def __init__(self, macro: dict):
        macro = copy.deepcopy(macro)
        self.order: List[str] = list(macro.keys())
        self.steps: List[StepNode] = [StepNode(s) for s in macro.pop("steps", [])]
        self.meta: dict = macro

    def to_dict(self) -> dict:
        keys = list(self.order)
        for k in list(self.meta) + ["steps"]:
            if k not in keys:
                keys.append(k)
        out = {}
        for k in keys:
            if k == "steps":
                out["steps"] = [s.to_dict() for s in self.steps]
            elif k in self.meta:
                out[k] = copy.deepcopy(self.meta[k])
        return out


# ---------------------------------------------------------------- 경로

def walk(steps: List[StepNode], prefix: str = "steps") -> Iterator[Tuple[str, StepNode]]:
    """(엔진 경로, 노드) 를 깊이 우선으로."""
    for i, node in enumerate(steps):
        path = f"{prefix}[{i}]"
        yield path, node
        for k in node.child_keys():
            if k in node.branches:
                yield from walk(node.branches[k], f"{path}.{k}")


def walk_dict(steps: list, prefix: str = "steps") -> Iterator[Tuple[str, dict]]:
    """JSON 스텝 목록을 (경로, 스텝 dict) 로 깊이 우선 순회."""
    for i, s in enumerate(steps or []):
        path = f"{prefix}[{i}]"
        yield path, s
        if isinstance(s, dict):
            for k in CHILD_KEYS.get(s.get("type"), ()):
                if isinstance(s.get(k), list):
                    yield from walk_dict(s[k], f"{path}.{k}")


def default_step(step_type: str) -> dict:
    """새 스텝의 기본값."""
    d: dict = {"type": step_type}
    if step_type in ("click", "move"):
        d["target"] = {"point": [0, 0]}
    elif step_type == "scroll":
        d["amount"] = -3
    elif step_type == "menu":
        d["path"] = tr("파일 > 새로 만들기")
    elif step_type == "drag":
        d["from"] = {"point": [0, 0]}
        d["to"] = {"point": [100, 0]}
    elif step_type == "key":
        d["keys"] = "enter"
    elif step_type == "type_text":
        d["text"] = ""
    elif step_type == "wait":
        d["until"] = {"exists": {"image": ""}}
        d["timeout"] = 10
    elif step_type == "delay":
        d["seconds"] = 1.0
    elif step_type == "remember":
        d["var"] = tr("위치")
        d["what"] = "mouse"
    elif step_type == "if":
        d["cond"] = {"exists": {"image": ""}}
        d["then"] = []
    elif step_type == "repeat":
        d["times"] = 2
        d["steps"] = []
    elif step_type == "group":
        d["steps"] = []
    elif step_type == "launch":
        d["target"] = ""
    elif step_type == "snapshot":
        d["name"] = tr("화면")
    elif step_type == "web":
        d["action"] = "goto"
        d["url"] = "https://"
    elif step_type in ("excel", "word", "hwp"):
        d["action"] = "open"
        d["path"] = tr("파일 > 새로 만들기")
    elif step_type == "for_each":
        d["var"] = tr("카드")
        d["target"] = {"image": ""}
        d["steps"] = []
    elif step_type == "call":
        d["macro"] = ""
    elif step_type == "set_result":
        d["value"] = ""
    elif step_type == "text":
        d["var"] = tr("글자")
        d["text"] = ""
    elif step_type == "date":
        d["var"] = tr("오늘")
        d["format"] = "yyyy-MM-dd"
    elif step_type == "calc":
        d["var"] = tr("결과")
        d["expr"] = ""
    elif step_type == "clipboard":
        d["action"] = "copy"
        d["var"] = tr("복사한글")
    elif step_type == "list":
        d["var"] = tr("목록")
        d["action"] = "add"
        d["value"] = ""
    elif step_type == "mail":
        d["via"] = "outlook"
        d["action"] = "find"
        d["var"] = tr("메일들")
    elif step_type == "pdf":
        d["path"] = ""
        d["var"] = tr("글")
    elif step_type == "memory":
        d["action"] = "read"
        d["value"] = ""
        d["var"] = tr("값")
    elif step_type == "ask":
        d["kind"] = "input"
        d["var"] = tr("답")
        d["message"] = ""
    elif step_type == "notify":
        d["message"] = ""
    elif step_type == "each":
        d["var"] = tr("항목")
        d["list"] = ""
        d["steps"] = []
    elif step_type == "file":
        d["action"] = "copy"
        d["path"] = ""
        d["to"] = ""
    elif step_type == "set":
        d["var"] = tr("횟수")
        d["add"] = 1
    elif step_type == "return":
        pass
    elif step_type == "stop":
        d["reason"] = ""
    elif step_type == "comment":
        d["text"] = ""
    return d
