"""
매크로 v2 데이터 모델: 기본값, 검증, 로드/저장.

매크로·스텝은 JSON과 같은 dict 그대로 다룬다(GUI·MCP·AI가 바로 읽고 쓰기 쉽게).
검증은 오류 위치(steps[3].target.region 등)를 모두 모아서 한 번에 알려준다.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .i18n import t

VERSION = 2

DEFAULT_SETTINGS: Dict[str, Any] = {
    "timeout": 30,            # 대상/조건 대기 최대 초. None = 무한
    "confidence": 0.8,        # 이미지 매칭 임계값 (흑백 형태)
    "color_check": 0.85,      # 색 유사도 임계값. None = 색 검사 안 함 (오인식 방지용, 실측 근거 docs §8)
    "stable_frames": 2,       # 클릭 위치를 정할 때 연속 N프레임 같은 위치여야 '찾음' (조건 판단은 1프레임)
    "stable_px": 6,           # 같은 위치로 보는 허용 오차(px). 통통 튀는 표시(▼ 등)도 인정되게
    "settle_ms": 150,         # 찾은 뒤 클릭 전 대기
    "move_settle_ms": 40,     # 마우스 이동 후 누르기 전 대기
    "click_hold_ms": 60,      # 마우스 누르고 있는 시간
    "double_click_gap_ms": 80,
    "after_click_ms": 100,    # 클릭 후 대기
    "key_hold_ms": 50,        # 키 누르고 있는 시간
    "poll_ms": 100,           # 화면 확인 간격
    "input_backend": "sendinput",
}

DEFAULT_ON_ITERATION_FAIL = {"action": "retry", "max_consecutive": 3, "delay": 1.0}

BUTTONS = ("left", "right", "middle")
COMMON_STEP_KEYS = {"type", "id", "note", "on_fail", "retries", "foreground"}


class MacroError(ValueError):
    """매크로 형식 오류. errors 에 '위치: 내용' 목록이 들어 있다."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(t("매크로 형식 오류:\n- ") + "\n- ".join(errors))


# ---------------------------------------------------------------- 검증 도우미

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _xy(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_num(n) for n in v)


class _Checker:
    def __init__(self):
        self.errors: List[str] = []

    def err(self, path: str, msg: str):
        self.errors.append(f"{path}: {msg}")

    def unknown(self, path: str, d: dict, allowed: set):
        for k in d:
            if k not in allowed:
                self.err(path, t("알 수 없는 필드 '{k}'", k=k))

    def num(self, path, d, key, lo=None, hi=None, allow_none=False, required=False):
        if key not in d:
            if required:
                self.err(path, t("'{key}' 필요", key=key))
            return
        v = d[key]
        if v is None and allow_none:
            return
        if not _is_num(v):
            self.err(f"{path}.{key}", t("숫자여야 함") + (t(" (또는 null)") if allow_none else ""))
            return
        if lo is not None and v < lo:
            self.err(f"{path}.{key}", t("{lo} 이상이어야 함", lo=lo))
        if hi is not None and v > hi:
            self.err(f"{path}.{key}", t("{hi} 이하여야 함", hi=hi))

    def int_(self, path, d, key, lo=None, allow_none=False, required=False):
        if key not in d:
            if required:
                self.err(path, t("'{key}' 필요", key=key))
            return
        v = d[key]
        if v is None and allow_none:
            return
        if not _is_int(v):
            self.err(f"{path}.{key}", t("정수여야 함"))
        elif lo is not None and v < lo:
            self.err(f"{path}.{key}", t("{lo} 이상이어야 함", lo=lo))

    def str_(self, path, d, key, required=False, nonempty=True):
        if key not in d:
            if required:
                self.err(path, t("'{key}' 필요", key=key))
            return
        v = d[key]
        if not isinstance(v, str) or (nonempty and not v.strip()):
            self.err(f"{path}.{key}", t("비어 있지 않은 문자열이어야 함"))

    # ------------------------------------------------------------ target
    def target(self, path: str, tt: Any):
        if not isinstance(tt, dict):
            self.err(path, t("대상(target)은 객체여야 함"))
            return
        kinds = [k for k in ("image", "color", "vivid", "point", "var", "element") if k in tt]
        if len(kinds) != 1:
            self.err(path, t("image / color / vivid / point / var / element 중 정확히 하나가 필요"))
            return
        kind = kinds[0]
        allowed = {kind, "offset", "anchor"}
        if "anchor" in tt:
            # region·at·point 를 변수 위치(remember·for_each 로 얻은 좌표) 기준 상대값으로
            self.str_(path, tt, "anchor")
            if kind == "var":
                self.err(f"{path}.anchor", t("var 대상에는 쓸 수 없음(offset 을 쓸 것)"))
        if kind == "image":
            allowed |= {"region", "confidence", "multiscale", "color_check", "fallback_images"}
            self.str_(path, tt, "image")
            fb = tt.get("fallback_images", [])
            if not isinstance(fb, list) or not all(isinstance(x, str) and x for x in fb):
                self.err(f"{path}.fallback_images", t("문자열 목록이어야 함"))
            if "region" in tt and tt["region"] is not None:
                r = tt["region"]
                if not (isinstance(r, (list, tuple)) and len(r) == 4 and all(_is_num(n) for n in r)):
                    self.err(f"{path}.region", t("[x, y, 너비, 높이] 형식이어야 함"))
                elif r[2] <= 0 or r[3] <= 0:
                    self.err(f"{path}.region", t("너비·높이는 0보다 커야 함"))
            self.num(path, tt, "confidence", 0, 1)
            self.num(path, tt, "color_check", 0, 1, allow_none=True)
            if "multiscale" in tt and not isinstance(tt["multiscale"], bool):
                self.err(f"{path}.multiscale", t("true/false 여야 함"))
        elif kind == "color":
            allowed |= {"at", "tolerance", "region", "min_pixels", "blob_depth"}
            c = tt["color"]
            if not (isinstance(c, (list, tuple)) and len(c) == 3
                    and all(_is_int(n) and 0 <= n <= 255 for n in c)):
                self.err(f"{path}.color", t("[R, G, B] (0~255) 형식이어야 함"))
            has_at, has_region = "at" in tt, "region" in tt
            if has_at == has_region:
                self.err(path, t("색상 대상은 at(한 점) 또는 region(영역 안에 그 색이 있는지) 중 하나가 필요"))
            elif has_at and not _xy(tt.get("at")):
                self.err(f"{path}.at", t("[x, y] 좌표가 필요"))
            elif has_region:
                r = tt["region"]
                if not (isinstance(r, (list, tuple)) and len(r) == 4 and all(_is_num(n) for n in r))                         or r[2] <= 0 or r[3] <= 0:
                    self.err(f"{path}.region", t("[x, y, 너비, 높이] (너비·높이 > 0)"))
                self.int_(path, tt, "min_pixels", 1)
            if "min_pixels" in tt and not has_region:
                self.err(f"{path}.min_pixels", t("region 과 같이 써야 함"))
            if "blob_depth" in tt:
                # 그 색 덩어리(구멍 메움) 중 가장 두꺼운 곳을 위치로. 두께 px 기준
                self.num(path, tt, "blob_depth", 1, 500)
                if not has_region:
                    self.err(f"{path}.blob_depth", t("region 과 같이 써야 함"))
                if "min_pixels" in tt:
                    self.err(f"{path}.blob_depth", t("min_pixels 와 함께 쓸 수 없음(둘 중 하나로 '있음'을 판단)"))
            self.int_(path, tt, "tolerance", 0)
        elif kind == "vivid":
            # 영역 안 '선명한 색'(채도·밝기 기준 이상) 픽셀 수 — 색 글자(등급 이름 등) 감지용
            allowed |= {"region", "min_pixels", "min_saturation", "min_value", "hues"}
            hs = tt.get("hues")
            if hs is not None and not (isinstance(hs, list) and hs and all(
                    isinstance(h, (list, tuple)) and len(h) == 2 and all(_is_num(x) and 0 <= x <= 180 for x in h)
                    and h[0] <= h[1] for h in hs)):
                self.err(f"{path}.hues", t("[[시작, 끝], ...] 색상 범위 목록 (OpenCV H 0~180)"))
            if tt["vivid"] is not True:
                self.err(f"{path}.vivid", t("true 여야 함"))
            r = tt.get("region")
            if not (isinstance(r, (list, tuple)) and len(r) == 4 and all(_is_num(n) for n in r))                     or r[2] <= 0 or r[3] <= 0:
                self.err(f"{path}.region", t("[x, y, 너비, 높이] 가 필요 (너비·높이 > 0)"))
            self.int_(path, tt, "min_pixels", 1)
            self.int_(path, tt, "min_saturation", 0)
            self.int_(path, tt, "min_value", 0)
        elif kind == "point":
            if not _xy(tt["point"]):
                self.err(f"{path}.point", t("[x, y] 형식이어야 함"))
        elif kind == "var":
            self.str_(path, tt, "var")
        elif kind == "element":
            # 창 요소(버튼·입력칸 등)를 이름으로 — 해상도·배율이 바뀌어도 찾음
            from .win_uia import check_spec
            for e in check_spec(tt["element"]):
                self.err(f"{path}.element", t(e))
            if "anchor" in tt:
                self.err(f"{path}.anchor", t("element 대상에는 쓸 수 없음(offset 을 쓸 것)"))
        if "offset" in tt and not _xy(tt["offset"]):
            self.err(f"{path}.offset", t("[dx, dy] 형식이어야 함"))
        self.unknown(path, tt, allowed)

    # ------------------------------------------------------------ cond
    def mem_value(self, path: str, v: Any):
        """메모리 값: 저장한 이름(글자) 또는 주소 모양(객체)."""
        if isinstance(v, str):
            if not v.strip():
                self.err(path, t("저장한 메모리 값 이름이 필요"))
            return
        if not isinstance(v, dict):
            self.err(path, t("저장한 이름(글자)이나 주소 {\"offset\": ..} 가 필요"))
            return
        from .memory import check_spec
        for e in check_spec(v):
            self.err(path, e)

    def cond(self, path: str, c: Any):
        if not isinstance(c, dict):
            self.err(path, t("조건은 객체여야 함"))
            return
        kinds = [k for k in ("exists", "gone", "var", "not", "all", "any", "web", "window_size", "file", "memory") if k in c]
        if "var" in kinds:
            kinds = ["var"]
        if len(kinds) != 1:
            self.err(path, t("exists / gone / var / not / all / any / web / file / memory 중 정확히 하나가 필요"))
            return
        kind = kinds[0]
        if kind == "memory":
            # 메모리 값 비교 {"memory": {"value": 이름|주소, "gt": 100}} / 기다리기에서만 {"changed": true}
            mc = c["memory"]
            if not isinstance(mc, dict):
                self.err(f"{path}.memory", t("객체여야 함"))
            else:
                self.mem_value(f"{path}.memory.value", mc.get("value"))
                ops = [k for k in ("eq", "ne", "gt", "lt", "ge", "le", "changed") if k in mc]
                if len(ops) != 1:
                    self.err(f"{path}.memory", t("eq / ne / gt / lt / ge / le / changed 중 하나가 필요"))
                elif ops[0] == "changed" and not getattr(self, "_in_wait", False):
                    self.err(f"{path}.memory.changed", t("'값이 바뀌면'은 기다리기(wait)에서만 쓸 수 있음"))
                self.unknown(f"{path}.memory", mc, {"value", "eq", "ne", "gt", "lt", "ge", "le", "changed"})
            self.unknown(path, c, {"memory"})
            return
        if kind == "window_size":
            # 대상 창 안쪽 크기가 [너비, 높이] 와 같을 때 참(고정 좌표 동작을 같은 창 크기에서만 하게)
            ws = c["window_size"]
            if not (isinstance(ws, (list, tuple)) and len(ws) == 2 and all(_is_int(n) and n > 0 for n in ws)):
                self.err(f"{path}.window_size", t("[너비, 높이] 형식이어야 함"))
            self.unknown(path, c, {"window_size"})
            return
        if kind == "file":
            # 파일·폴더가 있는지(내려받기 끝 기다리기 등). {"file": {"path": "...", "exists": true}}
            fc = c["file"]
            if not isinstance(fc, dict):
                self.err(f"{path}.file", t("객체여야 함"))
            else:
                self.str_(f"{path}.file", fc, "path", required=True)
                if "exists" in fc and not isinstance(fc["exists"], bool):
                    self.err(f"{path}.file.exists", "true/false")
                self.unknown(f"{path}.file", fc, {"path", "exists"})
            self.unknown(path, c, {"file"})
            return
        if kind == "web":
            # 웹 페이지에 그 요소가 있는지(에고라이트). {"web": {"selector": "text=로그인", "state": "visible", "page": "p1"}}
            w = c["web"]
            if not isinstance(w, dict):
                self.err(f"{path}.web", t("객체여야 함"))
            else:
                self.str_(f"{path}.web", w, "selector", required=True)
                if "state" in w and w["state"] not in ("visible", "attached", "hidden", "detached"):
                    self.err(f"{path}.web.state", "visible / attached / hidden / detached")
                self.str_(f"{path}.web", w, "page")
                self.unknown(f"{path}.web", w, {"selector", "state", "page"})
            self.unknown(path, c, {"web"})
            return
        if kind in ("exists", "gone") and isinstance(c[kind], dict) and (
                "var" in c[kind] or "point" in c[kind]):
            self.err(f"{path}.{kind}", t("화면 확인은 image / color 대상만 가능. "
                                         "변수가 있는지는 {\"var\": 이름, \"is_set\": true} 로 확인"))
            return
        if kind == "exists":
            self.target(f"{path}.exists", c["exists"])
            self.unknown(path, c, {"exists"})
        elif kind == "gone":
            self.target(f"{path}.gone", c["gone"])
            self.num(path, c, "for", 0)
            self.unknown(path, c, {"gone", "for"})
        elif kind == "var":
            self.str_(path, c, "var")
            from .textops import TEXT_OPS
            all_ops = ("eq", "ne", "gt", "lt", "ge", "le", "is_set") + TEXT_OPS
            ops = [k for k in all_ops if k in c]
            if len(ops) != 1:
                self.err(path, t("eq / ne / gt / lt / ge / le / is_set / contains / not_contains / starts_with / "
                                 "ends_with / matches / is_empty 중 하나가 필요"))
            elif ops[0] == "matches":
                import re as _re
                try:
                    _re.compile(str(c["matches"]))
                except _re.error as e:
                    self.err(f"{path}.matches", t("찾는 규칙(정규식)이 잘못됨: {error}", error=e))
            self.unknown(path, c, {"var"} | set(all_ops))
        elif kind == "not":
            self.cond(f"{path}.not", c["not"])
            self.unknown(path, c, {"not"})
        else:
            items = c[kind]
            if not isinstance(items, list) or not items:
                self.err(f"{path}.{kind}", t("조건 목록(1개 이상)이어야 함"))
            else:
                for i, sub in enumerate(items):
                    self.cond(f"{path}.{kind}[{i}]", sub)
            self.unknown(path, c, {kind})

    # ------------------------------------------------------------ steps
    def steps(self, path: str, steps: Any, loop_depth: int):
        if not isinstance(steps, list):
            self.err(path, t("스텝 목록이어야 함"))
            return
        for i, s in enumerate(steps):
            self.step(f"{path}[{i}]", s, loop_depth)

    def step(self, path: str, s: Any, loop_depth: int):
        if not isinstance(s, dict):
            self.err(path, t("스텝은 객체여야 함"))
            return
        typ = s.get("type")
        spec = STEP_SPECS.get(typ) if isinstance(typ, str) else None
        if spec is None:
            self.err(path, t("알 수 없는 스텝 type '{type}'", type=typ))
            return
        allowed = COMMON_STEP_KEYS | spec | set(DEFAULT_SETTINGS)
        self.unknown(path, s, allowed)
        self.settings(path, s, partial=True)

        of = s.get("on_fail", "fail")
        if not (of in ("fail", "skip", "retry") or (isinstance(of, dict) and set(of) == {"return"})):
            self.err(f"{path}.on_fail", t("'fail' / 'skip' / 'retry' / {\"return\": 값} 중 하나여야 함"))
        self.int_(path, s, "retries", 0)
        if "foreground" in s and not isinstance(s["foreground"], bool):
            self.err(f"{path}.foreground", t("true/false (true = 뒤에서 실행 중 이 스텝만 잠깐 앞에서)"))
        if typ == "menu":
            self.str_(path, s, "path", required=True)

        if "timeout" in spec:
            self.num(path, s, "timeout", 0, allow_none=True)
        if "button" in s and s["button"] not in BUTTONS:
            self.err(f"{path}.button", t("left / right / middle 중 하나여야 함"))

        if typ == "click":
            self.target(f"{path}.target", s.get("target"))
            if "count" in s and s["count"] not in (1, 2):
                self.err(f"{path}.count", t("1 또는 2"))
            if "verify" in s:
                v = s["verify"]
                if not isinstance(v, dict) or "cond" not in v:
                    self.err(f"{path}.verify", t("{cond, timeout, retries} 형식이어야 함"))
                else:
                    self.cond(f"{path}.verify.cond", v["cond"])
                    self.num(f"{path}.verify", v, "timeout", 0)
                    self.int_(f"{path}.verify", v, "retries", 0)
                    self.unknown(f"{path}.verify", v, {"cond", "timeout", "retries"})
        elif typ == "move":
            self.target(f"{path}.target", s.get("target"))
        elif typ == "scroll":
            if "target" in s:
                self.target(f"{path}.target", s.get("target"))
            self.int_(path, s, "amount")
            if "horizontal" in s and not isinstance(s["horizontal"], bool):
                self.err(f"{path}.horizontal", "true/false")
        elif typ == "drag":
            self.target(f"{path}.from", s.get("from"))
            self.target(f"{path}.to", s.get("to"))
            self.num(path, s, "duration_ms", 0)
        elif typ in ("mouse_down", "mouse_up"):
            if "target" in s:
                self.target(f"{path}.target", s["target"])
        elif typ == "key":
            self.str_(path, s, "keys", required=True)
            self.int_(path, s, "count", 1)
        elif typ == "type_text":
            if not isinstance(s.get("text"), str):
                self.err(path, t("'text' 문자열이 필요"))
            if "target" in s:
                if not (isinstance(s["target"], dict) and "element" in s["target"]):
                    self.err(f"{path}.target", t("글자 넣기의 대상은 창 요소(element)만 됨"))
                else:
                    self.target(f"{path}.target", s["target"])
        elif typ == "wait":
            if "until" not in s:
                self.err(path, t("'until' 조건이 필요"))
            else:
                self._in_wait = True             # 'changed'(값이 바뀌면) 같은 기다리기 전용 조건 허용
                try:
                    self.cond(f"{path}.until", s["until"])
                finally:
                    self._in_wait = False
        elif typ == "delay":
            self.num(path, s, "seconds", 0, required=True)
        elif typ == "remember":
            self.str_(path, s, "var", required=True)
            w = s.get("what", "mouse")
            if w != "mouse":
                self.target(f"{path}.what", w)
        elif typ == "if":
            if "cond" not in s:
                self.err(path, t("'cond' 조건이 필요"))
            else:
                self.cond(f"{path}.cond", s["cond"])
            self.num(path, s, "within", 0)
            self.steps(f"{path}.then", s.get("then", []), loop_depth)
            self.steps(f"{path}.else", s.get("else", []), loop_depth)
        elif typ == "repeat":
            modes = [k for k in ("times", "until", "while", "forever") if k in s]
            if len(modes) != 1:
                self.err(path, t("times / until / while / forever 중 정확히 하나가 필요"))
            else:
                m = modes[0]
                if m == "times":
                    self.int_(path, s, "times", 0)
                elif m == "forever":
                    if s["forever"] is not True:
                        self.err(f"{path}.forever", t("true 여야 함"))
                else:
                    self.cond(f"{path}.{m}", s[m])
            self.int_(path, s, "max_times", 1, allow_none=True)
            self.num(path, s, "max_seconds", 0, allow_none=True)
            if "steps" not in s:
                self.err(path, t("'steps' 목록이 필요"))
            self.steps(f"{path}.steps", s.get("steps", []), loop_depth + 1)
        elif typ == "for_each":
            self.str_(path, s, "var", required=True)
            tg = s.get("target")
            if not (isinstance(tg, dict) and "image" in tg):
                self.err(f"{path}.target", t("image 대상이 필요(화면에서 그 그림을 모두 찾음)"))
            else:
                self.target(f"{path}.target", tg)
            self.int_(path, s, "max", 1)
            self.int_(path, s, "row_tolerance", 0)
            if "reverse" in s and not isinstance(s["reverse"], bool):
                self.err(path, t("'reverse' 는 true/false"))
            if "steps" not in s:
                self.err(path, t("'steps' 목록이 필요"))
            self.steps(f"{path}.steps", s.get("steps", []), loop_depth + 1)
        elif typ == "each":
            # 목록마다: list / range / rows / files / lines 중 정확히 하나
            self.str_(path, s, "var", required=True)
            srcs = [k for k in ("list", "range", "rows", "files", "lines") if k in s]
            if len(srcs) != 1:
                self.err(path, t("list / range / rows / files / lines 중 정확히 하나가 필요"))
            else:
                k = srcs[0]
                v = s[k]
                if k == "list" and (not isinstance(v, (str, list)) or (isinstance(v, str) and not v.strip())):
                    self.err(f"{path}.list", t("변수 이름(글자) 또는 목록이어야 함"))
                if k in ("range", "rows", "files") and not isinstance(v, dict):
                    self.err(f"{path}.{k}", t("객체여야 함"))
                elif k == "range":
                    self.unknown(f"{path}.range", v, {"from", "to", "step"})
                    if "to" not in v:
                        self.err(f"{path}.range", t("'{key}' 필요", key="to"))
                elif k == "rows":
                    self.unknown(f"{path}.rows", v, {"path", "sheet", "header", "from", "to", "cols", "key_col",
                                                     "skip_empty", "group", "group_by"})
                elif k == "files":
                    self.str_(f"{path}.files", v, "path", required=True)
                    self.unknown(f"{path}.files", v, {"path", "pattern", "sub", "kind", "sort"})
                if k == "lines" and not isinstance(v, str):
                    self.err(f"{path}.lines", t("변수 이름 또는 글자여야 함"))
            self.str_(path, s, "index_var")
            self.int_(path, s, "max", 1)
            if "reverse" in s and not isinstance(s["reverse"], bool):
                self.err(path, t("'reverse' 는 true/false"))
            if "steps" not in s:
                self.err(path, t("'steps' 목록이 필요"))
            self.steps(f"{path}.steps", s.get("steps", []), loop_depth + 1)
        elif typ == "group":
            if "steps" not in s:
                self.err(path, t("'steps' 목록이 필요"))
            self.steps(f"{path}.steps", s.get("steps", []), loop_depth)
        elif typ in ("break", "continue"):
            if loop_depth == 0:
                self.err(path, t("'{type}'는 repeat·for_each 안에서만 쓸 수 있음", type=typ))
        elif typ == "call":
            self.str_(path, s, "macro", required=True)
            self.str_(path, s, "result_var")
        elif typ == "set_result":
            if "value" not in s:
                self.err(path, t("'value' 필요"))
        elif typ == "launch":
            # 프로그램·주소 실행(예: "steam://rungameid/1258080", "C:/.../app.exe")
            self.str_(path, s, "target", required=True)
        elif typ in ("close_window", "wait_window"):
            self.num(path, s, "timeout", 0)
        elif typ == "snapshot":
            self.str_(path, s, "name")
        elif typ == "read_number":
            # 화면 영역의 숫자를 읽어 정수로 변수에 넣기
            self.str_(path, s, "var", required=True)
            r = s.get("region")
            if not (isinstance(r, (list, tuple)) and len(r) == 4 and all(_is_num(n) for n in r))                     or r[2] <= 0 or r[3] <= 0:
                self.err(f"{path}.region", t("[x, y, 너비, 높이] 가 필요 (너비·높이 > 0)"))
            self.str_(path, s, "anchor")
            self.str_(path, s, "font")
            if "part" in s and s["part"] not in ("first", "second"):
                self.err(f"{path}.part", t("'first' 또는 'second'"))
            if "memory" in s:
                # 메모리로 먼저 읽고, 안 되면(꺼짐·어긋남·범위 밖) 화면으로. {"value": 이름|주소, "range": [최소, 최대]}
                mm_ = s["memory"]
                if not isinstance(mm_, dict):
                    self.err(f"{path}.memory", t("객체여야 함"))
                else:
                    self.mem_value(f"{path}.memory.value", mm_.get("value"))
                    rg = mm_.get("range")
                    if rg is not None and not (isinstance(rg, (list, tuple)) and len(rg) == 2 and all(_is_num(n) for n in rg)):
                        self.err(f"{path}.memory.range", t("[최소, 최대] 숫자 두 개"))
                    self.unknown(f"{path}.memory", mm_, {"value", "range"})
        elif typ == "text":
            # 글자 만들기: text(안의 {변수} 채움) → action 으로 가공 → var
            from .textops import TEXT_ACTIONS
            self.str_(path, s, "var", required=True)
            a = s.get("action", "set")
            if a not in TEXT_ACTIONS:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(TEXT_ACTIONS)))
            if a == "join":
                self.str_(path, s, "list", required=True)
            elif "text" not in s or not isinstance(s["text"], str):
                self.err(path, t("'text' 문자열이 필요"))
            if a == "replace" and not isinstance(s.get("find"), str):
                self.err(path, t("'{k}' 필요", k="find"))
            if a == "extract":
                self.str_(path, s, "pattern", required=True)
            for k in ("pattern", "find"):
                if s.get("regex" if k == "find" else k) and isinstance(s.get(k), str):
                    import re as _re
                    try:
                        _re.compile(s[k])
                    except _re.error as e:
                        self.err(f"{path}.{k}", t("찾는 규칙(정규식)이 잘못됨: {error}", error=e))
            for k in ("index", "start", "count", "width", "group"):
                if k in s:
                    self.int_(path, s, k)
        elif typ == "date":
            # 날짜: from(없으면 지금) + add → format 글자 / diff = to - from
            from .textops import DATE_ACTIONS
            self.str_(path, s, "var", required=True)
            a = s.get("action", "format")
            if a not in DATE_ACTIONS:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(DATE_ACTIONS)))
            add = s.get("add")
            if add is not None:
                if not isinstance(add, dict) or not set(add) <= {"years", "months", "days", "hours", "minutes"}:
                    self.err(f"{path}.add", t("years / months / days / hours / minutes 숫자로"))
                else:
                    for k in add:
                        self.num(f"{path}.add", add, k)
            if "unit" in s and s["unit"] not in ("days", "hours", "minutes"):
                self.err(f"{path}.unit", t("days / hours / minutes 중 하나"))
        elif typ == "calc":
            self.str_(path, s, "var", required=True)
            self.str_(path, s, "expr", required=True)
        elif typ == "file":
            from .fileops import ACTIONS as F_ACTIONS, OVERWRITE
            a = s.get("action", "copy")
            if a not in F_ACTIONS:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(F_ACTIONS)))
            self.str_(path, s, "path", required=True)
            if a in ("copy", "move"):
                self.str_(path, s, "to", required=True)
            if a == "rename":
                self.str_(path, s, "name", required=True)
            if a in ("list", "exists", "info", "read_text", "read_csv"):
                self.str_(path, s, "var", required=True)
            if a == "write_csv" and not isinstance(s.get("data"), (str, list)):
                self.err(path, t("'data' 필요(표가 든 변수 이름 또는 줄 목록)"))
            if a == "write_text" and not isinstance(s.get("text"), str):
                self.err(path, t("'text' 문자열이 필요"))
            if "overwrite" in s and s["overwrite"] not in OVERWRITE:
                self.err(f"{path}.overwrite", t("{opts} 중 하나", opts=" / ".join(OVERWRITE)))
            if "permanent" in s and (not isinstance(s["permanent"], bool) or a != "delete"):
                self.err(f"{path}.permanent", t("delete 에서만 true/false"))
            if "kind" in s and s["kind"] not in ("files", "folders"):
                self.err(f"{path}.kind", "files / folders")
            if "sort" in s and s["sort"] not in ("name", "modified", "newest"):
                self.err(f"{path}.sort", "name / modified / newest")
        elif typ == "ask":
            kinds = ("input", "confirm", "choose", "file", "folder")
            if s.get("kind", "input") not in kinds:
                self.err(f"{path}.kind", t("{opts} 중 하나", opts=" / ".join(kinds)))
            self.str_(path, s, "var", required=True)
            if "message" in s and not isinstance(s["message"], str):
                self.err(f"{path}.message", t("문자열이어야 함"))
            if s.get("kind") == "choose" and not isinstance(s.get("options"), (list, str)):
                self.err(path, t("'{k}' 필요", k="options"))
        elif typ == "notify":
            from .notify import CHANNELS
            ch = s.get("channels", ["toast"])
            ch = [ch] if isinstance(ch, str) else ch
            if not isinstance(ch, list) or not ch or any(c not in CHANNELS for c in ch):
                self.err(f"{path}.channels", t("{opts} 중에서", opts=" / ".join(CHANNELS)))
            self.str_(path, s, "message", required=True)
            if "level" in s and s["level"] not in ("info", "warning", "error"):
                self.err(f"{path}.level", "info / warning / error")
            if "must" in s and not isinstance(s["must"], bool):
                self.err(f"{path}.must", "true/false")
        elif typ == "mail":
            from .mail import ACTIONS as M_ACTIONS, VIAS
            via = s.get("via", "outlook")
            if via not in VIAS:
                self.err(f"{path}.via", t("{opts} 중 하나", opts=" / ".join(VIAS)))
            if via == "web" and not s.get("service"):
                self.err(path, t("'{k}' 필요", k="service"))
            if via == "server":
                self.str_(path, s, "account", required=True)
            a = s.get("action", "find")
            if a not in M_ACTIONS:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(M_ACTIONS)))
            if a in ("find", "read", "save_attachments"):
                self.str_(path, s, "var", required=a in ("find", "read"))
            if a in ("read", "save_attachments", "mark_read", "move") and "mail" not in s:
                self.err(path, t("'{k}' 필요", k="mail"))
            if a == "move" and not (s.get("to_folder") or s.get("to")):
                self.err(path, t("'{k}' 필요", k="to_folder"))
            if a == "send":
                self.str_(path, s, "to", required=True)
                if "send_now" in s and not isinstance(s["send_now"], bool):
                    self.err(f"{path}.send_now", "true/false")
            if "overwrite" in s:
                from .fileops import OVERWRITE
                if s["overwrite"] not in OVERWRITE:
                    self.err(f"{path}.overwrite", " / ".join(OVERWRITE))
            for k in ("days", "max"):
                if k in s:
                    self.num(path, s, k, 0)
        elif typ == "list":
            from .listops import ACTIONS as L_ACTIONS
            self.str_(path, s, "var", required=True)
            a = s.get("action", "add")
            if a not in L_ACTIONS:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(L_ACTIONS)))
            if a == "add" and "value" not in s:
                self.err(path, t("'{k}' 필요", k="value"))
            if "by" in s and not isinstance(s["by"], (str, list)):
                self.err(f"{path}.by", t("칸 이름(쉼표로 여러 개) 또는 [{key, order, as}] 목록"))
            if isinstance(s.get("by"), list):
                for i, k in enumerate(s["by"]):
                    if not isinstance(k, dict) or not set(k) <= {"key", "order", "as"}:
                        self.err(f"{path}.by[{i}]", t("{key, order, as} 모양이어야 함"))
                    elif k.get("order", "asc") not in ("asc", "desc") or k.get("as", "auto") not in ("auto", "number", "date", "text"):
                        self.err(f"{path}.by[{i}]", "order asc/desc, as auto/number/date/text")
            if "order" in s and s["order"] not in ("asc", "desc"):
                self.err(f"{path}.order", "asc / desc")
            self.str_(path, s, "to_var")
        elif typ == "memory":
            # 메모리 매크로(부가 기능): 대상 프로그램의 값을 읽어 변수로. value = 저장한 이름 또는 주소 모양
            # 혼자 하는 게임용 쓰기: write(set 값) / freeze(set 값, interval) / unfreeze
            a = s.get("action", "read")
            if a not in ("read", "write", "freeze", "unfreeze"):
                self.err(f"{path}.action", "read / write / freeze / unfreeze")
            self.mem_value(f"{path}.value", s.get("value"))
            if a == "read":
                self.str_(path, s, "var", required=True)
            if a in ("write", "freeze") and "set" not in s:
                self.err(path, t("'set'(넣을 값)이 필요"))
            if a == "freeze":
                self.num(path, s, "interval", 0.01)
        elif typ == "pdf":
            acts = ("text", "extract", "table")
            a = s.get("action", "text")
            if a not in acts:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(acts)))
            self.str_(path, s, "path", required=True)
            self.str_(path, s, "var", required=True)
            if a == "extract":
                self.str_(path, s, "pattern", required=True)
                if isinstance(s.get("pattern"), str):
                    import re as _re
                    try:
                        _re.compile(s["pattern"])
                    except _re.error as e:
                        self.err(f"{path}.pattern", t("찾는 규칙(정규식)이 잘못됨: {error}", error=e))
            for k in ("index", "group"):
                if k in s:
                    self.int_(path, s, k)
            if "via" in s and s["via"] not in ("builtin", "word"):
                self.err(f"{path}.via", "builtin / word")
        elif typ == "clipboard":
            from .clipboard import ACTIONS as CB_ACTIONS
            a = s.get("action", "read")
            if a not in CB_ACTIONS:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(CB_ACTIONS)))
            if a in ("read", "copy", "files"):
                self.str_(path, s, "var", required=True)
            if a == "write" and not isinstance(s.get("text"), str):
                self.err(path, t("'text' 문자열이 필요"))
            if a == "save_image":
                self.str_(path, s, "path", required=True)
        elif typ in ("excel", "word", "hwp"):
            # 오피스 스텝(COM): 셀·누름틀·책갈피를 이름으로. 글자 안 {변수} 는 실행 때 바뀜
            from .office import ACTIONS, REQUIRED
            a = s.get("action")
            if a not in ACTIONS[typ]:
                self.err(f"{path}.action", t("{opts} 중 하나", opts=" / ".join(ACTIONS[typ])))
            else:
                for k in REQUIRED.get((typ, a), []):
                    if k not in s:
                        self.err(path, t("'{k}' 필요", k=k))
            for k in ("path", "sheet", "cell", "var", "find", "name"):
                if k in s and not isinstance(s[k], (str, int)):
                    self.err(f"{path}.{k}", t("문자열이어야 함"))
            for k in ("visible", "pdf"):
                if k in s and not isinstance(s[k], bool):
                    self.err(f"{path}.{k}", "true/false")
        elif typ == "web":
            # 웹 요소 스텝(에고라이트). action: goto / click / fill / select / press / wait / read / screenshot / url
            from .web import ACTIONS
            a = s.get("action")
            if a not in ACTIONS or a in ("exists", "elements", "script", "upload"):
                self.err(f"{path}.action", t("goto / click / fill / select / press / wait / read / screenshot / url / table / download / close 중 하나"))
            else:
                if a == "goto":
                    self.str_(path, s, "url", required=True)
                if a in ("click", "fill", "select", "wait", "read"):
                    self.str_(path, s, "selector", required=True)
                if a in ("fill", "select", "press"):
                    v = s.get("text")
                    if not (isinstance(v, str) or (isinstance(v, dict) and set(v) == {"var"})):
                        self.err(f"{path}.text", t("문자열 또는 {var: 이름} 이 필요"))
                if a in ("read", "url", "table"):
                    self.str_(path, s, "var", required=a in ("read", "table"))
                if a == "download":
                    if not s.get("selector") and not s.get("url"):
                        self.err(path, t("내려받을 링크(selector) 또는 주소(url)가 필요"))
                    self.str_(path, s, "path")
                    if "overwrite" in s:
                        from .fileops import OVERWRITE
                        if s["overwrite"] not in OVERWRITE:
                            self.err(f"{path}.overwrite", " / ".join(OVERWRITE))
            self.str_(path, s, "page")
            self.str_(path, s, "name")
            if "state" in s and s["state"] not in ("visible", "attached", "hidden", "detached"):
                self.err(f"{path}.state", "visible / attached / hidden / detached")
        elif typ == "set":
            # 변수에 값 넣기(value) 또는 숫자 더하기(add, 없던 변수는 0에서 시작)
            self.str_(path, s, "var", required=True)
            if ("value" in s) == ("add" in s):
                self.err(path, t("value(값 넣기) 또는 add(숫자 더하기) 중 하나가 필요"))
            elif "add" in s and not _is_num(s["add"]):
                self.err(f"{path}.add", t("숫자여야 함"))

    def settings(self, path: str, d: dict, partial: bool):
        for k in DEFAULT_SETTINGS:
            if k not in d:
                continue
            if k == "input_backend":
                if d[k] not in ("sendinput", "pyautogui"):
                    self.err(f"{path}.{k}", t("'sendinput' 또는 'pyautogui'"))
            elif k == "timeout":
                self.num(path, d, k, 0, allow_none=True)
            elif k == "confidence":
                self.num(path, d, k, 0, 1)
            elif k == "color_check":
                self.num(path, d, k, 0, 1, allow_none=True)
            elif k == "stable_frames":
                self.int_(path, d, k, 1)
            else:
                self.num(path, d, k, 0)


# 스텝별 허용 필드 (공통 필드·설정 키 제외)
STEP_SPECS: Dict[str, set] = {
    "click": {"target", "button", "count", "timeout", "verify"},
    "move": {"target", "timeout"},
    "scroll": {"target", "amount", "horizontal", "timeout"},
    "menu": {"path"},
    "drag": {"from", "to", "duration_ms", "button", "timeout"},
    "mouse_down": {"target", "button", "timeout"},
    "mouse_up": {"target", "button", "timeout"},
    "key": {"keys", "count"},
    "type_text": {"text", "target", "timeout"},
    "wait": {"until", "timeout"},
    "delay": {"seconds"},
    "remember": {"var", "what", "timeout"},
    "if": {"cond", "within", "then", "else"},
    "repeat": {"times", "until", "while", "forever", "max_times", "max_seconds", "steps"},
    "group": {"steps"},
    "each": {"var", "list", "range", "rows", "files", "lines", "skip_empty", "index_var", "max", "reverse", "steps"},
    "for_each": {"var", "target", "max", "row_tolerance", "reverse", "steps"},
    "break": set(),
    "continue": set(),
    "call": {"macro", "result_var"},
    "set_result": {"value"},
    "set": {"var", "value", "add"},
    "text": {"var", "text", "action", "find", "with", "regex", "pattern", "group", "all", "sep", "index", "start",
             "count", "width", "char", "list"},
    "date": {"var", "action", "from", "to", "add", "format", "unit"},
    "calc": {"var", "expr"},
    "clipboard": {"action", "var", "text", "path", "timeout"},
    "pdf": {"action", "path", "var", "pattern", "group", "all", "index", "header", "via"},
    "memory": {"action", "value", "var", "set", "interval"},
    "list": {"var", "action", "value", "unique", "by", "order", "to_var"},
    "mail": {"via", "service", "account", "action", "var", "folder", "mail_folder", "from", "subject", "unread",
             "has_attachment", "days", "max", "mail", "path", "pattern", "overwrite", "to_folder", "to", "cc", "body",
             "attachments", "send_now"},
    "ask": {"kind", "var", "title", "message", "options", "default", "timeout"},
    "notify": {"channels", "title", "message", "level", "url", "must"},
    "file": {"action", "path", "to", "name", "overwrite", "var", "pattern", "sub", "kind", "sort", "text", "append",
             "encoding", "data", "header", "sep", "permanent"},
    "read_number": {"var", "region", "anchor", "part", "font", "memory"},
    "return": {"value"},
    "stop": {"reason"},
    "launch": {"target"},
    "close_window": {"timeout"},
    "wait_window": {"timeout"},
    "snapshot": {"name"},
    "comment": {"text"},
    "web": {"action", "selector", "url", "text", "var", "page", "timeout", "state", "name", "path", "overwrite"},
    "excel": {"action", "path", "sheet", "cell", "value", "var", "name", "visible", "pdf", "printer", "to_file", "copies",
              "format", "overwrite"},
    "word": {"action", "path", "find", "text", "name", "var", "visible", "pdf", "printer", "to_file", "copies"},
    "hwp": {"action", "path", "find", "text", "name", "var", "visible", "pdf", "printer", "to_file", "copies"},
}

MACRO_KEYS = {"version", "name", "description", "window", "repeat", "on_iteration_fail",
              "settings", "run_hotkey", "stop_hotkey", "steps", "ai_rescue", "rescues", "self_heal", "unstick"}
UNSTICK_KEYS = {"on", "repeat_n", "window_s", "verify_s", "rest_min", "same_screen", "max_distinct", "ai", "close_targets",
                "recover_macro", "generic_close"}
SELF_HEAL_KEYS = {"mode", "propose_after_uses", "watch_vars", "stall_repeats", "score_window", "score_margin", "slow_window",
                  "slow_factor", "slow_min_seconds", "slow_count"}
AI_RESCUE_KEYS = {"on", "per_hour", "per_day", "forbid_regions", "forbid_words"}
RESCUE_KEYS = {"step", "screen", "size", "steps", "added", "reason", "why", "by", "fails", "off", "uses"}


def validate_macro(data: Any) -> List[str]:
    """오류 목록을 돌려준다. 빈 목록이면 정상."""
    c = _Checker()
    if not isinstance(data, dict):
        return [t("(최상위): 매크로는 객체여야 함")]
    p = "macro"
    c.unknown(p, data, MACRO_KEYS)
    if data.get("version") != VERSION:
        c.err(f"{p}.version", t("{version} 이어야 함", version=VERSION))
    c.str_(p, data, "name", required=True)

    w = data.get("window")
    if w is not None:
        if not isinstance(w, dict) or not ({"title", "process"} & set(w)):
            c.err(f"{p}.window", t("title 또는 process 가 필요"))
        else:
            c.unknown(f"{p}.window", w, {"title", "process", "size", "activate", "background", "wrapper", "hidden"})
            if "hidden" in w and not isinstance(w["hidden"], bool):
                c.err(f"{p}.window.hidden", t("true/false (true = 숨겨서 실행)"))
            elif w.get("hidden") and not w.get("background"):
                c.err(f"{p}.window.hidden", t("숨겨서 실행은 background: true 와 같이 써야 함"))
            if "background" in w and not isinstance(w["background"], bool):
                c.err(f"{p}.window.background", "true/false")
            if "wrapper" in w and not isinstance(w["wrapper"], bool):
                c.err(f"{p}.window.wrapper", t("true/false (false = 호환 모드)"))
            if "size" in w and not _xy(w["size"]):
                c.err(f"{p}.window.size", t("[너비, 높이] 형식이어야 함"))

    r = data.get("repeat", {"times": 1})
    if not isinstance(r, dict) or len(r) != 1 or not ({"times", "forever"} & set(r)):
        c.err(f"{p}.repeat", t("{\"times\": N} 또는 {\"forever\": true}"))
    elif "times" in r:
        c.int_(f"{p}.repeat", r, "times", 1)
    elif r["forever"] is not True:
        c.err(f"{p}.repeat.forever", t("true 여야 함"))

    f = data.get("on_iteration_fail")
    if f is not None:
        if not isinstance(f, dict):
            c.err(f"{p}.on_iteration_fail", t("객체여야 함"))
        else:
            c.unknown(f"{p}.on_iteration_fail", f, {"action", "max_consecutive", "delay"})
            if f.get("action", "retry") not in ("retry", "stop"):
                c.err(f"{p}.on_iteration_fail.action", t("'retry' 또는 'stop'"))
            c.int_(f"{p}.on_iteration_fail", f, "max_consecutive", 1, allow_none=True)
            c.num(f"{p}.on_iteration_fail", f, "delay", 0)

    s = data.get("settings", {})
    if not isinstance(s, dict):
        c.err(f"{p}.settings", t("객체여야 함"))
    else:
        c.unknown(f"{p}.settings", s, set(DEFAULT_SETTINGS))
        c.settings(f"{p}.settings", s, partial=False)

    for k in ("run_hotkey", "stop_hotkey"):
        if k in data and not isinstance(data[k], str):
            c.err(f"{p}.{k}", t("문자열이어야 함"))

    ar = data.get("ai_rescue")
    if ar is not None:
        if not isinstance(ar, dict):
            c.err(f"{p}.ai_rescue", t("객체여야 함"))
        else:
            c.unknown(f"{p}.ai_rescue", ar, AI_RESCUE_KEYS)
            if "on" in ar and not isinstance(ar["on"], bool):
                c.err(f"{p}.ai_rescue.on", "true/false")
            c.int_(f"{p}.ai_rescue", ar, "per_hour", 0)
            c.int_(f"{p}.ai_rescue", ar, "per_day", 0)
            fr = ar.get("forbid_regions", [])
            if not isinstance(fr, list) or not all(isinstance(r, (list, tuple)) and len(r) == 4 and all(_is_num(n) for n in r) for r in fr):
                c.err(f"{p}.ai_rescue.forbid_regions", t("[[x, y, 너비, 높이], ...] 형식이어야 함"))
            fw = ar.get("forbid_words", [])
            if not isinstance(fw, list) or not all(isinstance(w, str) for w in fw):
                c.err(f"{p}.ai_rescue.forbid_words", t("문자열 목록이어야 함"))
    sh = data.get("self_heal")
    if sh is not None:
        if not isinstance(sh, dict):
            c.err(f"{p}.self_heal", t("객체여야 함"))
        else:
            c.unknown(f"{p}.self_heal", sh, SELF_HEAL_KEYS)
            if sh.get("mode", "off") not in ("off", "notify", "tune", "propose"):
                c.err(f"{p}.self_heal.mode", "off / notify / tune / propose")
            wv = sh.get("watch_vars", [])
            if not isinstance(wv, list) or not all(isinstance(x, str) for x in wv):
                c.err(f"{p}.self_heal.watch_vars", t("문자열 목록이어야 함"))
            for k in ("stall_repeats", "score_window", "slow_window", "slow_count", "propose_after_uses"):
                c.int_(f"{p}.self_heal", sh, k, 1)
            for k in ("score_margin", "slow_factor", "slow_min_seconds"):
                c.num(f"{p}.self_heal", sh, k, 0)
    us = data.get("unstick")                     # 헛돎 알아채기·스스로 고치기(engine/selfheal.py)
    if us is not None:
        if not isinstance(us, dict):
            c.err(f"{p}.unstick", t("객체여야 함"))
        else:
            c.unknown(f"{p}.unstick", us, UNSTICK_KEYS)
            for k in ("repeat_n", "same_screen", "max_distinct"):
                c.int_(f"{p}.unstick", us, k, 1)
            for k in ("window_s", "verify_s", "rest_min"):
                c.num(f"{p}.unstick", us, k, 0)
            ct = us.get("close_targets", [])
            if not isinstance(ct, list):
                c.err(f"{p}.unstick.close_targets", t("목록이어야 함"))
            else:
                for i, tg in enumerate(ct):
                    c.target(f"{p}.unstick.close_targets[{i}]", tg)
    rs = data.get("rescues")
    if rs is not None:
        if not isinstance(rs, list):
            c.err(f"{p}.rescues", t("목록이어야 함"))
        else:
            for i, r in enumerate(rs):
                rp = f"{p}.rescues[{i}]"
                if not isinstance(r, dict):
                    c.err(rp, t("객체여야 함"))
                    continue
                c.unknown(rp, r, RESCUE_KEYS)
                c.str_(rp, r, "step", required=True)
                c.str_(rp, r, "screen", required=True)
                c.steps(f"rescues[{i}].steps", r.get("steps", []), 0)

    if "steps" not in data:
        c.err(p, t("'steps' 목록이 필요"))
    c.steps("steps", data.get("steps", []), 0)
    return c.errors


def ensure_valid(data: Any) -> dict:
    errors = validate_macro(data)
    if errors:
        raise MacroError(errors)
    return data


def new_macro(name: str, steps: Optional[list] = None, **fields) -> dict:
    d = {"version": VERSION, "name": name, "repeat": {"times": 1}, "steps": steps or []}
    d.update(fields)
    return d


def load_macro(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return ensure_valid(json.load(f))


def save_macro(data: dict, path: str) -> None:
    ensure_valid(data)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
