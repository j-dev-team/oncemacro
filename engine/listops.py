"""목록 단계(Qt 없음): 목록에 하나씩 더하기(중복 빼기 선택) · 정렬(여러 칸, 숫자·날짜·글자) · 비우기 · 중복 빼기 · 개수."""
from __future__ import annotations

import functools
from typing import Any, Dict, List

from .i18n import t
from .textops import TextOpError, fill, lookup, parse_date, to_number

ACTIONS = ("add", "sort", "clear", "unique", "count")
_ABSENT = object()


def build_item(spec: Any, vars_: Dict[str, Any]) -> Any:
    """더할 것: 글자(안의 {변수} 채움) / {"칸": "{변수}", ...}(줄 하나). 값이 '{이름}' 하나뿐이면 원래 값(숫자 등)을 그대로."""
    if isinstance(spec, dict):
        if set(spec) == {"var"}:
            return lookup(vars_, spec["var"], None)
        return {str(k): build_item(v, vars_) for k, v in spec.items()}
    if isinstance(spec, str):
        s = spec.strip()
        if s.startswith("{") and s.endswith("}") and s.count("{") == 1:
            v = lookup(vars_, s[1:-1], _ABSENT)
            if v is not _ABSENT:
                return v
        out, missing = fill(spec, vars_)
        if missing:
            raise TextOpError(t("변수 '{name}' 가 없음", name=missing[0]))
        return out
    return spec


def _key_value(item: Any, key: str):
    if key in (None, "", "."):
        return item
    if isinstance(item, dict):
        return lookup(item, key, None)
    return None


def _kind_of(values: List[Any]) -> str:
    vals = [v for v in values if v not in (None, "")]
    if not vals:
        return "text"
    try:
        for v in vals:
            if isinstance(v, bool):
                raise TextOpError("")
            to_number(v)
        return "number"
    except TextOpError:
        pass
    try:
        for v in vals:
            parse_date(v)
        return "date"
    except TextOpError:
        return "text"


def sort_items(items: List[Any], keys: List[dict]) -> List[Any]:
    """keys: [{"key": 칸 이름(비우면 값 자체), "order": "asc|desc", "as": "auto|number|date|text"}] — 앞 칸이 먼저."""
    keys = keys or [{"key": "", "order": "asc"}]
    kinds = []
    for k in keys:
        as_ = k.get("as", "auto")
        kinds.append(_kind_of([_key_value(it, k.get("key", "")) for it in items]) if as_ == "auto" else as_)

    def conv(v, kind):
        if v in (None, ""):
            return None
        try:
            if kind == "number":
                return to_number(v)
            if kind == "date":
                return parse_date(v)
        except TextOpError:
            return None
        return str(v)

    def cmp(a, b):
        for k, kind in zip(keys, kinds):
            va, vb = conv(_key_value(a, k.get("key", "")), kind), conv(_key_value(b, k.get("key", "")), kind)
            if va == vb:
                continue
            if va is None:                      # 빈 값은 늘 뒤로
                return 1
            if vb is None:
                return -1
            r = -1 if va < vb else 1
            return -r if k.get("order") == "desc" else r
        return 0
    return sorted(items, key=functools.cmp_to_key(cmp))


def unique(items: List[Any]) -> List[Any]:
    import json
    seen, out = set(), []
    for it in items:
        k = json.dumps(it, ensure_ascii=False, sort_keys=True, default=str)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out
