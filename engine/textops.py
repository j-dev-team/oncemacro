"""글자·날짜·계산 도우미(Qt 없음): 글자 안 {변수} 채우기, '글자 만들기'·'날짜'·'계산' 스텝, 글자 비교 조건.

- fill(): 있는 변수 이름만 바꾸고, 모르는 중괄호는 그대로 둔다(옛 매크로의 글자를 깨지 않게). 못 바꾼 이름을 함께 돌려준다.
- 계산식은 ast 로 숫자·사칙연산·괄호·몇 개 함수만 허용한다(임의 코드 실행 없음).
"""
from __future__ import annotations

import ast
import datetime as _dt
import operator
import re
from typing import Any, Dict, List, Tuple

from .i18n import t

VAR = re.compile(r"\{([^{}\s]+)\}")


class TextOpError(Exception):
    pass


def as_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, tuple)):
        return ", ".join(as_text(x) for x in v)
    if isinstance(v, _dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S") if (v.hour or v.minute or v.second) else v.strftime("%Y-%m-%d")
    return str(v)


_MISSING = object()
_ABSENT = object()      # fill 안에서 '없음' 표시(lookup 의 기본값 표시와 달라야 함)


def lookup(vars_: Dict[str, Any], name: str, default: Any = _MISSING) -> Any:
    """변수 값. '행.이름'·'행.A'(표 한 줄)·'목록.1'(첫째)·'정보.크기' 처럼 점으로 안쪽 값도. 없으면 default(안 주면 KeyError)."""
    if name in vars_:
        return vars_[name]
    if "." in name:
        head, rest = name.split(".", 1)
        if head in vars_:
            cur = vars_[head]
            for part in rest.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                elif isinstance(cur, (list, tuple)) and re.fullmatch(r"-?\d+", part):
                    i = int(part)
                    try:
                        cur = cur[i - 1 if i > 0 else i]
                    except IndexError:
                        break
                else:
                    break
            else:
                return cur
    if default is _MISSING:
        raise KeyError(name)
    return default


def fill(s: Any, vars_: Dict[str, Any]) -> Tuple[Any, List[str]]:
    """문자열 안 {이름} → 변수 값. (결과, 못 찾은 이름 목록). 문자열이 아니면 그대로."""
    if not isinstance(s, str) or "{" not in s:
        return s, []
    missing: List[str] = []

    def rep(m):
        k = m.group(1)
        v = lookup(vars_, k, _ABSENT)
        if v is not _ABSENT:
            return as_text(v)
        missing.append(k)
        return m.group(0)
    return VAR.sub(rep, s), missing


# ---------------------------------------------------------------- 숫자
def to_number(v: Any) -> float:
    """'1,234', ' 12.5 ', '₩3,000', '45%' 같은 글자도 숫자로."""
    if isinstance(v, bool):
        raise TextOpError(t("숫자가 아님: {value}", value=v))
    if isinstance(v, (int, float)):
        return v
    s = as_text(v).strip().replace(",", "")
    s = re.sub(r"^[^\d\-+.]+|[^\d.]+$", "", s)
    try:
        f = float(s)
    except ValueError:
        raise TextOpError(t("숫자가 아님: {value}", value=v))
    return int(f) if f.is_integer() and "." not in s else f


def _tidy(n):
    if isinstance(n, float) and n.is_integer() and abs(n) < 1e15:
        return int(n)
    if isinstance(n, float):
        return round(n, 10)
    return n


# ---------------------------------------------------------------- 글자 만들기
TEXT_ACTIONS = ("set", "replace", "extract", "split", "slice", "trim", "upper", "lower", "length", "number", "join",
                "pad")


def text_op(action: str, text: str, step: dict, vars_: Dict[str, Any]) -> Any:
    a = action or "set"
    if a == "set":
        return text
    if a == "trim":
        return text.strip()
    if a == "upper":
        return text.upper()
    if a == "lower":
        return text.lower()
    if a == "length":
        return len(text)
    if a == "number":
        return to_number(text)
    if a == "replace":
        find = fill(step.get("find", ""), vars_)[0]
        to = fill(step.get("with", ""), vars_)[0]
        if step.get("regex"):
            try:
                return re.sub(find, to, text)
            except re.error as e:
                raise TextOpError(t("찾는 규칙(정규식)이 잘못됨: {error}", error=e))
        return text.replace(find, to)
    if a == "extract":
        pat = fill(step.get("pattern", ""), vars_)[0]
        try:
            rx = re.compile(pat)
        except re.error as e:
            raise TextOpError(t("찾는 규칙(정규식)이 잘못됨: {error}", error=e))
        g = step.get("group")
        if step.get("all"):
            out = []
            for m in rx.finditer(text):
                out.append(m.group(g if g is not None else (1 if rx.groups else 0)))
            return out
        m = rx.search(text)
        if not m:
            raise TextOpError(t("글자에서 찾지 못함: {pattern}", pattern=pat))
        return m.group(g if g is not None else (1 if rx.groups else 0))
    if a == "split":
        sep = step.get("sep")
        parts = [p.strip() for p in (text.split(sep) if sep else text.split())]
        if "index" in step:
            i = int(step["index"])
            idx = i - 1 if i > 0 else i                 # 1 = 첫째, -1 = 마지막
            try:
                return parts[idx]
            except IndexError:
                raise TextOpError(t("{n}번째 조각이 없음(모두 {count}개)", n=i, count=len(parts)))
        return parts
    if a == "slice":
        start = int(step.get("start", 1))
        n = step.get("count")
        i = start - 1 if start > 0 else len(text) + start
        return text[i:] if n is None else text[i:i + int(n)]
    if a == "pad":
        width = int(step.get("width", 2))
        ch = str(step.get("char", "0"))[:1] or "0"
        return text.rjust(width, ch)
    if a == "join":
        src = vars_.get(step.get("list", ""))
        if not isinstance(src, (list, tuple)):
            raise TextOpError(t("목록 변수가 아님: {name}", name=step.get("list")))
        return str(step.get("sep", ", ")).join(as_text(x) for x in src)
    raise TextOpError(t("모르는 글자 동작 '{action}'", action=a))


# ---------------------------------------------------------------- 날짜
_TOKENS = [("yyyy", "%Y"), ("yy", "%y"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S")]
_WEEK_KO = "월화수목금토일"
_WEEK_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def format_date(d: _dt.datetime, fmt: str) -> str:
    """yyyy·yy·MM·M·dd·d·HH·mm·ss·요일·ddd(Mon) 를 바꾼다. 나머지 글자는 그대로."""
    out = []
    i = 0
    while i < len(fmt):
        if fmt.startswith("ddd", i):                    # 요일 영어 약자(dd 보다 먼저)
            out.append(_WEEK_EN[d.weekday()])
            i += 3
            continue
        for tok, code in _TOKENS:
            if fmt.startswith(tok, i):
                out.append(d.strftime(code))
                i += len(tok)
                break
        else:
            if fmt.startswith("요일", i):
                out.append(_WEEK_KO[d.weekday()])
                i += 2
            elif fmt[i] == "M":
                out.append(str(d.month))
                i += 1
            elif fmt[i] == "d":
                out.append(str(d.day))
                i += 1
            else:
                out.append(fmt[i])
                i += 1
    return "".join(out)


def parse_date(v: Any) -> _dt.datetime:
    if isinstance(v, _dt.datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, _dt.date):
        return _dt.datetime(v.year, v.month, v.day)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if v > 10_000_000:                               # 초(지금 시각 변수)
            return _dt.datetime.fromtimestamp(v)
        return _dt.datetime(1899, 12, 30) + _dt.timedelta(days=float(v))   # 엑셀 날짜 숫자
    s = as_text(v).strip()
    m = re.match(r"^(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?"
                 r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$", s)
    if m:
        y, mo, d, hh, mi, ss = m.groups()
        return _dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        return _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    raise TextOpError(t("날짜로 읽을 수 없음: {value}", value=s))


def _add_months(d: _dt.datetime, n: int) -> _dt.datetime:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    import calendar
    day = min(d.day, calendar.monthrange(y, m + 1)[1])
    return d.replace(year=y, month=m + 1, day=day)


DATE_ACTIONS = ("format", "diff")


def date_op(step: dict, vars_: Dict[str, Any], now: _dt.datetime) -> Any:
    """format: from(없으면 지금) + add → format 글자. diff: to - from 의 날 수(unit: days/hours/minutes)."""
    src = step.get("from")
    base = now if src in (None, "") else parse_date(fill(src, vars_)[0] if isinstance(src, str) else src)
    add = step.get("add") or {}
    if add:
        base = _add_months(base, int(add.get("years", 0)) * 12 + int(add.get("months", 0)))
        base = base + _dt.timedelta(days=float(add.get("days", 0)), hours=float(add.get("hours", 0)),
                                    minutes=float(add.get("minutes", 0)))
    if (step.get("action") or "format") == "diff":
        to = step.get("to")
        other = now if to in (None, "") else parse_date(fill(to, vars_)[0] if isinstance(to, str) else to)
        sec = (other - base).total_seconds()
        unit = step.get("unit", "days")
        div = {"days": 86400, "hours": 3600, "minutes": 60}.get(unit, 86400)
        return _tidy(round(sec / div, 4))
    return format_date(base, str(step.get("format") or "yyyy-MM-dd"))


# ---------------------------------------------------------------- 계산
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "int": int, "abs": abs, "min": min, "max": max, "float": float}


def calc(expr: str, vars_: Dict[str, Any]) -> Any:
    """'가격 * 수량 * 1.1', '{가격} * 2', 'round(합계 / 3, 1)' 같은 식. 변수 글자 '1,200' 도 숫자로 본다."""
    src = VAR.sub(lambda m: m.group(1), str(expr))      # {이름} 도 이름으로
    tmp: Dict[str, Any] = {}

    def dotted(m):                                       # 보고.1.매출·행.금액 → 값(숫자 칸 이름은 파이썬 식이 못 읽어서 미리 바꿈)
        name = m.group(0)
        v = lookup(vars_, name, _ABSENT)
        if v is _ABSENT:
            return name
        key = f"_v{len(tmp)}"
        tmp[key] = v
        return key
    src = re.sub(r"(?<![\w.])[^\W\d]\w*(?:\.\w+)+", dotted, src)
    if tmp:
        vars_ = dict(vars_, **tmp)
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        raise TextOpError(t("계산식이 잘못됨: {expr}", expr=expr))

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in vars_:
                raise TextOpError(t("변수 '{name}' 가 없음", name=n.id))
            return to_number(vars_[n.id])
        if isinstance(n, ast.Attribute):            # 행.금액 처럼 표 한 줄의 칸
            parts = []
            cur = n
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if not isinstance(cur, ast.Name):
                raise TextOpError(t("계산식에 쓸 수 없는 것이 있음: {expr}", expr=expr))
            name = ".".join([cur.id] + parts[::-1])
            v = lookup(vars_, name, _ABSENT)
            if v is _ABSENT:
                raise TextOpError(t("변수 '{name}' 가 없음", name=name))
            return to_number(v)
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 64:
                raise TextOpError(t("계산식이 잘못됨: {expr}", expr=expr))
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
            return _UN[type(n.op)](ev(n.operand))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS
                and not n.keywords and len(n.args) <= 4):
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise TextOpError(t("계산식에 쓸 수 없는 것이 있음: {expr}", expr=expr))
    try:
        return _tidy(ev(tree))
    except ZeroDivisionError:
        raise TextOpError(t("0으로 나눌 수 없음"))


# ---------------------------------------------------------------- 글자 비교 조건
TEXT_OPS = ("contains", "not_contains", "starts_with", "ends_with", "matches", "is_empty")


def text_compare(op: str, v: Any, want: Any) -> bool:
    s = as_text(v)
    if op == "is_empty":
        return (s.strip() == "") == bool(want)
    w = as_text(want)
    if op == "contains":
        return w in s
    if op == "not_contains":
        return w not in s
    if op == "starts_with":
        return s.startswith(w)
    if op == "ends_with":
        return s.endswith(w)
    if op == "matches":
        try:
            return re.search(w, s) is not None
        except re.error:
            return False
    return False


def is_number_like(v: Any) -> bool:
    try:
        to_number(v)
        return True
    except TextOpError:
        return False


def coerce_pair(a: Any, b: Any):
    """크다·작다 비교에서 한쪽이 '1,200' 같은 숫자 글자면 둘 다 숫자로."""
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, str) and is_number_like(b):
        return a, to_number(b)
    if isinstance(b, (int, float)) and not isinstance(b, bool) and isinstance(a, str) and is_number_like(a):
        return to_number(a), b
    return a, b


__all__ = ["fill", "as_text", "to_number", "text_op", "date_op", "calc", "text_compare", "TextOpError",
           "TEXT_ACTIONS", "DATE_ACTIONS", "TEXT_OPS", "format_date", "parse_date", "coerce_pair"]
