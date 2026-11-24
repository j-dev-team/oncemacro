"""
v1 매크로(macros/*.json) → v2 변환기. 원본은 건드리지 않는다.

매핑 규칙: docs/engine_v2_design.md §10 표.
변환할 때마다 매크로별 경고·동작 변경 목록(Report)을 만든다.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .i18n import K, t as tr_
from .model import VERSION, validate_macro

INF_WITHIN = 86400   # v1 '무한 대기 + 실패 분기'를 if 로 옮길 때 쓰는 within (사실상 무한)

# v1(pyautogui) 키 이름 → v2 키 이름
_KEY_ALIASES = {
    "winleft": "win", "winright": "win", "command": "win", "escape": "esc", "return": "enter",
    "pgup": "pageup", "pgdn": "pagedown", "del": "delete", "ins": "insert", "prtsc": "printscreen",
    "prtscr": "printscreen", "prntscrn": "printscreen", "print": "printscreen", "ctrlleft": "lctrl",
    "ctrlright": "rctrl", "shiftleft": "lshift", "shiftright": "rshift", "altleft": "lalt",
    "altright": "ralt", "control": "ctrl", "spacebar": "space", "kana": "hangul", "hanguel": "hangul",
}
for _i in range(10):
    _KEY_ALIASES[f"numpad_{_i}"] = f"num{_i}"
_KEY_ALIASES.update({"numpad_*": "multiply", "numpad_+": "add", "numpad_-": "subtract",
                     "numpad_.": "decimal", "numpad_/": "divide"})


@dataclass
class Report:
    name: str
    source: str
    v1_actions: int = 0
    v2_steps: int = 0
    warnings: List[str] = field(default_factory=list)   # 사람이 확인해야 할 것
    changes: List[str] = field(default_factory=list)    # 의도한 동작 변경
    infinite_waits: int = 0
    merged_clicks: int = 0
    errors: List[str] = field(default_factory=list)     # 변환 결과 검증 오류
    output: Optional[str] = None
    skipped: Optional[str] = None

    def warn(self, path: str, msg: str):
        self.warnings.append(f"{path}: {msg}")


def _count_steps(steps: list) -> int:
    n = 0
    for s in steps:
        n += 1
        for k in ("then", "else", "steps"):
            if isinstance(s.get(k), list):
                n += _count_steps(s[k])
    return n


def _count_actions(acts: list) -> int:
    n = 0
    for a in acts:
        n += 1
        p = a.get("params", {})
        for k in ("on_success", "on_failure"):
            if p.get(k):
                n += _count_actions(p[k])
    return n


def _is_num(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


def _var_refs(acts: list, out: Dict[str, int]) -> Dict[str, int]:
    """mouse_move 좌표에서 변수 이름이 몇 번 쓰였는지."""
    for a in acts:
        p = a.get("params", {})
        if a.get("type") == "mouse_move":
            names = {v for v in (p.get("x"), p.get("y")) if isinstance(v, str) and v and not _is_num(v)}
            for n in names:
                out[n] = out.get(n, 0) + 1
        for k in ("on_success", "on_failure"):
            if p.get(k):
                _var_refs(p[k], out)
    return out


class Converter:
    def __init__(self, image_root: str, origin: Tuple[int, int] = (0, 0)):
        self.image_root = os.path.normcase(os.path.abspath(image_root))
        self.origin = origin

    # ------------------------------------------------------------ 공개
    def convert(self, v1: dict, source: str = "", window: Optional[dict] = None) -> Tuple[dict, Report]:
        name = v1.get("name") or os.path.splitext(os.path.basename(source))[0]
        rep = Report(name, source)
        acts = v1.get("actions", [])
        rep.v1_actions = _count_actions(acts)
        self._rep = rep
        self._refs = _var_refs(acts, {})
        steps = self._list(acts, "actions", skip_failures=False)

        infinite = bool(v1.get("infinite_repeat"))
        times = int(v1.get("repeat_count") or 1)
        out: Dict[str, Any] = {"version": VERSION, "name": name}
        if window:
            out["window"] = window
        if infinite:
            out["repeat"] = {"forever": True}
            out["on_iteration_fail"] = {"action": "retry", "max_consecutive": None}
        else:
            out["repeat"] = {"times": max(1, times)}
            out["on_iteration_fail"] = {"action": "retry", "max_consecutive": 3}
            rep.changes.append(tr_("반복 {times}회: v1은 한 회차만 실패해도 전체 종료 → v2는 실패한 회차를 처음부터 다시 돎(연속 3회 실패하면 종료). 횟수는 성공한 회차만 셈", times=max(1, times)))
        for k in ("run_hotkey", "stop_hotkey"):
            if v1.get(k):
                out[k] = str(v1[k])
        out["steps"] = steps
        rep.v2_steps = _count_steps(steps)
        rep.errors = validate_macro(out)
        return out, rep

    # ------------------------------------------------------------ 목록 (짝 합치기 포함)
    def _list(self, acts: list, path: str, skip_failures: bool) -> list:
        out: list = []
        i = 0
        while i < len(acts):
            a = acts[i]
            p = a.get("params", {})
            ap = f"{path}[{i}]"
            nxt = acts[i + 1] if i + 1 < len(acts) else None
            if self._mergeable(a, nxt):
                out.extend(self._merged(a, nxt, ap))
                self._rep.merged_clicks += 1
                i += 2
                continue
            out.extend(self._action(a, ap))
            i += 1
        if skip_failures and out:
            # v1 실패 분기: 하위 액션이 실패하면 나머지는 건너뛰고 매크로는 계속 → group + skip
            return [{"type": "group", "steps": out, "on_fail": "skip",
                     "note": tr_("v1 실패 분기: 중간에 실패하면 나머지는 건너뛰고 계속 진행")}]
        return out

    def _mergeable(self, a: dict, nxt: Optional[dict]) -> bool:
        if a.get("type") != "image" or not nxt or nxt.get("type") != "mouse_move":
            return False
        p, q = a.get("params", {}), nxt.get("params", {})
        rv = p.get("result_var")
        if not rv or p.get("on_success") or p.get("on_failure") or p.get("wait_until_disappear"):
            return False
        if q.get("x") != rv or q.get("y") != rv or self._refs.get(rv, 0) != 1:
            return False
        return q.get("action", "click") in ("click", "move") or q.get("move_only")

    # ------------------------------------------------------------ 대상
    def _rel_xy(self, x, y) -> List[int]:
        return [int(float(x)) - self.origin[0], int(float(y)) - self.origin[1]]

    def _template(self, path: str, ap: str) -> str:
        if not path:
            self._rep.warn(ap, tr_("템플릿 경로가 비어 있음"))
            return ""
        full = os.path.normcase(os.path.abspath(path))
        if not os.path.exists(path):
            self._rep.warn(ap, tr_("템플릿 파일 없음: {path}", path=path))
        if full.startswith(self.image_root + os.sep):
            return os.path.relpath(os.path.abspath(path), self.image_root).replace("\\", "/")
        self._rep.warn(ap, tr_("image/ 밖의 템플릿이라 절대경로 유지: {path}", path=path))
        return path

    def _image_target(self, p: dict, ap: str) -> dict:
        t: Dict[str, Any] = {"image": self._template(p.get("template", ""), ap)}
        region = p.get("region")
        if region:
            x, y = self._rel_xy(region[0], region[1])
            t["region"] = [x, y, int(region[2]), int(region[3])]
        conf = p.get("shape_confidence", p.get("confidence"))
        if conf is not None and float(conf) != 0.8:
            t["confidence"] = round(float(conf), 3)
        if p.get("color_confidence") is not None:
            t["color_check"] = round(float(p["color_confidence"]), 3)
        if p.get("use_multiscale", True):
            t["multiscale"] = True       # v1 기본값이 true 였음
        return t

    def _color_target(self, p: dict, ap: str) -> dict:
        c = p.get("color")
        if isinstance(c, str):
            h = c.lstrip("#")
            c = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        c = [int(v) for v in (c or [0, 0, 0])][:3]
        t = {"color": c, "at": self._rel_xy(p.get("x", 0), p.get("y", 0))}
        if p.get("tolerance"):
            t["tolerance"] = int(p["tolerance"])
        return t

    def _timeout(self, p: dict, ap: str, default: float = 10.0):
        v = p.get("timeout", default)
        if v in (0, 0.0, None):
            self._rep.infinite_waits += 1
            return None
        return float(v)

    # ------------------------------------------------------------ 액션별
    def _action(self, a: dict, ap: str) -> list:
        t = a.get("type")
        p = a.get("params", {})
        if t in ("image", "color"):
            return self._detect(t, p, ap)
        if t == "mouse_move":
            return self._mouse(p, ap)
        if t == "keyboard":
            return self._keyboard(p, ap)
        if t == "delay":
            return [{"type": "delay", "seconds": float(p.get("delay", 1.0))}]
        if t == "comment":
            return [{"type": "comment", "text": str(p.get("comment", ""))}]
        if t == "logic_branch":
            return self._logic_branch(p, ap)
        self._rep.warn(ap, tr_("변환할 수 없는 액션 '{type}' → 주석으로 남김", type=t))
        return [{"type": "comment", "text": tr_("[변환 불가 v1 액션] {action}", action=json.dumps(a, ensure_ascii=False))}]

    def _merged(self, a: dict, nxt: dict, ap: str) -> list:
        p, q = a["params"], nxt["params"]
        target = self._image_target(p, ap)
        out = []
        if q.get("save_position_var"):
            out.append({"type": "remember", "var": q["save_position_var"]})   # v1 은 클릭 전 위치를 저장
        timeout = self._timeout(p, ap)
        if q.get("move_only") or q.get("action") == "move":
            out.append({"type": "move", "target": target, "timeout": timeout})
        else:
            step = {"type": "click", "target": target, "timeout": timeout}
            if q.get("button", "left") != "left":
                step["button"] = q["button"]
            if q.get("double"):
                step["count"] = 2
            out.append(step)
        return out

    def _detect(self, kind: str, p: dict, ap: str) -> list:
        target = self._image_target(p, ap) if kind == "image" else self._color_target(p, ap)
        if p.get("wait_until_disappear"):
            if kind == "color":
                timeout = None             # v1 색상 사라짐 대기는 시간 제한이 없었음
                self._rep.infinite_waits += 1
            else:
                timeout = self._timeout(p, ap, default=0)
            return [{"type": "wait", "until": {"gone": target, "for": float(p.get("disappear_duration", 1.0))},
                     "timeout": timeout}]

        rv = p.get("result_var") or None
        uses_rv = bool(rv and self._refs.get(rv))
        on_s, on_f = p.get("on_success") or [], p.get("on_failure") or []
        S = self._list(on_s, f"{ap}.on_success", skip_failures=False)
        F = self._list(on_f, f"{ap}.on_failure", skip_failures=True)
        cond = {"exists": target}

        # 성공 쪽
        body = [{"type": "remember", "var": rv, "what": target}] if uses_rv else []
        if p.get("repeat_success_until_fail"):
            success = [{"type": "repeat", "while": cond, "steps": body + S}]
            body = []
        elif int(p.get("on_success_repeat", 1) or 1) > 1:
            success = body + [{"type": "repeat", "times": int(p["on_success_repeat"]), "steps": S}]
        else:
            success = body + S
            # 성공 분기가 '찾은 위치 클릭'으로 시작하고 그 변수를 다른 데서 안 쓰면 click(이미지) 하나로
            if (uses_rv and self._refs.get(rv) == 1 and S and S[0].get("type") in ("click", "move")
                    and S[0].get("target") == {"var": rv}):
                success = [dict(S[0], target=target)] + S[1:]
                self._rep.merged_clicks += 1

        # 실패 쪽
        if p.get("repeat_failure_until_success"):
            failure = [{"type": "repeat", "until": cond, "steps": F}] if F else []
        elif F and int(p.get("on_failure_repeat", 1) or 1) > 1:
            failure = [{"type": "repeat", "times": int(p["on_failure_repeat"]), "steps": F}]
        else:
            failure = F

        timeout = self._timeout(p, ap)
        if not on_f:
            # v1: 못 찾으면 매크로(회차) 실패
            if uses_rv:
                first = {"type": "remember", "var": rv, "what": target, "timeout": timeout}
                rest = success[1:] if success and success[0].get("type") == "remember" else success
                return [first] + rest
            return [{"type": "wait", "until": cond, "timeout": timeout}] + success

        if timeout is None:
            within = INF_WITHIN
            self._rep.warn(ap, tr_("v1에서 '무한 대기 + 실패 분기'라 실패 분기가 실행될 수 없었음. within={within}초로 옮겼으니 원하는 시간으로 바꿔야 실패 분기가 동작함", within=INF_WITHIN))
        else:
            within = timeout
        return [{"type": "if", "cond": cond, "within": within, "then": success, "else": failure}]

    def _mouse(self, p: dict, ap: str) -> list:
        out = []
        save = p.get("save_position_var")
        if save:
            out.append({"type": "remember", "var": save})
        x, y = p.get("x"), p.get("y")
        if save and (x in (0, "", None) and y in (0, "", None)):
            return out
        if _is_num(x) and _is_num(y):
            target = {"point": self._rel_xy(x, y)}
        elif isinstance(x, str) and x and x == y:
            target = {"var": x}
        else:
            self._rep.warn(ap, tr_("좌표 x={x}, y={y} 를 변환할 수 없음(변수·숫자 섞임) → 주석으로 남김", x=repr(x), y=repr(y)))
            return out + [{"type": "comment", "text": tr_("[변환 불가 마우스] x={x} y={y}", x=repr(x), y=repr(y))}]
        action = p.get("action", "click")
        button = p.get("button", "left")
        if p.get("move_only") or action == "move":
            return out + [{"type": "move", "target": target}]
        if action == "press":
            return out + [{"type": "mouse_down", "target": target, "button": button}]
        if action == "release":
            return out + [{"type": "mouse_up", "target": target, "button": button}]
        step = {"type": "click", "target": target}
        if button != "left":
            step["button"] = button
        if p.get("double"):
            step["count"] = 2
        return out + [step]

    def _key_name(self, k: str, ap: str) -> str:
        k = k.strip().lower()
        k = _KEY_ALIASES.get(k, k)
        try:
            from .win_input import VK
            if k not in VK:
                self._rep.warn(ap, tr_("v2에 없는 키 이름 '{key}' — 실행 때 오류남", key=k))
        except Exception:
            pass
        return k

    def _keyboard(self, p: dict, ap: str) -> list:
        if p.get("hotkey_type") == "combo":
            raw = p.get("combo_key", "")
        else:
            raw = p.get("key", "")
        if not raw:
            self._rep.warn(ap, tr_("키가 비어 있음 → 주석으로 남김"))
            return [{"type": "comment", "text": tr_("[변환 불가 키보드] 빈 키")}]
        parts = [raw] if raw.strip() == "+" else [x for x in raw.split("+") if x.strip()]
        return [{"type": "key", "keys": "+".join(self._key_name(x, ap) for x in parts)}]

    def _logic_branch(self, p: dict, ap: str) -> list:
        ct, cd = p.get("condition_type"), p.get("condition_data", {}) or {}
        if ct == "image":
            target = self._image_target(cd, ap)
        elif ct == "color":
            target = self._color_target(cd, ap)
        else:
            self._rep.warn(ap, tr_("알 수 없는 논리 분기 조건 '{ct}' → 주석", ct=ct))
            return [{"type": "comment", "text": tr_("[변환 불가 논리 분기] {ct}", ct=ct)}]
        timeout = self._timeout(cd, ap)
        within = INF_WITHIN if timeout is None else timeout
        if timeout is None:
            self._rep.warn(ap, tr_("논리 분기 무한 대기 → within={within}초로 옮김", within=INF_WITHIN))
        return [{"type": "if", "cond": {"exists": target}, "within": within,
                 "then": [{"type": "set_result", "value": 1}],
                 "else": [{"type": "set_result", "value": 0}]}]


# ---------------------------------------------------------------- 폴더 단위

GLOBAL_CHANGES = [
    K("이미지 색 검사: v1은 형태+색(MSE)을 같은 기준(0.8)으로 봤음 → v2는 색 유사도 기준 0.85가 기본(오인식 방지, 실측 근거 docs §8). v1에서 color_confidence 를 직접 정한 액션은 그 값을 유지"),
    K("이미지를 찾으면 바로 클릭하지 않고 2프레임 연속 같은 위치인지 확인 + 0.15초 대기 후 클릭(너무 빨리 넘어가는 문제 대책)"),
    K("클릭: 이동 후 0.04초 대기 → 0.06초 누르고 뗌 → 0.1초 대기 (v1은 0초)"),
    K("multiscale: v1 기본값이 켜짐이라 그대로 켬. 같은 해상도에서 만든 템플릿이면 꺼도 됨(더 빠르고 오인식 적음)"),
]


def convert_folder(src: str, dst: str, image_root: str, names: Optional[List[str]] = None,
                   window: Optional[dict] = None, origin: Tuple[int, int] = (0, 0),
                   force: bool = False, dry_run: bool = False) -> List[Report]:
    from .model import save_macro
    conv = Converter(image_root, origin)
    files = sorted(f for f in os.listdir(src) if f.endswith(".json") and f != "groups.json")
    if names:
        wanted = {n if n.endswith(".json") else n + ".json" for n in names}
        missing = wanted - set(files)
        if missing:
            raise FileNotFoundError(tr_("v1 매크로 없음: {names}", names=sorted(missing)))
        files = [f for f in files if f in wanted]
    reports = []
    for f in files:
        path = os.path.join(src, f)
        with open(path, encoding="utf-8") as fh:
            v1 = json.load(fh)
        v2, rep = conv.convert(v1, path, window)
        out = os.path.join(dst, f"{v2['name']}.json")
        rep.output = out
        if rep.errors:
            rep.skipped = tr_("검증 오류")
        elif os.path.exists(out) and not force:
            rep.skipped = tr_("이미 있음(--force 로 덮어쓰기)")
        elif not dry_run:
            save_macro(v2, out)
        reports.append(rep)

    groups_src = os.path.join(src, "groups.json")
    if not dry_run and os.path.exists(groups_src):
        done = {r.name for r in reports if not r.skipped}
        with open(groups_src, encoding="utf-8") as fh:
            groups = json.load(fh)
        gpath = os.path.join(dst, "_groups.json")
        existing = {}
        if os.path.exists(gpath):
            with open(gpath, encoding="utf-8") as fh:
                existing = json.load(fh)
        for g, members in groups.items():
            keep = [m for m in members if m in done]
            if keep:
                cur = existing.setdefault(g, [])
                cur.extend(m for m in keep if m not in cur)
        os.makedirs(dst, exist_ok=True)
        with open(gpath, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, ensure_ascii=False, indent=2)
    return reports


def render_report(reports: List[Report], dry_run: bool = False) -> str:
    lines = [tr_("# v1 → v2 변환 보고서"), ""]
    if dry_run:
        lines += [tr_("> 미리보기(--dry-run): 파일은 쓰지 않았음"), ""]
    lines += [tr_("## 모든 매크로에 공통으로 바뀌는 동작"), ""] + [f"- {tr_(c)}" for c in GLOBAL_CHANGES] + [""]
    lines += [tr_("## 요약"), "", tr_("| 매크로 | v1 액션 | v2 스텝 | 합친 클릭 | 무한 대기 | 경고 | 결과 |"), "|---|---|---|---|---|---|---|"]
    for r in reports:
        state = r.skipped or (tr_("미리보기") if dry_run else tr_("저장"))
        lines.append(f"| {r.name} | {r.v1_actions} | {r.v2_steps} | {r.merged_clicks} | {r.infinite_waits} | "
                     f"{len(r.warnings)} | {state} |")
    lines.append("")
    for r in reports:
        if not (r.warnings or r.changes or r.errors):
            continue
        lines += [f"## {r.name}", ""]
        for e in r.errors:
            lines.append("- ❌ " + tr_("검증 오류: {error}", error=e))
        for w in r.warnings:
            lines.append(f"- ⚠ {w}")
        for c in r.changes:
            lines.append(f"- ↻ {c}")
        lines.append("")
    return "\n".join(lines)
