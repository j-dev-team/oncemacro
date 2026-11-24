"""
매크로 v2 실행기.

실행 의미는 docs/engine_v2_design.md §6 표를 그대로 따른다.
- 모든 스텝은 성공하거나 StepFailed 를 던진다. 조용히 넘어가는 경우는 on_fail: "skip" 뿐.
- 정지 신호는 모든 대기 안에서 확인한다.
- Qt 에 의존하지 않는다. 진행 상황은 on_event 콜백으로만 알린다(print 안 씀).
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .backends import (Clock, Input, Match, Pos, Vision, Window, WindowFactory, WindowNotFound,
                       null_window_factory)
from .i18n import current, row_item, t
from .library import Library, MacroNotFound
from .model import (DEFAULT_ON_ITERATION_FAIL, DEFAULT_SETTINGS, MacroError, _Checker,
                    ensure_valid)

EventCallback = Callable[[dict], None]


# ---------------------------------------------------------------- 제어 흐름

def _pic(name) -> str:
    """그림 파일 이름을 사람이 읽기 쉽게: 폴더·확장자·'__고침…' 꼬리를 뗀다."""
    import re as _re
    b = str(name).replace("\\", "/").split("/")[-1]
    b = _re.sub(r"__(?:고침|fix)\d+", "", b)
    return b.rsplit(".", 1)[0]


def repair_sentence(kind: str, status: str, target, old=None, new=None, why=None) -> str:
    """고침 기록에 보일 쉬운 문장(내부 낱말 없이)."""
    tail = (" — " + str(why)) if why else ""
    if kind == "recapture":
        p = _pic(target)
        if status == "trial":
            return t("'{p}' 그림을 지금 화면에서 새로 따서 시험 중(옛 그림은 예비로 둠)", p=p)
        if status == "applied":
            return t("확정: '{p}' 그림을 새로 딴 것으로 바꿈(옛 그림은 예비로 둠)", p=p) + tail
        return t("되돌림: '{p}' 그림을 원래 것으로 되돌림", p=p) + tail
    if kind == "confidence":
        p = _pic(target)
        o, n = f"{float(old):.2f}" if old is not None else "?", f"{float(new):.2f}" if new is not None else "?"
        if status == "trial":
            return t("'{p}' 그림의 인식 기준을 {old} → {new} 로 낮춰 시험 중", p=p, old=o, new=n) + tail
        if status == "applied":
            return t("확정: '{p}' 그림의 인식 기준을 {old} → {new} 로 낮춤", p=p, old=o, new=n) + tail
        return t("되돌림: '{p}' 그림의 인식 기준을 {old} 로 되돌림", p=p, old=o) + tail
    if kind == "timeout":
        step = str(target).split("|")[0].replace("/", " ")
        if status == "trial":
            return t("'{s}' 스텝의 기다리는 시간을 {old}초 → {new}초로 늘려 시험 중", s=step, old=old, new=new) + tail
        if status == "applied":
            return t("확정: '{s}' 스텝의 기다리는 시간을 {old}초 → {new}초로 늘림", s=step, old=old, new=new) + tail
        return t("되돌림: '{s}' 스텝의 기다리는 시간을 {old}초로 되돌림", s=step, old=old) + tail
    return str(why or "")


# 막혔을 때 해결을 시도하는 스텝 종류(흐름·변수 스텝은 안의 스텝이 대신 시도)
RESCUABLE = {"click", "move", "drag", "scroll", "mouse_down", "mouse_up", "key", "type_text", "wait", "remember",
             "read_number", "web", "wait_window"}


class StepFailed(Exception):
    def __init__(self, reason: str, path: Optional[str] = None, step_type: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.path = path
        self.step_type = step_type


class _Flow(Exception):
    """StepFailed 가 아닌 제어 흐름 신호. on_fail 로 잡히지 않는다."""


class _Break(_Flow):
    pass


class _Continue(_Flow):
    pass


class _Return(_Flow):
    def __init__(self, value):
        self.value = value


class _Stopped(_Flow):
    pass


class _MacroStop(_Flow):
    def __init__(self, reason: str, path: str):
        self.reason = reason
        self.path = path


@dataclass
class Result:
    status: str                       # ok | failed | stopped
    value: Any = "ok"
    iterations: int = 0
    failed_iterations: int = 0
    error: Optional[dict] = None      # {path, type, reason}
    duration: float = 0.0

    def to_dict(self) -> dict:
        return {"status": self.status, "value": self.value, "iterations": self.iterations,
                "failed_iterations": self.failed_iterations, "error": self.error,
                "duration": round(self.duration, 3)}


@dataclass
class Context:
    vars: Dict[str, Any] = field(default_factory=dict)


GLOBAL_PREFIX = "전역_"
GLOBAL_PREFIXES = ("전역_", "global_")      # 영어 이름도 같은 뜻(11-24)


class SharedVars(dict):
    """이름이 '전역_'으로 시작하는 변수는 부른 매크로·불린 매크로·반복 회차가 모두 같이 쓰는 저장소에 둔다
    (맨 위 실행이 끝날 때까지 유지). 나머지는 이 매크로 회차 안에서만."""

    def __init__(self, shared: Dict[str, Any]):
        super().__init__()
        self._shared = shared

    @staticmethod
    def _g(k) -> bool:
        return isinstance(k, str) and k.startswith(GLOBAL_PREFIXES)

    def __getitem__(self, k):
        return self._shared[k] if self._g(k) else super().__getitem__(k)

    def __setitem__(self, k, v):
        if self._g(k):
            self._shared[k] = v
        else:
            super().__setitem__(k, v)

    def __contains__(self, k):
        return k in self._shared if self._g(k) else super().__contains__(k)

    def get(self, k, default=None):
        return self._shared.get(k, default) if self._g(k) else super().get(k, default)


# ---------------------------------------------------------------- 조건 폴링

def _close(a: Pos, b: Pos, px: float) -> bool:
    return abs(a[0] - b[0]) <= px and abs(a[1] - b[1]) <= px


def _target_label(tg: dict) -> str:
    if "image" in tg:
        return str(tg["image"]).replace("\\", "/").split("/")[-1]
    if "color" in tg:
        where = tuple(tg["at"]) if "at" in tg else t("영역{region}", region=tuple(tg['region']))
        return t("색{color}@{where}", color=tuple(tg['color']), where=where)
    if "vivid" in tg:
        return t("선명한 색@영역{region}", region=tuple(tg['region']))
    if "point" in tg:
        return t("좌표{point}", point=tuple(tg['point']))
    if "element" in tg:
        from .win_uia import label
        return t("창 요소 {label}", label=label(tg["element"]))
    return t("변수 {var}", var=tg.get('var'))


class _Probe:
    """조건 하나를 여러 번 확인하며 상태(연속 프레임 수, 사라진 시각 등)를 쌓는다.
    poll() 은 True / False / None(아직 판단 중) 을 돌려준다."""

    def __init__(self, runner: "Runner", cond: dict, ctx: Context, settings: dict,
                 stable: bool = False):
        self.r = runner
        self.stable = stable      # True: 클릭 위치를 정할 때 — 연속 프레임 같은 위치여야 인정
        self.cond = cond
        self.ctx = ctx
        self.s = settings
        self.kind = "var" if "var" in cond else next(
            k for k in ("exists", "gone", "not", "all", "any", "web", "window_size", "file", "memory") if k in cond)
        self.children: List[_Probe] = []
        if self.kind == "not":
            self.children = [_Probe(runner, cond["not"], ctx, settings, stable)]
        elif self.kind in ("all", "any"):
            self.children = [_Probe(runner, c, ctx, settings, stable) for c in cond[self.kind]]
        self.count = 0
        self.last: Optional[Pos] = None
        self.found_pos: Optional[Pos] = None
        self.best = 0.0
        self.absent_since: Optional[float] = None

    def max_for(self) -> float:
        own = float(self.cond.get("for", 0)) if self.kind == "gone" else 0.0
        return max([own] + [c.max_for() for c in self.children])

    def poll(self, now: float) -> Optional[bool]:
        k = self.kind
        if k == "exists":
            tg = self.cond["exists"]
            pos, score = self.r._sample(tg, self.ctx, self.s)
            self.best = max(self.best, score)
            if "point" in tg or "var" in tg:
                self.found_pos = pos
                return pos is not None
            if pos is None:
                self.count, self.last = 0, None
                return False
            if self.last is not None and _close(pos, self.last, self.s["stable_px"]):
                self.count += 1
            else:
                self.count = 1
            self.last = pos
            need = self.s["stable_frames"] if self.stable else 1
            if self.count >= need:
                self.found_pos = pos
                return True
            return None
        if k == "gone":
            pos, score = self.r._sample(self.cond["gone"], self.ctx, self.s)
            self.best = max(self.best, score)
            if pos is not None:
                self.absent_since = None
                return False
            if self.absent_since is None:
                self.absent_since = now
            return True if now - self.absent_since >= float(self.cond.get("for", 0)) else None
        if k == "var":
            return _compare_var(self.cond, self.ctx.vars, now)
        if k == "web":
            return self.r._web_has(self.cond["web"])
        if k == "window_size":
            return self.r._window_size_is(self.cond["window_size"])
        if k == "file":
            return self.r._file_cond(self.cond["file"], self.ctx)
        if k == "memory":
            mc = self.cond["memory"]
            v = self.r._mem_read(mc.get("value"), self.ctx)
            self.mem_last = v
            if mc.get("changed"):
                if not hasattr(self, "mem_base"):
                    self.mem_base = v               # 처음 읽은 값에서 바뀌면 참
                    return False
                return v != self.mem_base
            op = next(o for o in ("eq", "ne", "gt", "lt", "ge", "le") if o in mc)
            return _compare_var({"var": "_m", op: mc[op]}, {"_m": v}, now)
        if k == "not":
            v = self.children[0].poll(now)
            return None if v is None else (not v)
        results = [c.poll(now) for c in self.children]
        if k == "all":
            if False in results:
                return False
            return None if None in results else True
        if True in results:
            return True
        return None if None in results else False

    def detail(self) -> str:
        k = self.kind
        if k in ("exists", "gone"):
            tg = self.cond[k]
            if "image" in tg:
                conf = tg.get("confidence", self.s["confidence"])
                return t("{label} 최고 점수 {best:.2f} (기준 {conf:.2f})", label=_target_label(tg), best=self.best, conf=conf)
            if "blob_depth" in tg:
                return t("{label} 덩어리 두께 {depth:.1f}px (기준 {ref})", label=_target_label(tg),
                         depth=self.best * float(tg['blob_depth']), ref=tg['blob_depth'])
            return _target_label(tg)
        if k == "var":
            return t("변수 {var} = {value}", var=self.cond['var'], value=repr(self.ctx.vars.get(self.cond['var'])))
        if k == "web":
            return t("웹 요소 {selector}", selector=self.cond['web'].get('selector'))
        if k == "file":
            return t("파일 {path}", path=self.cond["file"].get("path"))
        if k == "memory":
            v = self.cond["memory"].get("value")
            return t("메모리 값 {name} = {value}", name=v if isinstance(v, str) else v.get("offset"),
                     value=repr(getattr(self, "mem_last", None)))
        return ", ".join(c.detail() for c in self.children)


def _now_value(v, now: Optional[float], vars_: Optional[dict] = None):
    """{"now": true, "add": 초} 이면 지금 시각(초) + add, {"var": 이름} 이면 그 변수 값(없으면 None), 아니면 그대로."""
    if isinstance(v, dict):
        if v.get("now") and now is not None:
            return now + float(v.get("add", 0))
        if "var" in v and vars_ is not None:
            return vars_.get(v["var"])
    return v


def _cond_value(w, now, vars_):
    """비교할 값: {"now"}·{"var"} 는 그 값, 글자 안 {변수} 는 채운 글자."""
    w = _now_value(w, now, vars_)
    if isinstance(w, str) and "{" in w:
        from .textops import fill
        w = fill(w, vars_)[0]
    return w


def _compare_var(c: dict, vars_: dict, now: Optional[float] = None) -> bool:
    from .textops import TEXT_OPS, coerce_pair, lookup, text_compare
    name = c["var"]
    gone = object()
    found = lookup(vars_, name, gone)              # '행.상태' 처럼 표 한 줄의 칸도
    if "is_set" in c:
        return (found is not gone) == bool(c["is_set"])
    v = None if found is gone else found
    for op in TEXT_OPS:                      # 글자 비교: 포함·시작·끝·규칙(정규식)·비었음
        if op in c:
            return text_compare(op, v, _cond_value(c[op], now, vars_))
    for op, fn in (("eq", lambda a, b: a == b), ("ne", lambda a, b: a != b),
                   ("gt", lambda a, b: a > b), ("lt", lambda a, b: a < b),
                   ("ge", lambda a, b: a >= b), ("le", lambda a, b: a <= b)):
        if op in c:
            w = _cond_value(c[op], now, vars_)
            if op in ("gt", "lt", "ge", "le"):
                v2, w = coerce_pair(v, w)     # '1,200' 같은 숫자 글자는 숫자로(같음·다름은 예전 그대로)
            else:
                v2 = v
            try:
                return bool(fn(v2, w))
            except TypeError:
                return False
    return False


def _group_lines(lines: list, n: int, by: Optional[str]) -> list:
    """거래 하나가 여러 줄인 표: n 줄씩, 또는 by 칸에 값이 있는 줄에서 새 묶음 시작.
    묶음 = 첫 줄 값 그대로 + '줄2'·'줄3'… 에 다음 줄들(예: {행.줄2.E}). '줄수' = 묶음 줄 수."""
    groups: list = []
    for it in lines:
        start = (it.get(by) not in (None, "")) if by else (not groups or len(groups[-1]) >= n)
        if start or not groups:
            groups.append([it])
        else:
            groups[-1].append(it)
    out = []
    for g in groups:
        head = dict(g[0])
        for k, extra in enumerate(g[1:], 2):
            head[f"줄{k}"] = extra                  # 두 언어 열쇠 다(언어에 따라 매크로 동작이 달라지면 안 됨)
            head[f"line{k}"] = extra
        head["줄수"] = head["lines"] = len(g)
        out.append(head)
    return out


def _col_name(n: int) -> str:
    """1 → A, 27 → AA"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _col_index(c: str) -> int:
    n = 0
    for ch in c.upper():
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - 64)
    return n or 1


# 글자 안 {변수} 를 실행 때 값으로 바꾸는 칸(오피스·웹 단계는 각자 바꿈). 모르는 이름은 그대로 두고 경고만.
FILL_KEYS = {"type_text": ("text",), "launch": ("target",), "menu": ("path",), "snapshot": ("name",),
             "key": ("keys",), "stop": ("reason",), "set": ("value",), "set_result": ("value",),
             "return": ("value",), "clipboard": ("text", "path"),
             "file": ("path", "to", "name", "pattern", "text"),
             "ask": ("message", "title", "default"), "notify": ("title", "message", "url"),
             "pdf": ("path", "pattern"), "list": ("value",),
             "mail": ("folder", "from", "subject", "path", "pattern", "to", "cc", "body", "service", "mail_folder",
                      "attachments", "to_folder")}


# ---------------------------------------------------------------- 실행기

class Runner:
    def __init__(self, macro: dict, *, vision: Vision, input: Input,
                 clock: Optional[Clock] = None, library: Optional[Library] = None,
                 window_factory: Optional[WindowFactory] = None,
                 on_event: Optional[EventCallback] = None,
                 launcher: Optional[Callable[[str], None]] = None,
                 snapshot_dir: Optional[str] = None,
                 web=None,
                 office=None,
                 rescuer=None,
                 health=None,
                 clipboard=None,
                 asker=None,
                 notifier=None,
                 _call_stack: Tuple[str, ...] = (),
                 _globals: Optional[Dict[str, Any]] = None,
                 _heal=None):
        self.macro = ensure_valid(macro)
        self.name = macro["name"]
        self.vision = vision
        self.input = input
        self.clipboard = clipboard          # 없으면 처음 쓸 때 진짜 클립보드
        self.asker = asker                  # 사람에게 묻는 창(화면 프로그램이 넣음). 없으면 기본값 또는 실패
        self.notifier = notifier            # 알림 보내기(시험에서 바꿈). 없으면 engine.notify.send
        self._real_input = input           # '이 스텝만 잠깐 앞에서' 때 쓰는 진짜 입력(뒤에서 실행이어도 그대로 둠)
        self.clock = clock or Clock()
        self.library = library
        self.window_factory = window_factory or null_window_factory
        self.on_event = on_event
        self.launcher = launcher
        self.snapshot_dir = snapshot_dir
        self.web = web                     # 웹 스텝 실행부(없으면 처음 쓸 때 에고라이트로 만듦)
        self.office = office               # 오피스 스텝(엑셀·한글·워드) 세션. 맨 위 실행이 끝날 때 닫음
        self._office_owner = office is None
        self._memory = None                 # 메모리 매크로(부가 기능): 메모리 단계가 처음 돌 때 붙고 실행 끝에 뗌
        self.memory_reader = None           # 시험용: ProcessReader 대신 쓸 것(pid → 읽기 객체)
        self.memory_pid = None              # 시험용: 대상 프로그램 번호를 직접 줌
        self.rescuer = rescuer             # 막히면 AI 한 번 부르기(engine/rescue.py). 없으면 저장된 해결 규칙만 씀
        from collections import deque
        self._recent = deque(maxlen=200)   # 직전 실행 기록(막혔을 때 AI에게·증거 묶음에)
        self._rescuing = False
        self._in_foreground = False
        self.health = health               # 건강 기록(engine/health.py). 없으면 안 모음
        self._iter_paths: List[str] = []
        self.settings = {**DEFAULT_SETTINGS, **macro.get("settings", {})}
        self._call_stack = _call_stack + (self.name,)
        self._globals: Dict[str, Any] = {} if _globals is None else _globals   # '전역_' 변수(호출 사이 공유)
        self._heal = _heal                  # 헛돎 알아채기·스스로 고치기(engine/selfheal.py). 하위 매크로와 같이 씀
        self._cur_ctx = None
        if self._heal is None and (macro.get("unstick") or {}).get("on"):
            try:
                from .selfheal import SelfHeal
                self._heal = SelfHeal(self.name, macro["unstick"])
            except Exception:
                self._heal = None
        self._window: Optional[Window] = None
        self._activated = False
        self._background = bool((macro.get("window") or {}).get("background"))
        self._bg_input: Optional[Input] = None
        self._stop = threading.Event()
        self.value: Any = "ok"

    # ------------------------------------------------------------ 공개 API

    def run(self, stop: Optional[threading.Event] = None) -> Result:
        """매크로 전체 실행(반복 포함). 블로킹. 어느 스레드에서 불러도 됨."""
        try:
            return self._run(stop)
        finally:            # 어떤 식으로 끝나도(엔진 밖 오류·강제 중단 포함) 매크로가 켠 엑셀·워드·한글은 닫는다
            if len(self._call_stack) <= 1:
                self._unhide()              # 숨겨서 실행한 창은 원래대로(하위 매크로는 부른 쪽이)
            self._office_shutdown()
            self._memory_shutdown()         # 메모리로 붙은 프로그램에서도 뗀다

    def _run(self, stop: Optional[threading.Event]) -> Result:
        self._stop = stop or threading.Event()
        self.value = "ok"
        start = self.clock.now()
        rep = self.macro.get("repeat", {"times": 1})
        times = rep.get("times")
        fail_cfg = {**DEFAULT_ON_ITERATION_FAIL, **(self.macro.get("on_iteration_fail") or {})}
        # done = 성공한 회차 수. 실패한 회차는 횟수에 넣지 않고 다시 돈다(retry).
        done = failed = consecutive = 0
        self._emit("run_start", repeat=rep)

        def finish(status, error=None) -> Result:
            self._end_background()
            self._office_shutdown()
            res = Result(status, self.value, done, failed, error, self.clock.now() - start)
            self._emit("run_end", result=res.to_dict())
            return res

        try:
            while times is None or done < times:
                it = done + failed + 1
                ctx = self.new_context()
                self._emit("iteration_start", iteration=it)
                self._iter_paths = []
                it_t0 = self.clock.now()
                try:
                    self._exec_steps(self.macro["steps"], ctx, "steps")
                    done += 1
                    consecutive = 0
                    self._emit("iteration_end", iteration=it, status="ok")
                    self._health_iteration(True, it_t0, ctx)
                except StepFailed as e:
                    failed += 1
                    consecutive += 1
                    err = self._err(e)
                    self._emit("iteration_end", iteration=it, status="failed", error=err)
                    self._health_iteration(False, it_t0, ctx, err.get("reason", ""))
                    if fail_cfg["action"] == "stop":
                        return finish("failed", err)
                    mc = fail_cfg.get("max_consecutive")
                    if mc is not None and consecutive >= mc:
                        err = dict(err, reason=t("연속 {n}회 실패 — 마지막: {reason}", n=consecutive, reason=err['reason']))
                        return finish("failed", err)
                    self._sleep(float(fail_cfg.get("delay", 1.0)))
        except _Return as r:
            self.value = r.value
            return finish("ok")
        except _Stopped:
            return finish("stopped")
        except _MacroStop as m:
            return finish("failed", {"path": m.path, "type": "stop", "reason": m.reason})
        except Exception as e:  # 엔진 내부 오류 — 숨기지 않고 결과로 돌려준다
            self._emit("internal_error", error=repr(e), traceback=traceback.format_exc())
            return finish("failed", {"path": None, "type": None, "reason": t("엔진 오류: {error}", error=repr(e))})
        return finish("ok")

    def _health_iteration(self, ok: bool, t0: float, ctx: Context, reason: str = ""):
        """회차 하나를 건강 기록에(실패해도 매크로는 그대로)."""
        if self.health is None:
            return
        try:
            from .health import config
            cfg = config(self.macro)
            h = self.health.of(self.name, int(cfg["score_window"]))
            watch = {k: ctx.vars.get(k) for k in cfg.get("watch_vars") or [] if k in ctx.vars}
            rec = h.add_iteration(ok, self.clock.now() - t0, self.health.signature(self._iter_paths),
                                  {k: (v if isinstance(v, (int, float, str, bool)) or v is None else str(v)) for k, v in watch.items()},
                                  reason, getattr(self, "_last_fail_path", "") if not ok else "")
            signals = []
            if cfg.get("mode", "off") != "off":                     # 알아채기(알림만 모드부터)
                titles = []
                win = self._window
                if win is None and self.macro.get("window"):
                    try:
                        win = self._get_window()
                    except Exception:
                        win = None
                if win is not None and hasattr(win, "process_window_titles"):
                    try:
                        titles = win.process_window_titles()
                    except Exception:
                        titles = []
                for sig in h.check(cfg, h.note_windows(titles) if titles else None):
                    self._health_signal(sig)
                    signals.append(sig)
                rec["warnings"] = sorted({s["kind"] + (":" + str(s["detail"].get("image")) if s["kind"] == "score_low" else "")
                                          for s in signals})
                if self._tune_allowed(cfg) and len(h.iterations) % 3 == 0:
                    img, region = self._rescue_grab()
                    if img is not None and hasattr(self.health, "add_screen"):
                        self.health.add_screen(self.name, img, (region[0], region[1]))
                if self._tune_allowed(cfg):
                    self._tune_after_iteration(h, rec, cfg, signals)
            h.save()
        except Exception as e:
            self._emit("warning", message=t("건강 기록 오류: {error}", error=repr(e)))

    # ------------------------------------------------------------ 값 조정 시험 반영(스스로 고치기 3단계)
    def _tuner(self):
        """이 매크로의 시험 반영 상태. 매크로 폴더가 있는 실행(파일로 저장된 매크로)에서만."""
        if self.health is None:
            return None
        t_ = getattr(self, "_tuner_obj", False)
        if t_ is False:
            t_ = None
            root = getattr(self.library, "root", None) or getattr(self, "tuning_root", None)
            if root and (self.macro.get("self_heal") or {}).get("mode") in ("tune", "propose"):
                from .tuning import Tuner
                path_for = getattr(self.library, "path_for", None)
                mp = path_for(self.name) if path_for else None
                t_ = Tuner(root, self.name, mp if mp and os.path.exists(mp) else None)
            self._tuner_obj = t_
        return t_

    def _tune_allowed(self, cfg: dict) -> bool:
        """값 조정은 매크로 모드(tune/propose)와 이 컴퓨터의 '스스로 고치기 허용'이 둘 다 켜져 있을 때만."""
        if cfg.get("mode") not in ("tune", "propose") or self._tuner() is None:
            return False
        if getattr(self, "tuning_allowed", None) is not None:
            return bool(self.tuning_allowed)
        try:
            from .rescue import load_ai_config
            return load_ai_config(self.library.root).get("self_heal_allowed") is True
        except Exception:
            return False

    def _tune_cfg(self) -> dict:
        from .tuning import TUNE_DEFAULTS
        return {**TUNE_DEFAULTS, **{k: v for k, v in (self.macro.get("self_heal") or {}).items() if k in TUNE_DEFAULTS}}

    def _repair_log(self, kind: str, status: str, detail: dict, msg: str):
        root = getattr(self.health, "repairs_root", None)
        if root:
            try:
                from .repairs import append
                append(root, self.name, kind, status, detail, message=msg)
            except Exception:
                pass
        self._emit("health_repair", kind=kind, status=status, message=msg)

    def _maybe_recapture(self, image: str, m, target: dict, opts: dict):
        """그림 다시 따기: '찾은 이 순간·이 자리'에서만, 안전 검사를 모두 통과할 때만."""
        from .health import config
        cfg = config(self.macro)
        h = self.health.of(self.name)
        flags = h.__dict__.setdefault("flags", {})
        if not flags.get("want_recapture:" + image) or not self._tune_allowed(cfg):
            return
        tuner = self._tuner()
        tc = self._tune_cfg()
        import re as _re
        lineage = _re.sub(r"__(?:고침|fix)\d+", "", image)       # 같은 원본 그림 계열은 한 줄로(이어 붙은 이름·되풀이 방지)
        if not tuner.can_try("recapture:" + lineage, tc, time.time()) or target.get("multiscale"):
            return
        flags["want_recapture:" + image] = False
        tpl = getattr(self.vision, "template", None)
        if tpl is None or float(m.score) < float(opts["confidence"]):
            return
        th, tw = tpl(image).gray.shape[:2]
        cx, cy = m.pos
        region = (int(cx - tw // 2), int(cy - th // 2), int(tw), int(th))
        ar = (self.macro.get("ai_rescue") or {}).get("forbid_regions") or []
        try:
            ox, oy = self._origin() if self.macro.get("window") else (0, 0)
        except Exception:
            ox, oy = 0, 0
        for r in ar:                                     # 누르면 안 되는 구역과 겹치면 안 땀
            fx, fy = ox + r[0], oy + r[1]
            if not (region[0] + tw <= fx or fx + r[2] <= region[0] or region[1] + th <= fy or fy + r[3] <= region[1]):
                self._repair_log("recapture", "blocked", {"image": image}, t("그림 다시 따기 안 함: 금지 구역과 겹침"))
                return
        base, ext = os.path.splitext(lineage)
        new_rel = f"{base}__fix{time.strftime('%m%d%H%M%S')}{ext or '.png'}"      # 11-24: 영어 이름(예전 '__고침' 도 알아봄)
        new_abs = self.vision.resolve(new_rel) if hasattr(self.vision, "resolve") else new_rel
        try:
            self.vision.save_region(region, new_abs)
            self.vision.new_frame()
            chk = self.vision.match(new_rel, None, {"confidence": 0.9, "color_check": None})
            second = self.vision.runner_up(new_rel, None)[0] if hasattr(self.vision, "runner_up") else 0.0
        except Exception as e:
            self._repair_log("recapture", "blocked", {"image": image}, t("그림 다시 따기 실패: {error}", error=e))
            return
        if not chk.found or float(chk.score) < 0.95 or float(second) >= 0.9:
            try:
                os.remove(new_abs)
            except Exception:
                pass
            self._repair_log("recapture", "blocked", {"image": image, "self": round(float(chk.score), 3),
                                                       "second": round(float(second), 3)},
                             t("그림 다시 따기 안 함: 새 그림이 화면의 다른 곳과도 비슷함(점수 {s})", s=round(float(second), 2)))
            return
        tr_ = tuner.start("recapture", image, new_rel, image, h.iterations, tc,
                          t("인식 점수가 아슬아슬해서 찾은 자리에서 다시 땀"), time.time())
        if tr_ is not None:
            tuner.state.setdefault("cooldown", {})["recapture:" + lineage] = time.time()
            tuner.save()
        if tr_ is None:
            try:
                os.remove(new_abs)
            except Exception:
                pass
            return
        h.images.get(image, {})["scores"] = []           # 옛 낮은 점수가 평균에 남아 다시 신호가 나지 않게
        self._repair_log("recapture", "trial", {"target": image, "image": image, "new": new_rel, "old": image},
                         repair_sentence("recapture", "trial", image, image, new_rel))

    def _tune_after_iteration(self, h, rec: dict, cfg: dict, signals: list):
        tuner = self._tuner()
        tc = self._tune_cfg()
        # 1) 진행 중인 시험 평가
        res = tuner.on_iteration(rec, tc)
        if res:
            status, trial = res
            kname = {"recapture": t("그림 다시 따기"), "confidence": t("인식 기준 낮추기"),
                     "timeout": t("기다리는 시간 늘리기")}.get(trial["kind"], trial["kind"])
            tname = str(trial["target"]).replace("\\", "/").split("/")[-1] if trial["kind"] != "timeout" else str(trial["target"]).split("|")[0]
            if status == "applied":
                from .tuning import apply_to_macro, backup_and_save
                try:
                    new_macro = apply_to_macro(self.library.load(self.name), trial)
                    backup = backup_and_save(self.library, new_macro)
                    self.macro = apply_to_macro(self.macro, trial)
                except Exception as e:
                    backup = None
                    self._emit("warning", message=t("확정 반영 실패: {error}", error=e))
                self._repair_log(trial["kind"], "applied", {"target": trial["target"], "new": trial["new"],
                                                            "old": trial.get("old"), "why": trial.get("result_why"),
                                                            "backup": backup, "post": trial.get("post_metrics"),
                                                            "baseline": trial.get("baseline")},
                                 repair_sentence(trial["kind"], "applied", trial["target"], trial.get("old"),
                                                 trial["new"], trial.get("result_why")))
            else:
                self._repair_log(trial["kind"], "reverted", {"target": trial["target"], "new": trial["new"],
                                                             "old": trial.get("old"), "why": trial.get("result_why"),
                                                             "post": trial.get("post_metrics"),
                                                             "baseline": trial.get("baseline")},
                                 repair_sentence(trial["kind"], "reverted", trial["target"], trial.get("old"),
                                                 trial["new"], trial.get("result_why")))
            return
        if tuner.trial:
            return
        # 2) 새 시험 판단(한 번에 하나)
        for s in signals:
            if s["kind"] == "score_low":                 # 다음에 그 그림을 '찾은 순간'에 다시 따도록 표시
                h.__dict__.setdefault("flags", {})["want_recapture:" + s["detail"]["image"]] = True
        now = time.time()
        for img, irec in h.images.items():               # 아깝게 놓치는 그림 → 기준 낮추기(잘못 맞힘 검사 통과 시)
            nm = [x[1] for x in (irec.get("near_miss") or []) if isinstance(x, list)]
            if h.__dict__.get("flags", {}).get("want_recapture:" + img):
                continue                                     # 다시 따기가 가능한 상황이면 그쪽이 먼저
            last_conf = float(tuner.state.get("cooldown", {}).get("confidence:" + img, 0))
            if len(nm) >= int(tc["near_miss_count"]) and irec.get("scores") and not tuner.trial \
                    and now - last_conf >= float(tc["confidence_cooldown_s"]):
                old = float(irec.get("confidence", 0.8))
                orig = float(tuner.state.get("conf_original", {}).get(img, old))
                lowest = max(float(tc["confidence_floor"]), round(orig - float(tc["max_conf_drop"]), 2))
                new = round(max(lowest, min(nm) - 0.02), 2)
                if new >= old:
                    if old <= lowest:
                        irec["near_miss"] = []
                        tuner.state.setdefault("cooldown", {})["confidence:" + img] = now
                        tuner.save()
                        self._repair_log("confidence", "blocked", {"target": img, "image": img, "old": old},
                                         t("기준 낮추기 안 함: 이미 낮출 수 있는 한도({low})까지 내림", low=lowest))
                    continue
                ok, why = self._false_match_ok(img, new, old, irec.get("last_pos"))
                irec["near_miss"] = []
                if not ok:
                    tuner.state.setdefault("cooldown", {})["confidence:" + img] = now
                    tuner.save()
                    self._repair_log("confidence", "blocked", {"image": img, "new": new, "old": old},
                                     t("기준 낮추기 안 함: {why}", why=why))
                    continue
                if tuner.start("confidence", img, new, old, h.iterations, tc, why, now):
                    tuner.state.setdefault("conf_original", {}).setdefault(img, orig)
                    tuner.save()
                    self._repair_log("confidence", "trial", {"target": img, "image": img, "new": new, "old": old, "why": why},
                                     repair_sentence("confidence", "trial", img, old, new, why))
                    return
        # 3) 같은 스텝이 '시간 초과'로 자주 실패 → 기다리는 시간 늘리기
        from .tuning import reason_kind, step_key, _step_at
        last_done = max([x.get("finished", "") for x in tuner.state.get("history", [])] or [""])
        recent = [it for it in h.iterations[-int(tc["baseline_window"]):]
                  if it.get("at", "") > last_done]          # 마지막 고침이 끝난 뒤의 회차만(이미 고친 원인으로 또 고치지 않게)
        counts: Dict[str, int] = {}
        for it in recent:
            if not it.get("ok") and it.get("fail_path") and ("대기 초과" in it.get("reason", "") or "timed out" in it.get("reason", "") or "timeout" in it.get("reason", "").lower()):
                counts[it["fail_path"]] = counts.get(it["fail_path"], 0) + 1
        for p, n in counts.items():
            if n < int(tc["timeout_fail_count"]):
                continue
            sp = p.replace("[", "/").replace("]", "").replace(".", "/")
            step = _step_at(self.macro, sp)
            if not step or step.get("type") not in ("wait", "wait_window", "click", "move", "drag", "remember"):
                continue
            key = step_key(step, p)
            cur = step.get("timeout", self.settings.get("timeout"))
            if cur is None or not tuner.can_try("timeout:" + key, tc, now):
                continue
            cur = float(cur)
            new = round(min(float(tc["timeout_cap"]), cur * float(tc["timeout_factor"]), cur * float(tc["timeout_max_factor"])), 1)
            if new <= cur:
                continue
            if tuner.start("timeout", key, new, cur, h.iterations, tc, t("시간 초과 실패 {n}회", n=n), now):
                self._repair_log("timeout", "trial", {"target": key, "step": p, "new": new, "old": cur},
                                 repair_sentence("timeout", "trial", key, cur, new))
                return

    def _false_match_ok(self, image: str, new: float, old: float, last_pos) -> Tuple[bool, str]:
        from .tuning import false_match_check
        ring = getattr(self.health, "screens_of", None)
        screens = ring(self.name) if ring else []
        path = self.vision.resolve(image) if hasattr(self.vision, "resolve") else image
        return false_match_check(path, screens, new, old, tuple(last_pos) if last_pos else None)

    def _near_miss_now(self, step: dict) -> bool:
        """이번 회차에 그 스텝의 그림이 '아깝게 놓침'(기준 바로 아래)으로 기록됐고, 값 조정이 켜져 있는지."""
        tg = step.get("target") if isinstance(step.get("target"), dict) else None
        if not tg or "image" not in tg or self.health is None:
            return False
        from .health import config
        if not self._tune_allowed(config(self.macro)):
            return False
        h = self.health.of(self.name)
        nm = (h.images.get(tg["image"]) or {}).get("near_miss") or []
        return bool(nm) and isinstance(nm[-1], list) and nm[-1][0] == len(h.iterations)

    def _window_size_is(self, size) -> bool:
        """대상 창 안쪽 크기가 size 와 같은지(창이 없으면 거짓)."""
        try:
            if not self.macro.get("window"):
                return False
            fn = getattr(self._get_window(), "client_size", None)
            return bool(fn) and list(fn()) == [int(size[0]), int(size[1])]
        except Exception:
            return False

    def _maybe_propose_rule(self, rule: dict, path: str, step: dict):
        """자주 쓰이는 막힘 해결 규칙 → '막히던 스텝 앞에 그 해결 스텝을 넣자'는 제안(승인 대기함). 자동 반영은 안 함."""
        sh = self.macro.get("self_heal") or {}
        if sh.get("mode") != "propose" or not self._tune_allowed({"mode": "propose"}):
            return
        root = getattr(self.library, "root", None) or getattr(self, "tuning_root", None)
        if not root or int(rule.get("uses") or 0) < int(sh.get("propose_after_uses", 3)):
            return
        fix = copy.deepcopy(rule.get("steps") or [])
        tg = step.get("target") if isinstance(step.get("target"), dict) else None
        if tg and ("image" in tg or "color" in tg or "element" in tg):
            # 해결 동작은 '막히던 대상이 안 보일 때만' 하게 감싼다(안 막혔는데 엉뚱한 곳을 누르지 않게)
            cond = {"not": {"exists": copy.deepcopy(tg)}}
            if rule.get("size"):                         # 그 해결을 배운 창 크기에서만(고정 좌표라서)
                cond = {"all": [cond, {"window_size": list(rule["size"])}]}
            fix = [{"type": "if", "cond": cond, "then": fix}]
        try:
            from .proposals import add
            p = add(root, self.name, "insert_before", path, fix,
                    t("막힐 때마다 같은 해결이 {n}번 쓰였음(처음 원인: {reason})", n=rule.get("uses"),
                      reason=str(rule.get("reason") or "")[:80]), "rule", summary=str(rule.get("why") or "")[:160])
        except Exception:
            return
        if p:
            self._repair_log("proposal", "pending", {"id": p["id"], "path": path, "steps": p["steps"]},
                             t("제안: '{step}' 앞에 동작 {n}개를 넣기(승인 대기)", step=path, n=len(p["steps"])))

    def _health_signal(self, sig: dict):  # noqa: C901
        """알아챈 신호: 사건으로 알리고 고침 기록에 남긴다(고치기는 3·4단계)."""
        d = sig.get("detail") or {}
        k = sig["kind"]
        if k == "stall":
            msg = t("진전 없음: 같은 경로·같은 목표 값으로 {n}회 연속", n=d.get("repeats"))
        elif k == "score_low":
            msg = t("'{p}' 그림이 아슬아슬하게 인식됨(평균 점수 {avg}, 기준 {conf})", p=_pic(d.get("image")),
                    avg=d.get("avg"), conf=d.get("confidence"))
        elif k == "new_window":
            msg = t("처음 보는 창: {title}", title=d.get("title"))
        else:
            msg = t("느려짐: 한 바퀴 {sec}초(보통 {usual}초)가 {n}회 연속", sec=d.get("seconds"), usual=d.get("usual"),
                    n=d.get("times"))
        self._emit("health_warning", kind=k, message=msg, detail=d)
        self._emit("warning", message=msg)
        root = getattr(self.health, "repairs_root", None)
        if root:
            try:
                from .repairs import append
                append(root, self.name, k, "notified", d, message=msg)
            except Exception:
                pass

    def new_context(self) -> Context:
        return Context(vars=SharedVars(self._globals))

    def run_step(self, step: dict, ctx: Context, stop: Optional[threading.Event] = None) -> dict:
        """스텝 하나만 실행(MCP·편집기에서 시험용). ctx 의 변수는 호출 사이에 유지된다."""
        c = _Checker()
        c.step("step", step, 1)
        if c.errors:
            raise MacroError(c.errors)
        self._stop = stop or threading.Event()
        try:
            return self._run_one(step, ctx)
        finally:
            self._end_background()

    def _run_one(self, step: dict, ctx: Context) -> dict:
        try:
            self._exec(step, ctx, "step")
            return {"status": "ok", "vars": dict(ctx.vars)}
        except StepFailed as e:
            return {"status": "failed", "error": self._err(e), "vars": dict(ctx.vars)}
        except _Return as r:
            return {"status": "ok", "value": r.value, "vars": dict(ctx.vars)}
        except (_Break, _Continue):
            return {"status": "ok", "vars": dict(ctx.vars)}
        except _Stopped:
            return {"status": "stopped", "vars": dict(ctx.vars)}
        except _MacroStop as m:
            return {"status": "failed", "error": {"path": m.path, "type": "stop", "reason": m.reason},
                    "vars": dict(ctx.vars)}

    # ------------------------------------------------------------ 내부: 공통

    def _emit(self, event: str, **data):
        if (self._heal is not None and not getattr(self._heal, "busy", False)
                and (event == "input" or (event == "branch" and data.get("taken") == "then"))):
            try:
                self._heal_check(str(data.get("path") or ""), event == "input")
            except (_Flow, _Stopped):
                raise
            except Exception:
                pass
        if event != "poll":
            try:
                self._recent.append({"event": event, "macro": self.name,
                                     **{k: v for k, v in data.items() if k in ("path", "type", "status", "reason",
                                                                                "iteration", "branch", "message")}})
            except Exception:
                pass
        if not self.on_event:
            return
        try:
            self.on_event({"event": event, "t": round(self.clock.now(), 3), "macro": self.name,
                           "depth": len(self._call_stack) - 1, **data})
        except Exception:
            pass

    @staticmethod
    def _err(e: StepFailed) -> dict:
        return {"path": e.path, "type": e.step_type, "reason": e.reason}

    def _check_stop(self):
        if self._stop.is_set():
            raise _Stopped()

    def _sleep(self, seconds: float):
        if not self.clock.sleep(seconds, self._stop):
            raise _Stopped()

    def _step_settings(self, step: dict) -> dict:
        s = self.settings
        over = {k: step[k] for k in DEFAULT_SETTINGS if k in step}
        return {**s, **over} if over else s

    def _get_window(self) -> Window:
        if self._window is None:
            try:
                self._window = self.window_factory(self.macro.get("window"))
            except WindowNotFound as e:
                raise StepFailed(t("대상 창 문제: {error}", error=e))
            self._emit("window", target=self._window.describe())
            for w in self._window.warnings():
                self._emit("warning", message=w)
            if self._background:
                self._start_background(self._window)
            # 화면을 찾기 전에 대상 창을 맨 앞으로 (다른 창에 가려지면 캡처에 안 보임)
            self._prepare_input()
        return self._window

    def _origin(self) -> Pos:
        try:
            return self._get_window().origin()
        except WindowNotFound as e:
            raise StepFailed(t("대상 창을 찾을 수 없음: {error}", error=e))

    def _base(self, target: dict, ctx: Context) -> Pos:
        """대상 좌표의 기준점: anchor 가 있으면 그 변수 위치(화면 절대좌표), 없으면 창 원점."""
        name = target.get("anchor")
        if name is None:
            return self._origin()
        if name not in ctx.vars:
            raise StepFailed(t("기준 변수 '{name}'가 없음 (remember·for_each 로 먼저 정해야 함)", name=name))
        v = ctx.vars[name]
        self._origin()  # 창 확인(뒤에서 실행이면 캡처 연결)
        return (int(v[0]), int(v[1]))

    def _abs(self, xy) -> Pos:
        ox, oy = self._origin()
        return (int(round(xy[0])) + ox, int(round(xy[1])) + oy)

    # ------------------------------------------------------------ 내부: 스텝 실행

    def _exec_steps(self, steps: List[dict], ctx: Context, path: str):
        i = 0
        while i < len(steps):
            s = steps[i]
            if s.get("foreground") and self._background and not self._in_foreground:
                j = i                                   # 연달아 있는 '잠깐 앞에서' 스텝은 한 번에(메뉴 열기→항목)
                while j < len(steps) and steps[j].get("foreground"):
                    j += 1
                with self._foreground_block(path, i):
                    for k in range(i, j):
                        self._exec(steps[k], ctx, f"{path}[{k}]")
                i = j
                continue
            self._exec(s, ctx, f"{path}[{i}]")
            i += 1

    def _foreground_block(self, path: str, index: int):
        """뒤에서 실행 중 잠깐 앞에서: 지금 활성 창·커서 기억 → (사람이 쓰는 중이면 잠깐 대기) → 대상 창 앞으로 →
        진짜 입력으로 실행 → 실패해도 원래 활성 창·커서로 되돌림."""
        from contextlib import contextmanager

        @contextmanager
        def block():
            win = self._get_window()
            snap = win.focus_snapshot() if hasattr(win, "focus_snapshot") else None
            active = getattr(win, "user_active", None)
            if active is not None:                       # 사람이 마우스·키보드를 쓰는 중이면 멈출 때까지 최대 5초 기다림
                waited = 0.0
                while waited < 5.0 and active():
                    self._sleep(0.5)
                    waited += 0.75
                if waited:
                    self._emit("foreground_wait", seconds=round(waited, 1))
            t0 = self.clock.now()
            saved = self.input
            self._in_foreground = True
            self._emit("foreground_start", path=f"{path}[{index}]")
            shown = getattr(win, "show_for_now", None)
            if shown:
                shown()                                  # 숨겨서 실행 중이면 이 동안만 보이게(진짜 마우스를 씀)
            try:
                if win.activate() is False:
                    self._emit("warning", message=t("잠깐 앞에서: 대상 창을 맨 앞으로 가져오지 못함"))
                self._sleep(0.15)
                self.input = self._real_input
                yield
            finally:
                self.input = saved
                self._in_foreground = False
                if snap is not None:
                    try:
                        win.focus_restore(snap)
                    except Exception:
                        pass
                again = getattr(win, "hide_again", None)
                if again:
                    try:
                        again()
                    except Exception:
                        pass
                self._emit("foreground_end", path=f"{path}[{index}]", ms=round((self.clock.now() - t0) * 1000))
        return block()

    def _exec(self, step: dict, ctx: Context, path: str):
        self._check_stop()
        self._cur_ctx = ctx
        stype = step["type"]
        if stype == "comment":
            return
        if self.health is not None and len(self._iter_paths) < 2000:
            self._iter_paths.append(path)
        tuner = self._tuner() if self.health is not None else None
        if tuner is not None and tuner.trial and tuner.trial["kind"] == "timeout":
            from .tuning import step_key
            to = tuner.timeout_for(step_key(step, path), None)
            if to is not None:
                step = dict(step, timeout=to)
        on_fail = step.get("on_fail", "fail")
        retries = step.get("retries", 2) if on_fail == "retry" else 0
        settings = self._step_settings(step)
        handler = getattr(self, f"_do_{stype}")
        attempt = 0
        self._emit("step_start", path=path, type=stype)
        t0 = self.clock.now()
        while True:
            try:
                try:
                    handler(self._filled(step, ctx, path), ctx, path, settings)
                    self._guard_focus(path)
                except (_Flow, StepFailed):
                    raise
                except Exception as e:  # 백엔드 오류도 스텝 실패로 처리
                    raise StepFailed(t("오류: {error}", error=repr(e)))
                self._emit("step_end", path=path, type=stype, status="ok",
                           ms=round((self.clock.now() - t0) * 1000))
                return
            except StepFailed as e:
                if e.path is None:
                    e.path, e.step_type = path, stype
                if attempt < retries:
                    attempt += 1
                    self._emit("step_retry", path=path, type=stype, attempt=attempt, reason=e.reason)
                    continue
                if (on_fail == "fail" and stype in RESCUABLE and not getattr(e, "rescue_tried", False)
                        and not self._rescuing):
                    e.rescue_tried = True
                    if self._try_rescue(step, ctx, path, settings, handler, e):
                        self._emit("step_end", path=path, type=stype, status="ok", rescued=True,
                                   ms=round((self.clock.now() - t0) * 1000))
                        return
                ms = round((self.clock.now() - t0) * 1000)
                if on_fail == "skip":
                    self._emit("step_end", path=path, type=stype, status="skipped", reason=e.reason, ms=ms)
                    return
                self._emit("step_end", path=path, type=stype, status="failed", reason=e.reason,
                           failed_at=e.path, ms=ms)
                if not hasattr(self, "_last_fail_path") or e.path == path:
                    self._last_fail_path = e.path or path
                if isinstance(on_fail, dict):
                    raise _Return(on_fail["return"])
                raise

    # ------------------------------------------------------------ 내부: 대상·조건

    def _sample(self, target: dict, ctx: Context, s: dict) -> Tuple[Optional[Pos], float]:
        """한 프레임 확인. (위치 또는 None, 점수)"""
        if "image" in target:
            region = target.get("region")
            if region is not None:
                ox, oy = self._base(target, ctx)
                region = (int(region[0]) + ox, int(region[1]) + oy, int(region[2]), int(region[3]))
            else:
                self._origin()  # 창이 없으면 여기서 실패
            opts = {"confidence": target.get("confidence", s["confidence"]),
                    "multiscale": target.get("multiscale", False),
                    "color_check": target["color_check"] if "color_check" in target
                    else s["color_check"]}
            img0 = target["image"]
            tuner = self._tuner()
            if tuner is not None:
                opts["confidence"] = tuner.confidence_for(img0, opts["confidence"])
            imgs = (tuner.images_for(img0) if tuner is not None else [img0]) + list(target.get("fallback_images") or [])
            m: Match = self.vision.match(imgs[0], region, opts)
            used = imgs[0]
            margin = float((self.macro.get("self_heal") or {}).get("score_margin", 0.05))
            for alt in imgs[1:]:                         # 예비 그림은 앞 그림을 못 찾았거나 아슬아슬할 때만
                if m.found and float(m.score) >= float(opts["confidence"]) + margin:
                    break
                try:
                    m2 = self.vision.match(alt, region, opts)
                except Exception:
                    continue
                if (m2.found and (not m.found or m2.score > m.score)) or (not m.found and m2.score > m.score):
                    m, used = m2, alt
            if self.health is not None:
                try:
                    self.health.of(self.name).note_image(img0, float(m.score), bool(m.found),
                                                         float(opts["confidence"]), m.pos)
                    if m.found and used == img0:
                        self._maybe_recapture(img0, m, target, opts)
                except Exception:
                    pass
            return (tuple(m.pos) if m.found else None), float(m.score)
        if "vivid" in target:
            r = target["region"]
            ox, oy = self._base(target, ctx)
            region = (int(r[0]) + ox, int(r[1]) + oy, int(r[2]), int(r[3]))
            need = int(target.get("min_pixels", 50))
            count, center = self.vision.count_vivid(region, int(target.get("min_saturation", 110)),
                                                    int(target.get("min_value", 110)), target.get("hues"))
            return (tuple(center) if count >= need and center else None), min(1.0, count / float(need))
        if "color" in target and "region" in target:
            # 영역 안에 그 색(허용 오차 안) 픽셀이 min_pixels 개 이상 있으면 '있음', 위치는 그 픽셀들의 중심
            r = target["region"]
            ox, oy = self._base(target, ctx)
            region = (int(r[0]) + ox, int(r[1]) + oy, int(r[2]), int(r[3]))
            if "blob_depth" in target:
                # 그 색 덩어리 중 가장 두꺼운 곳이 blob_depth px 이상이면 '있음', 위치는 그 안쪽 점
                need_d = float(target["blob_depth"])
                depth, center = self.vision.color_blob(region, tuple(target["color"]),
                                                       int(target.get("tolerance", 0)))
                ok = depth >= need_d and center is not None
                return (tuple(center) if ok else None), min(1.0, depth / need_d)
            need = int(target.get("min_pixels", 10))
            count, center = self.vision.count_color(region, tuple(target["color"]),
                                                    int(target.get("tolerance", 0)))
            score = min(1.0, count / float(need))
            return (tuple(center) if count >= need and center else None), score
        if "color" in target:
            bx, by = self._base(target, ctx)
            at = (int(round(target["at"][0])) + bx, int(round(target["at"][1])) + by)
            px = self.vision.pixel(*at)
            tol = target.get("tolerance", 0)
            ok = all(abs(int(a) - int(b)) <= tol for a, b in zip(px, target["color"]))
            return (at if ok else None), (1.0 if ok else 0.0)
        if "element" in target:
            win = self._get_window()
            try:
                r = win.find_element(target["element"])
            except Exception as e:
                raise StepFailed(t("창 요소 찾기 실패: {error}", error=e))
            if r is None:
                return None, 0.0
            return (int(r[0] + r[2] // 2), int(r[1] + r[3] // 2)), 1.0
        if "point" in target:
            bx, by = self._base(target, ctx)
            return (int(round(target["point"][0])) + bx, int(round(target["point"][1])) + by), 1.0
        name = target["var"]
        if name not in ctx.vars:
            raise StepFailed(t("변수 '{name}'가 없음 (remember 나 이미지 클릭 전에 썼는지 확인)", name=name))
        v = ctx.vars[name]
        return (int(v[0]), int(v[1])), 1.0

    def _await(self, cond: dict, ctx: Context, s: dict, timeout: Optional[float],
               path: str, stable: bool = False) -> Tuple[bool, _Probe]:
        """조건이 참이 될 때까지 폴링. timeout=None 이면 무한."""
        probe = _Probe(self, cond, ctx, s, stable)
        poll = s["poll_ms"] / 1000.0
        grace = poll * s["stable_frames"] + probe.max_for()
        start = self.clock.now()
        last_r, last_emit = object(), -1e9
        while True:
            self._check_stop()
            self.vision.new_frame()
            now = self.clock.now()
            r = probe.poll(now)
            self._guard_focus(path)
            if r is not last_r or now - last_emit >= 1.0:
                self._emit("poll", path=path, result=r, detail=probe.detail())
                last_r, last_emit = r, now
            if r is True:
                return True, probe
            if timeout is not None:
                el = now - start
                if el >= timeout and (r is False or el >= timeout + grace):
                    return False, probe
            self._sleep(poll)

    def _locate(self, target: dict, ctx: Context, s: dict, path: str) -> Pos:
        """대상 위치를 구한다. 이미지·색상은 나타나서 안정될 때까지 기다린 뒤 settle."""
        if "point" in target or "var" in target:
            pos, _ = self._sample(target, ctx, s)
        else:
            timeout = s["timeout"]
            ok, probe = self._await({"exists": target}, ctx, s, timeout, path, stable=True)
            if not ok:
                raise StepFailed(t("{timeout}초 안에 못 찾음 — {detail}", timeout=timeout, detail=probe.detail()))
            pos = probe.found_pos
            self._sleep(s["settle_ms"] / 1000.0)
        off = target.get("offset")
        if off:
            pos = (pos[0] + int(off[0]), pos[1] + int(off[1]))
        return pos

    # ------------------------------------------------------------ 내부: 입력

    def _start_background(self, win: Window):
        """'뒤에서 실행': 창을 앞으로 안 가져오고, 그 창만 캡처하고, 진짜 마우스 대신 창에 직접 입력."""
        inp = win.background_input()
        src = win.capture_source()
        if inp is None or src is None:
            raise StepFailed(t("이 환경은 '뒤에서 실행'(window.background)을 지원하지 않음"))
        self.vision.bind_window(src)
        self.input = self._bg_input = inp
        if (self.macro.get("window") or {}).get("hidden"):
            hide = getattr(win, "hide", None)
            if hide is None:
                raise StepFailed(t("이 환경은 '숨겨서 실행'(window.hidden)을 지원하지 않음"))
            try:
                hide()
            except Exception as e:
                raise StepFailed(t("숨겨서 실행을 시작하지 못함: {error}", error=e))
            self._emit("hidden", target=win.describe())
        uf = getattr(win, "user_foreground", None)
        try:
            self._user_fg = uf() if uf else None          # 사람이 쓰던 앞 창(대상 프로그램이 가져가면 되돌림)
        except Exception:
            self._user_fg = None
        self._emit("background", target=win.describe())

    def _guard_focus(self, path: str = ""):
        """'뒤에서 실행' 중 대상 프로그램(뜬 대화상자 등)이 사람의 앞 창을 가져갔으면 되돌림(11-23)."""
        if self._bg_input is None or getattr(self, "_in_foreground", False):
            return                                       # '잠깐 앞에서' 스텝은 일부러 앞으로 가져온 것
        win = self._window
        try:
            now = win.user_foreground() if hasattr(win, "user_foreground") else None
            if now:
                self._user_fg = now                      # 사람이 다른 창으로 옮기면 그 창을 기억(오래 도는 매크로)
            uf = getattr(self, "_user_fg", None)
            fn = getattr(win, "keep_user_foreground", None)
            if uf and fn and fn(uf):
                self._emit("focus_guard", path=path)
        except Exception:
            pass

    def _end_background(self, force: bool = False):
        """최상위 실행(또는 스텝 시험)이 끝날 때만: 뒤에서 실행을 원래대로, 캡처도 화면으로.
        하위 매크로는 부른 쪽이 정리한다(부른 쪽이 '뒤에서 실행'이 아니면 _do_call 이 force 로 정리)."""
        if self._bg_input is None or (len(self._call_stack) > 1 and not force):
            return
        rel = getattr(self._bg_input, "release", None)
        if rel:
            try:
                rel()
            except Exception:
                pass
        self._unhide()
        self.vision.bind_window(None)
        # 같은 Runner 로 다시 돌리면(스텝 시험 등) 창을 다시 잡으면서 캡처·입력을 다시 연결
        self._bg_input = None
        self._window = None
        self._activated = False

    def _unhide(self):
        un = getattr(self._window, "unhide", None)
        if un:
            try:
                un()
            except Exception:
                pass

    def _prepare_input(self):
        if self._activated:
            return
        self._activated = True
        cfg = self.macro.get("window")
        if self._background:
            self._get_window()
            return
        if cfg and cfg.get("activate", True):
            win = self._get_window()
            if win.activate() is False:
                self._emit("warning", message=t("대상 창을 맨 앞으로 가져오지 못함: {window} — "
                                              "다른 창에 가려져 있으면 화면 인식·클릭이 실패함", window=win.describe()))
            else:
                self._emit("window_activated", target=win.describe())
            self._sleep(0.2)          # 창이 다시 그려질 시간

    def _move(self, pos: Pos):
        self._prepare_input()
        self.input.move(*pos)

    def _click_at(self, pos: Pos, button: str, count: int, s: dict, path: str):
        self._move(pos)
        self._sleep(s["move_settle_ms"] / 1000.0)
        for k in range(count):
            self.input.down(button)
            self._sleep(s["click_hold_ms"] / 1000.0)
            self.input.up(button)
            if k < count - 1:
                self._sleep(s["double_click_gap_ms"] / 1000.0)
        self._emit("input", path=path, kind="click", x=pos[0], y=pos[1], button=button, count=count)
        self._sleep(s["after_click_ms"] / 1000.0)

    # ------------------------------------------------------------ 스텝 처리기

    def _do_click(self, step, ctx, path, s):
        verify = step.get("verify")
        tries = 1 + (verify.get("retries", 2) if verify else 0)
        probe = None
        for attempt in range(tries):
            pos = self._locate(step["target"], ctx, s, path)
            tg = step["target"]
            inv = getattr(self._get_window(), "invoke_element", None) if isinstance(tg, dict) and "element" in tg else None
            cnt = int(step.get("count", 1))
            if (inv is not None and self._background and step.get("button", "left") == "left"
                    and cnt in (1, 2) and inv(tg["element"], cnt == 2)):
                # '뒤에서 실행'에서 창 요소는 마우스 메시지 대신 요소 누르기(스토어 앱도 확실, 11-23)
                self._emit("input", path=path, kind="invoke", x=pos[0], y=pos[1])
            else:
                mini = getattr(self._get_window(), "is_minimized", None)
                if self._background and mini is not None and mini():
                    raise StepFailed(t("최소화된 창에서는 마우스로 누를 수 없음 — 이 대상은 요소 누르기를 지원하지 않음"))
                self._click_at(pos, step.get("button", "left"), step.get("count", 1), s, path)
            if not verify:
                return
            ok, probe = self._await(verify["cond"], ctx, s, verify.get("timeout", 2.0), path)
            if ok:
                return
            self._emit("verify_failed", path=path, attempt=attempt + 1, detail=probe.detail())
        raise StepFailed(t("클릭 후 확인 {tries}회 실패 — {detail}", tries=tries, detail=probe.detail()))

    def _do_move(self, step, ctx, path, s):
        pos = self._locate(step["target"], ctx, s, path)
        self._move(pos)
        self._emit("input", path=path, kind="move", x=pos[0], y=pos[1])

    def _do_menu(self, step, ctx, path, s):
        """창의 표준 메뉴 항목을 이름으로 고른다(예: '서식 > 글꼴'). 창을 앞으로 안 가져오고 명령만 보냄."""
        win = self._get_window()
        fn = getattr(win, "menu_command", None)
        if fn is None:
            raise StepFailed(t("이 환경은 메뉴 스텝을 지원하지 않음"))
        try:
            cid = fn(step["path"])
        except ValueError as e:
            raise StepFailed(str(e))
        self._emit("input", path=path, kind="menu", menu=step["path"], command=cid)

    def _do_scroll(self, step, ctx, path, s):
        """휠 굴리기: 대상이 있으면 그 자리로 옮긴 뒤 amount 칸(+ 위, - 아래)."""
        if step.get("target"):
            pos = self._locate(step["target"], ctx, s, path)
            self._move(pos)
            self._sleep(s["move_settle_ms"] / 1000.0)
        else:
            self._prepare_input()
        amount = int(step.get("amount", -3))
        self.input.scroll(amount, bool(step.get("horizontal", False)))
        self._emit("input", path=path, kind="scroll", amount=amount)

    def _do_drag(self, step, ctx, path, s):
        p1 = self._locate(step["from"], ctx, s, path)
        p2 = self._locate(step["to"], ctx, s, path)
        button = step.get("button", "left")
        dur = step.get("duration_ms", 300) / 1000.0
        self._move(p1)
        self._sleep(s["move_settle_ms"] / 1000.0)
        self.input.down(button)
        self._sleep(s["click_hold_ms"] / 1000.0)
        n = max(1, int(dur / 0.016))
        for i in range(1, n + 1):
            x = round(p1[0] + (p2[0] - p1[0]) * i / n)
            y = round(p1[1] + (p2[1] - p1[1]) * i / n)
            self.input.move(x, y)
            self._sleep(dur / n)
        self._sleep(s["move_settle_ms"] / 1000.0)
        self.input.up(button)
        self._emit("input", path=path, kind="drag", x=p1[0], y=p1[1], x2=p2[0], y2=p2[1])
        self._sleep(s["after_click_ms"] / 1000.0)

    def _do_mouse_down(self, step, ctx, path, s):
        if "target" in step:
            self._move(self._locate(step["target"], ctx, s, path))
            self._sleep(s["move_settle_ms"] / 1000.0)
        self._prepare_input()
        self.input.down(step.get("button", "left"))

    def _do_mouse_up(self, step, ctx, path, s):
        if "target" in step:
            self._move(self._locate(step["target"], ctx, s, path))
            self._sleep(s["move_settle_ms"] / 1000.0)
        self._prepare_input()
        self.input.up(step.get("button", "left"))

    def _do_key(self, step, ctx, path, s):
        keys = [k.strip().lower() for k in step["keys"].split("+") if k.strip()] or [step["keys"]]
        self._prepare_input()
        for n in range(step.get("count", 1)):
            for k in keys:
                self.input.key_down(k)
            self._sleep(s["key_hold_ms"] / 1000.0)
            for k in reversed(keys):
                self.input.key_up(k)
            self._sleep(s["key_hold_ms"] / 1000.0)
        self._emit("input", path=path, kind="key", keys=keys, count=step.get("count", 1))

    def _do_type_text(self, step, ctx, path, s):
        tg = step.get("target")
        if tg:
            # 입력 칸을 정해 주면: 그 칸에 키보드 없이 값으로 넣음(뒤에서 뜬 대화상자도 됨). 안 되면 그 칸을 누르고 키로
            pos = self._locate(tg, ctx, s, path)
            fn = getattr(self._get_window(), "set_element_value", None)
            try:
                done = bool(fn and fn(tg["element"], step["text"]))
            except Exception as e:
                raise StepFailed(t("글자 넣기 실패: {error}", error=e))
            if done:
                self._emit("input", path=path, kind="set_value", length=len(step["text"]))
                return
            self._click_at(pos, "left", 1, s, path)
        self._prepare_input()
        self.input.type_text(step["text"])
        self._emit("input", path=path, kind="type_text", length=len(step["text"]))

    def _do_wait(self, step, ctx, path, s):
        timeout = s["timeout"]
        ok, probe = self._await(step["until"], ctx, s, timeout, path)
        if not ok:
            raise StepFailed(t("{timeout}초 대기 초과 — {detail}", timeout=timeout, detail=probe.detail()))

    def _do_delay(self, step, ctx, path, s):
        self._sleep(float(step["seconds"]))

    def _do_remember(self, step, ctx, path, s):
        what = step.get("what", "mouse")
        pos = self.input.position() if what == "mouse" else self._locate(what, ctx, s, path)
        ctx.vars[step["var"]] = (int(pos[0]), int(pos[1]))

    def _do_if(self, step, ctx, path, s):
        ok, probe = self._await(step["cond"], ctx, s, float(step.get("within", 0)), path)
        branch = "then" if ok else "else"
        self._emit("branch", path=path, taken=branch, detail=probe.detail())
        self._exec_steps(step.get(branch, []), ctx, f"{path}.{branch}")

    def _do_repeat(self, step, ctx, path, s):
        mode = next(k for k in ("times", "until", "while", "forever") if k in step)
        max_times = step.get("max_times")
        max_seconds = step.get("max_seconds")
        start = self.clock.now()
        n = 0
        while True:
            self._check_stop()
            if mode == "times" and n >= step["times"]:
                return
            if mode == "while":
                ok, _ = self._await(step["while"], ctx, s, 0, path)
                if not ok:
                    return
            if max_times is not None and n >= max_times:
                raise StepFailed(t("최대 반복 {n}회를 넘김", n=max_times))
            if max_seconds is not None and self.clock.now() - start >= max_seconds:
                raise StepFailed(t("최대 반복 시간 {n}초를 넘김", n=max_seconds))
            n += 1
            self._emit("repeat_iteration", path=path, n=n)
            t0 = self.clock.now()
            try:
                self._exec_steps(step["steps"], ctx, f"{path}.steps")
            except _Break:
                return
            except _Continue:
                pass
            if mode == "until":
                ok, _ = self._await(step["until"], ctx, s, 0, path)
                if ok:
                    return
            if self.clock.now() - t0 < 0.001:   # 빈 반복이 CPU 를 다 쓰지 않게
                self._sleep(0.01)

    def _do_for_each(self, step, ctx, path, s):
        """화면에서 그 그림을 모두 찾아(위→아래 줄, 줄 안에서는 왼→오; reverse 면 거꾸로) 하나씩 var 에 넣고 steps 실행.
        break 는 끝내기, continue 는 다음 것으로."""
        tgt = step["target"]
        region = tgt.get("region")
        if region is not None:
            ox, oy = self._base(tgt, ctx)
            region = (int(region[0]) + ox, int(region[1]) + oy, int(region[2]), int(region[3]))
        else:
            self._origin()
        opts = {"confidence": tgt.get("confidence", s["confidence"]),
                "multiscale": tgt.get("multiscale", False),
                "color_check": tgt["color_check"] if "color_check" in tgt else s["color_check"]}
        self.vision.new_frame()
        found = self.vision.match_all(tgt["image"], region, opts)
        tol = int(step.get("row_tolerance", 20))
        pts = sorted(found, key=lambda p: (p[1], p[0]))
        rows: List[List[Pos]] = []
        for p in pts:
            if rows and p[1] - rows[-1][0][1] <= tol:
                rows[-1].append(p)
            else:
                rows.append([p])
        ordered = [q for row in rows for q in sorted(row, key=lambda p: p[0])]
        if step.get("reverse"):          # 아래→위, 오→왼(목록 맨 끝부터)
            ordered.reverse()
        off = tgt.get("offset")
        if off:
            ordered = [(p[0] + int(off[0]), p[1] + int(off[1])) for p in ordered]
        if step.get("max"):
            ordered = ordered[:int(step["max"])]
        self._emit("for_each", path=path, count=len(ordered))
        for i, p in enumerate(ordered):
            self._check_stop()
            ctx.vars[step["var"]] = (int(p[0]), int(p[1]))
            try:
                self._exec_steps(step["steps"], ctx, f"{path}.steps")
            except _Break:
                return
            except _Continue:
                continue

    def _each_items(self, step, ctx) -> list:
        """'목록마다'가 돌 것들. list / range / rows(엑셀 표) / files(폴더 파일) / lines(글 줄) 중 하나."""
        import os
        from .textops import fill, lookup
        if "list" in step:
            src = step["list"]
            if isinstance(src, str):
                missing = object()
                v = lookup(ctx.vars, src, missing)
                if v is missing:
                    raise StepFailed(t("목록 변수 '{name}' 가 없음", name=src))
                src = v
            if isinstance(src, dict):
                src = list(src.items())
            if not isinstance(src, (list, tuple)):
                src = [src]
            return list(src)
        if "range" in step:
            r = step["range"]
            a = int(self._num_arg(r.get("from", 1), ctx))
            b = int(self._num_arg(r.get("to", 1), ctx))
            st = int(r.get("step", 1)) or 1
            return list(range(a, b + (1 if st > 0 else -1), st))
        if "lines" in step:
            text = fill(step["lines"], ctx.vars)[0] if "{" in str(step["lines"]) else lookup(ctx.vars, step["lines"], "")
            lines = [ln.rstrip("\r") for ln in str(text).split("\n")]
            return [ln for ln in lines if ln.strip()] if step.get("skip_empty", True) else lines
        if "files" in step:
            from .fileops import FileOpError, list_files
            fsp = step["files"]
            folder = self._abs_path(fill(fsp.get("path", ""), ctx.vars)[0])
            try:
                return list_files(folder, fsp.get("pattern", "*"), bool(fsp.get("sub")), fsp.get("kind", "files"),
                                  fsp.get("sort", "name"))
            except FileOpError as e:
                raise StepFailed(str(e))
        if "rows" in step:
            return self._excel_rows(step["rows"], ctx)
        return []

    def _num_arg(self, v, ctx):
        from .textops import TextOpError, calc
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        try:
            return calc(str(v), ctx.vars)
        except TextOpError as e:
            raise StepFailed(str(e))

    def _excel_rows(self, r: dict, ctx) -> list:
        """열려 있는(또는 path 로 여는) 엑셀 시트의 줄들 → 한 줄마다 {제목: 값, 'A': 값, ..., '행': 번호}."""
        import re as _re
        from .office import OfficeError, fill_vars
        from .textops import fill
        sess = self._office()
        sheet = fill(r.get("sheet", ""), ctx.vars)[0] or None
        header = int(r.get("header", 1))
        first = int(self._num_arg(r.get("from", header + 1 if header else 1), ctx))
        try:
            if r.get("path"):
                sess.run("excel", "open", {"path": self._abs_path(fill(r["path"], ctx.vars)[0])})
            key_col = str(r.get("key_col") or ("*" if (r.get("group") or r.get("group_by")) else "A"))
            last = int(self._num_arg(r["to"], ctx)) if r.get("to") not in (None, "") else \
                int(sess.run("excel", "last_row", {"sheet": sheet, "cell": key_col}) or 0)
            cols = r.get("cols") or ""
            if cols:
                c1, c2 = (cols.split(":") + [cols])[:2]
            else:
                c1 = "A"
                probe = sess.run("excel", "read", {"sheet": sheet, "cell": f"A{header or first}:AZ{header or first}"})
                row0 = probe[0] if probe and isinstance(probe[0], list) else (probe or [])
                n = len(row0)
                while n > 1 and row0[n - 1] in (None, ""):
                    n -= 1
                c2 = _col_name(max(1, n))
            names = []
            if header:
                h = sess.run("excel", "read", {"sheet": sheet, "cell": f"{c1}{header}:{c2}{header}"})
                names = [("" if v is None else str(v).strip()) for v in (h[0] if h and isinstance(h[0], list) else h or [])]
            if last < first:
                return []
            data = sess.run("excel", "read", {"sheet": sheet, "cell": f"{c1}{first}:{c2}{last}"})
        except OfficeError as e:
            raise StepFailed(t("엑셀 표 읽기 실패: {error}", error=e))
        if data and not isinstance(data[0], list):
            data = [data] if (last == first) else [[v] for v in data]
        start_idx = _col_index(c1)
        lines = []
        for i, row in enumerate(data or []):
            item = row_item(first + i)
            for j, v in enumerate(row):
                item[_col_name(start_idx + j)] = v
                if j < len(names) and names[j]:
                    item[names[j]] = v
            lines.append((item, all(v in (None, "") for v in row)))
        n = int(r.get("group") or 0)
        by = r.get("group_by")
        if n > 1 or by:
            return _group_lines([it for it, empty in lines if not empty] if by else [it for it, _ in lines], n, by)
        return [it for it, empty in lines if not (r.get("skip_empty", True) and empty)]

    def _do_each(self, step, ctx, path, s):
        """목록마다: 목록(변수)·숫자 범위·엑셀 표의 줄·폴더 파일·글 줄을 하나씩 var 에 넣고 steps 실행.
        index_var 가 있으면 몇 번째인지(1부터). break 는 끝내기, continue 는 다음 것으로."""
        items = self._each_items(step, ctx)
        if step.get("reverse"):
            items = list(reversed(items))
        if step.get("max"):
            items = items[:int(step["max"])]
        self._emit("for_each", path=path, count=len(items))
        for i, item in enumerate(items, 1):
            self._check_stop()
            ctx.vars[step["var"]] = item
            if step.get("index_var"):
                ctx.vars[step["index_var"]] = i
            try:
                self._exec_steps(step["steps"], ctx, f"{path}.steps")
            except _Break:
                return
            except _Continue:
                continue

    def _do_group(self, step, ctx, path, s):
        self._exec_steps(step["steps"], ctx, f"{path}.steps")

    def _do_break(self, step, ctx, path, s):
        raise _Break()

    def _do_continue(self, step, ctx, path, s):
        raise _Continue()

    def _do_call(self, step, ctx, path, s):
        name = step["macro"]
        if self._heal is not None and self._heal.resting(name):
            # 헛돌던 일이라 잠깐 쉬는 중(스스로 고치기의 '쉬기')
            self._emit("warning", path=path, message=t("'{name}' 은(는) 헛돌아서 잠깐 쉬는 중 — 건너뜀", name=name))
            if step.get("result_var"):
                ctx.vars[step["result_var"]] = t("쉬는 중")
            return
        if name in self._call_stack:
            raise StepFailed(t("순환 호출: {chain}", chain=' → '.join(self._call_stack + (name,))))
        if self.library is None:
            raise StepFailed(t("매크로 저장소가 연결되지 않음"))
        try:
            sub_macro = self.library.load(name)
        except MacroNotFound:
            raise StepFailed(t("매크로 '{name}'가 없음", name=name))
        except MacroError as e:
            raise StepFailed(t("매크로 '{name}' 형식 오류: {errors}", name=name, errors=e.errors[:3]))
        sub = Runner(sub_macro, vision=self.vision, input=self.input, clock=self.clock,
                     library=self.library, window_factory=self.window_factory,
                     on_event=self.on_event, launcher=self.launcher, snapshot_dir=self.snapshot_dir,
                     web=self.web, office=self._office(), rescuer=self.rescuer, health=self.health,
                     clipboard=self.clipboard, asker=self.asker, notifier=self.notifier, _call_stack=self._call_stack, _globals=self._globals,
                     _heal=self._heal)
        res = sub.run(self._stop)
        if sub._bg_input is not None and self._bg_input is None:
            if self._background:          # 나도 '뒤에서 실행'이면 끝날 때 내가 정리
                self._bg_input = sub._bg_input
            else:
                sub._end_background(force=True)
        if res.status == "stopped":
            raise _Stopped()
        if res.status == "failed":
            e = res.error or {}
            raise StepFailed(t("'{name}' 실패 ({path}): {reason}", name=name, path=e.get('path'), reason=e.get('reason')))
        if step.get("result_var"):
            ctx.vars[step["result_var"]] = res.value

    def _filled(self, step: dict, ctx, path: str) -> dict:
        keys = FILL_KEYS.get(step.get("type"))
        if not keys:
            return step
        from .textops import fill
        out = None
        for k in keys:
            v = step.get(k)
            if isinstance(v, str) and "{" in v:
                nv, missing = fill(v, ctx.vars)
                for name in missing:
                    self._emit("warning", path=path, message=t("변수 '{name}' 가 없어 글자 그대로 둠", name=name))
                if nv != v:
                    out = out if out is not None else dict(step)
                    out[k] = nv
        return out if out is not None else step

    def _wall_now(self):
        import datetime as _dt
        return _dt.datetime.now()

    def _do_text(self, step, ctx, path, s):
        """글자 만들기: 글자(안의 {변수} 채움)를 가공해 변수에 넣는다."""
        from .textops import TextOpError, fill, text_op
        text, missing = fill(step.get("text", ""), ctx.vars)
        if missing and (step.get("action") or "set") != "join":
            raise StepFailed(t("변수 '{name}' 가 없음", name=missing[0]))
        try:
            value = text_op(step.get("action") or "set", text if isinstance(text, str) else str(text), step, ctx.vars)
        except TextOpError as e:
            raise StepFailed(str(e))
        ctx.vars[step["var"]] = value
        self._emit("set", path=path, var=step["var"], value=value)

    def _do_date(self, step, ctx, path, s):
        """날짜: 지금(또는 from) + 더하기 → 글자(format), 또는 두 날짜 사이(diff)."""
        from .textops import TextOpError, date_op
        try:
            value = date_op(step, ctx.vars, self._wall_now())
        except TextOpError as e:
            raise StepFailed(str(e))
        ctx.vars[step["var"]] = value
        self._emit("set", path=path, var=step["var"], value=value)

    def _clip(self):
        if self.clipboard is None:
            from .clipboard import RealClipboard
            self.clipboard = RealClipboard()
        return self.clipboard

    def _do_clipboard(self, step, ctx, path, s):
        """클립보드: read(글→변수) · write(글 넣기) · clear · copy(Ctrl+C 누르고 새 글이 올 때까지 기다려 변수에)
        · files(복사한 파일 경로 목록→변수) · save_image(복사한 그림→PNG 파일)."""
        import os
        cb = self._clip()
        a = step.get("action", "read")
        var = step.get("var")
        try:
            if a == "write":
                cb.set_text(str(step.get("text", "")))
                self._emit("clipboard", path=path, action=a, length=len(str(step.get("text", ""))))
                return
            if a == "clear":
                cb.clear()
                return
            if a == "copy":
                cb.clear()
                self._prepare_input()

                def press_copy():
                    self.input.key_down("ctrl")
                    self.input.key_down("c")
                    self._sleep(s["key_hold_ms"] / 1000.0)
                    self.input.key_up("c")
                    self.input.key_up("ctrl")
                    hook = getattr(cb, "on_copy", None)
                    if hook:
                        hook()
                press_copy()
                # 11-19 실환경: 막 띄운 프로그램은 첫 Ctrl+C 가 늦거나 안 먹을 때가 있음 → 넉넉히 기다리고, 절반 지나면 한 번 더 누름
                limit = float(step.get("timeout", 4))
                t0 = self.clock.now()
                text = cb.get_text()
                again = False
                while text is None and self.clock.now() - t0 < limit:
                    self._sleep(0.05)
                    text = cb.get_text()
                    if text is None and not again and self.clock.now() - t0 >= limit / 2:
                        again = True
                        press_copy()
                if text is None:
                    raise StepFailed(t("복사한 글이 {sec:g}초 안에 안 들어옴(고른 글이 없거나 복사가 안 되는 곳)", sec=limit))
                ctx.vars[var] = text
            elif a == "read":
                text = cb.get_text()
                if text is None:
                    raise StepFailed(t("클립보드에 글이 없음"))
                ctx.vars[var] = text
            elif a == "files":
                files = cb.get_files()
                if not files:
                    raise StepFailed(t("클립보드에 복사한 파일이 없음"))
                ctx.vars[var] = files
            elif a == "save_image":
                fp = os.path.abspath(str(step.get("path", "")))
                if not cb.save_image(fp):
                    raise StepFailed(t("클립보드에 그림이 없음"))
                if var:
                    ctx.vars[var] = fp
                self._emit("clipboard", path=path, action=a, file=fp)
                return
        except StepFailed:
            raise
        except OSError as e:
            raise StepFailed(t("클립보드를 쓸 수 없음: {error}", error=e))
        self._emit("set", path=path, var=var, value=ctx.vars.get(var))

    def _abs_path(self, p: str) -> str:
        """파일 단계의 경로: 상대 경로는 자료 폴더(macros_v2 가 있는 곳) 기준."""
        import os
        p = os.path.expandvars(os.path.expanduser(str(p or "")))
        if not p:
            return p
        if os.path.isabs(p):
            return p
        base = getattr(self, "base_dir", None)
        if base is None:
            try:
                from .real import PROJECT_ROOT as base
            except Exception:
                base = os.getcwd()
        return os.path.join(base, p)

    def _file_cond(self, f: dict, ctx) -> bool:
        """조건 {"file": {"path": .., "exists": true}} — 파일·폴더가 있으면(또는 없으면) 참."""
        import os
        from .textops import fill
        p = self._abs_path(fill(f.get("path", ""), ctx.vars)[0])
        return os.path.exists(p) == bool(f.get("exists", True))

    def _do_file(self, step, ctx, path, s):
        """파일·폴더: 복사·옮기기·이름 바꾸기·지우기(휴지통)·폴더 만들기·목록·있는지·정보·글 읽기/쓰기·압축."""
        import os
        from . import fileops
        a = step.get("action", "copy")
        trash = getattr(self, "trash", None) or fileops.to_recycle_bin
        p = dict(step)
        for k in ("path", "to"):
            if p.get(k):
                p[k] = self._abs_path(p[k])
        try:
            if a == "write_text":
                res = fileops.write_text(p["path"], str(step.get("text", "")), bool(step.get("append")),
                                         step.get("overwrite", "fail"), trash)
            elif a == "read_csv":
                if not os.path.exists(p["path"]):
                    raise fileops.FileOpError(t("파일이 없음: {path}", path=p["path"]))
                res = {"value": fileops.read_csv(p["path"], step.get("header", True), step.get("sep", ","),
                                                 step.get("encoding", "")), "changed": []}
            elif a == "write_csv":
                data = step.get("data")
                if isinstance(data, str):
                    from .textops import lookup
                    data = lookup(ctx.vars, data, None)
                res = fileops.write_csv(p["path"], data, bool(step.get("append")), step.get("overwrite", "fail"),
                                        trash, step.get("sep", ","))
            else:
                res = fileops.run(a, p, trash)
        except fileops.FileOpError as e:
            raise StepFailed(str(e))
        except OSError as e:
            raise StepFailed(t("파일 작업 실패: {error}", error=e))
        for what, src, dst in res["changed"]:
            self._emit("file", path=path, action=what, src=src, dst=dst)
        if step.get("var"):
            ctx.vars[step["var"]] = res["value"]
            self._emit("set", path=path, var=step["var"], value=res["value"])

    def _do_ask(self, step, ctx, path, s):
        """사람에게 묻기: input(글) · confirm(예/아니) · choose(목록에서) · file(파일 고르기) · folder.
        timeout 초 안에 답이 없으면 default(없으면 실패). 묻는 창을 띄울 수 없는 실행(AI·명령 줄)이면 default, 없으면 실패."""
        from .textops import fill, lookup
        kind = step.get("kind", "input")
        opts = step.get("options")
        if isinstance(opts, str):
            missing = object()
            v = lookup(ctx.vars, opts, missing)
            opts = list(v) if isinstance(v, (list, tuple)) else [x.strip() for x in opts.split(",") if x.strip()]
        req = {"kind": kind, "title": step.get("title") or self.name, "message": step.get("message", ""),
               "options": [str(o) for o in (opts or [])], "default": step.get("default"),
               "timeout": step.get("timeout"), "path": path, "macro": self.name}
        if self.asker is None:
            if "default" in step:
                value = step["default"]
                self._emit("warning", path=path, message=t("묻는 창을 띄울 수 없어 기본값을 씀: {value}", value=value))
            else:
                raise StepFailed(t("사람에게 묻는 창을 띄울 수 없는 실행(AI·명령 줄)이고 기본값도 없음"))
        else:
            self._emit("ask", path=path, kind=kind, message=req["message"])
            status, value = self.asker(req, self._stop)
            self._check_stop()
            if status == "timeout":
                if "default" not in step:
                    raise StepFailed(t("{sec}초 안에 답이 없음", sec=step.get("timeout")))
                value = step["default"]
            elif status != "ok":
                raise StepFailed(t("사람이 취소함"))
        if kind == "confirm":
            value = bool(value) if not isinstance(value, str) else value.lower() in ("true", "yes", "예", "1")
        ctx.vars[step["var"]] = value
        self._emit("set", path=path, var=step["var"], value=value)

    def _do_notify(self, step, ctx, path, s):
        """알림: toast(윈도우 알림)·sound·webhook(메신저). 기록 파일에는 항상 남김. 보내기 실패는 경고(멈추지 않음),
        must=true 면 실패로."""
        ch = step.get("channels") or ["toast"]
        if isinstance(ch, str):
            ch = [ch]
        title = step.get("title") or self.name
        msg = step.get("message", "")
        send = self.notifier
        if send is None:
            from .notify import send
        errs = send(title, msg, channels=ch, level=step.get("level", "info"), url=step.get("url", ""),
                    source=self.name)
        self._emit("notify", path=path, channels=list(ch), title=title)
        if errs:
            if step.get("must"):
                raise StepFailed(t("알림을 보내지 못함: {errors}", errors="; ".join(errs)))
            self._emit("warning", path=path, message=t("알림 일부를 보내지 못함: {errors}", errors="; ".join(errs)))

    # ------------------------------------------------------------ 메모리 매크로(부가 기능)
    def _mem_spec(self, value, ctx) -> dict:
        from . import memory as mm
        from .textops import fill
        if isinstance(value, str):
            name = fill(value, ctx.vars)[0]
            spec = mm.load_values(getattr(self, "base_dir", None)).get(name)
            if spec is None:
                raise StepFailed(t("저장한 메모리 값 '{name}' 이 없음", name=name))
        elif isinstance(value, dict):
            spec = value
        else:
            raise StepFailed(t("메모리 값(저장한 이름이나 주소)이 필요"))
        errs = mm.check_spec(spec)
        if errs:
            raise StepFailed("; ".join(errs))
        return spec

    def _mem_pid(self, spec, ctx) -> int:
        from . import memory as mm
        from .textops import fill
        if self.memory_pid:
            return int(self.memory_pid)
        if spec.get("process"):
            name = fill(str(spec["process"]), ctx.vars)[0]
            pid = mm.pid_of_process(name)
            if not pid:
                raise StepFailed(t("프로그램 '{name}' 이 켜져 있지 않음", name=name))
            return pid
        if self._window is not None and getattr(getattr(self._window, "info", None), "pid", None):
            return int(self._window.info.pid)
        cfg = self.macro.get("window")
        if not cfg:
            raise StepFailed(t("어느 프로그램의 값인지 모름 — 매크로 대상 창을 정하거나 주소에 process 를 쓰세요"))
        try:
            from .win_window import find_window       # 창을 앞으로 가져오지 않고 번호만 찾음
            return int(find_window(cfg).pid)
        except Exception as e:
            raise StepFailed(t("대상 창 문제: {error}", error=e))

    def _mem_read(self, value, ctx):
        from . import memory as mm
        if not mm.enabled(getattr(self, "base_dir", None)):
            raise StepFailed(t("메모리 매크로 부가 기능이 꺼져 있음 — 설정 → 부가 기능에서 켜세요"))
        spec = self._mem_spec(value, ctx)
        pid = self._mem_pid(spec, ctx)
        if self._memory is None:
            self._memory = mm.MemorySession(self.memory_reader or mm.ProcessReader)
        try:
            return self._memory.reader(pid).value(spec)
        except mm.MemoryError_ as e:
            raise StepFailed(str(e))

    def _do_memory(self, step, ctx, path, s):
        a = step.get("action", "read")
        if a == "read":
            v = self._mem_read(step.get("value"), ctx)
            ctx.vars[step["var"]] = v
            self._emit("set", path=path, var=step["var"], value=v)
            return
        # 쓰기(혼자 하는 게임용): 쓰기 권한으로 따로 붙는다. 고정은 이 실행이 끝나면 풀린다
        from . import memory as mm
        from .memwrite import Freezer, ProcessWriter
        if not mm.enabled(getattr(self, "base_dir", None)):
            raise StepFailed(t("메모리 매크로 부가 기능이 꺼져 있음 — 설정 → 부가 기능에서 켜세요"))
        spec = self._mem_spec(step.get("value"), ctx)
        pid = self._mem_pid(spec, ctx)
        key = step["value"] if isinstance(step.get("value"), str) else json.dumps(step.get("value"), sort_keys=True)
        try:
            w = self._mem_writers.get(pid) if hasattr(self, "_mem_writers") else None
            if w is None:
                factory = getattr(self, "memory_writer", None) or (
                    lambda p: ProcessWriter(p, root=getattr(self, "base_dir", None)))
                self._mem_writers = getattr(self, "_mem_writers", {})
                w = self._mem_writers[pid] = factory(pid)
            value = self._value_of(step.get("set"), ctx)
            if a == "write":
                addr = w.write(spec, value)
                self._emit("memory_write", path=path, address=hex(addr), value=value)
            elif a == "freeze":
                fz = self._mem_freezers.get(pid) if hasattr(self, "_mem_freezers") else None
                if fz is None:
                    self._mem_freezers = getattr(self, "_mem_freezers", {})
                    fz = self._mem_freezers[pid] = Freezer(w, float(step.get("interval", 0.1)))
                fz.set(key, spec, value)
                self._emit("memory_freeze", path=path, value=value, on=True)
            else:
                fz = getattr(self, "_mem_freezers", {}).get(pid)
                if fz is not None:
                    fz.clear(key)
                self._emit("memory_freeze", path=path, on=False)
        except mm.MemoryError_ as e:
            raise StepFailed(str(e))

    def _memory_shutdown(self):
        for fz in getattr(self, "_mem_freezers", {}).values():
            try:
                fz.stop()
            except Exception:
                pass
        self._mem_freezers = {}
        for w in getattr(self, "_mem_writers", {}).values():
            try:
                w.close()
            except Exception:
                pass
        self._mem_writers = {}
        if self._memory is not None:
            try:
                self._memory.close()
            except Exception:
                pass
            self._memory = None

    def _do_pdf(self, step, ctx, path, s):
        """PDF 읽기: text(글 전체) · extract(규칙으로 값 뽑기) · table(표 하나를 줄 목록으로).
        기본은 프로그램에 든 PDF 부품(워드 없이), via="word" 이거나 부품이 없으면 워드로 연다(창 없음)."""
        from . import pdfread
        from .office import OfficeError
        from .textops import TextOpError, text_op
        a = step.get("action", "text")
        fp = self._abs_path(step["path"])
        use_word = step.get("via") == "word" or not pdfread.available()

        def get_tables():
            return self._office().run("word", "pdf_tables", {"path": fp}) if use_word else pdfread.read_tables(fp)

        def get_text():
            if use_word:
                txt = self._office().run("word", "pdf_text", {"path": fp})
                if not (txt or "").strip():
                    raise pdfread.PdfError(t("PDF 에 글자가 없음(그림으로 스캔한 PDF 일 수 있음): {path}", path=fp))
                return txt
            return pdfread.read_text(fp)
        try:
            if a == "table":
                tables = get_tables()
                i = int(step.get("index", 1))
                if not tables:
                    raise StepFailed(t("PDF 에 표가 없음: {path}", path=fp))
                try:
                    grid = tables[i - 1 if i > 0 else i]
                except IndexError:
                    raise StepFailed(t("{n}번째 표가 없음(모두 {count}개)", n=i, count=len(tables)))
                head = grid[0] if step.get("header", True) and grid else []
                value = []
                for n, row in enumerate(grid[1:] if head else grid, 1):
                    if not any(c for c in row):
                        continue
                    o = row_item(n)
                    for j, c in enumerate(row):
                        o[str(j + 1)] = c
                        if j < len(head) and head[j]:
                            o[head[j]] = c
                    value.append(o)
            else:
                text = get_text()
                if a == "extract":
                    try:
                        value = text_op("extract", text, step, ctx.vars)
                    except TextOpError as e:
                        raise StepFailed(str(e))
                else:
                    value = text
        except (OfficeError, pdfread.PdfError) as e:
            raise StepFailed(t("PDF 읽기 실패: {error}", error=e))
        ctx.vars[step["var"]] = value
        self._emit("set", path=path, var=step["var"], value=(f"{len(value)} rows" if isinstance(value, list) and a == "table"
                                                            else (value[:200] if isinstance(value, str) else value)))

    def _mail_backend(self, via: str, step: Optional[dict] = None):
        step = step or {}
        key = f"{via}:{step.get('service') or step.get('account') or ''}"
        cache = self.__dict__.setdefault("_mail_backends", {})
        if key not in cache:
            maker = getattr(self, "mail_factory", None)
            if maker is not None:
                cache[key] = maker(via)
            else:
                from .mail import backend
                cache[key] = backend(via, self, step)
        return cache[key]

    def _mail_ids(self, step, ctx) -> list:
        """mail(메일 하나·목록·id 글자) → id 목록."""
        from .textops import lookup
        v = step.get("mail")
        if isinstance(v, str):
            gone = object()
            got = lookup(ctx.vars, v, gone)
            v = v if got is gone else got
        if isinstance(v, dict):
            v = [v]
        if not isinstance(v, (list, tuple)):
            v = [v]
        ids = [x.get("id") if isinstance(x, dict) else x for x in v]
        ids = [i for i in ids if i]
        if not ids:
            raise StepFailed(t("다룰 메일이 없음(먼저 '찾기'로 메일을 골라 변수에 넣으세요)"))
        return ids

    def _do_mail(self, step, ctx, path, s):
        """메일: find · read · save_attachments · mark_read · move · send (via outlook / web / server).
        보내기 기본은 임시 보관함(send_now=true 일 때만 바로 보냄). 보낸 것은 실행 기록에."""
        import os
        from . import fileops
        from .mail import MailError, split_list
        via = step.get("via", "outlook")
        a = step.get("action", "find")
        try:
            mb = self._mail_backend(via, step)
            value = None
            if a == "find":
                crit = {k: step[k] for k in ("folder", "from", "subject", "unread", "has_attachment", "days", "max")
                        if k in step}
                if "mail_folder" in step:
                    crit["folder"] = step["mail_folder"]
                value = mb.find(crit)
                self._emit("mail", path=path, via=via, action=a, count=len(value))
            elif a == "read":
                ids = self._mail_ids(step, ctx)
                value = mb.read(ids[0])
            elif a == "save_attachments":
                folder = self._abs_path(step.get("path") or "첨부")
                os.makedirs(folder, exist_ok=True)
                trash = getattr(self, "trash", None) or fileops.to_recycle_bin
                saved = []
                for mid in self._mail_ids(step, ctx):
                    for name, save in mb.attachments(mid, step.get("pattern", "*")):
                        from .mail import safe_name
                        dst = fileops._resolve_clash(os.path.join(folder, safe_name(name)),
                                                     step.get("overwrite", "number"), trash)
                        if dst is None:
                            continue
                        save(dst)
                        saved.append(dst)
                        self._emit("file", path=path, action="mail_attachment", src=name, dst=dst)
                value = saved
            elif a == "mark_read":
                for mid in self._mail_ids(step, ctx):
                    mb.mark_read(mid)
            elif a == "move":
                for mid in self._mail_ids(step, ctx):
                    mb.move(mid, step.get("to_folder") or step.get("to") or "")
            elif a == "send":
                atts = [self._abs_path(p) for p in split_list(step.get("attachments"))]
                for p in atts:
                    if not os.path.exists(p):
                        raise StepFailed(t("첨부할 파일이 없음: {path}", path=p))
                msg = {"to": step.get("to", ""), "cc": step.get("cc", ""), "subject": step.get("subject", ""),
                       "body": step.get("body", ""), "attachments": atts}
                now = bool(step.get("send_now"))
                value = mb.send(msg, now)
                self._emit("mail_sent" if value == "sent" else "mail_draft", path=path, via=via, to=msg["to"],
                           cc=msg["cc"], subject=msg["subject"], attachments=[os.path.basename(p) for p in atts])
        except MailError as e:
            raise StepFailed(t("메일 {action} 실패: {error}", action=a, error=e))
        if step.get("var"):
            ctx.vars[step["var"]] = value
            self._emit("set", path=path, var=step["var"],
                       value=f"{len(value)} mails" if a == "find" else (value[:200] if isinstance(value, str) else value))

    def _do_list(self, step, ctx, path, s):
        """목록: add(하나 더하기, unique 면 같은 것 빼기) · sort(칸 기준 정렬) · clear · unique · count."""
        from .listops import TextOpError, build_item, sort_items, unique
        name = step["var"]
        cur = ctx.vars.get(name)
        a = step.get("action", "add")
        if cur is None or not isinstance(cur, list):
            if a in ("add", "clear"):
                cur = []
            elif a != "count":
                raise StepFailed(t("목록 변수가 아님: {name}", name=name))
        try:
            if a == "add":
                item = build_item(step.get("value"), ctx.vars)
                if step.get("unique") and item in cur:
                    value = cur
                else:
                    value = list(cur) + [item]
            elif a == "sort":
                keys = step.get("by") or []
                if isinstance(keys, str):
                    keys = [{"key": k.strip()} for k in keys.split(",") if k.strip()]
                keys = [dict(k, order=k.get("order", step.get("order", "asc"))) for k in keys] or \
                    [{"key": "", "order": step.get("order", "asc")}]
                value = sort_items(list(cur), keys)
            elif a == "clear":
                value = []
            elif a == "unique":
                value = unique(cur)
            else:
                value = len(cur) if isinstance(cur, list) else 0
        except TextOpError as e:
            raise StepFailed(str(e))
        out = step.get("to_var") or name
        ctx.vars[out] = value
        self._emit("set", path=path, var=out, value=(f"{len(value)} items" if isinstance(value, list) else value))

    def _do_calc(self, step, ctx, path, s):
        """계산: 식(숫자·변수·사칙연산·round 등)의 결과를 변수에."""
        from .textops import TextOpError, calc
        try:
            value = calc(step["expr"], ctx.vars)
        except TextOpError as e:
            raise StepFailed(str(e))
        ctx.vars[step["var"]] = value
        self._emit("set", path=path, var=step["var"], value=value)

    def _do_set(self, step, ctx, path, s):
        name = step["var"]
        if "add" in step:
            cur = ctx.vars.get(name, 0)
            if isinstance(cur, bool) or not isinstance(cur, (int, float)):
                cur = 0
            ctx.vars[name] = cur + step["add"]
        else:
            ctx.vars[name] = _now_value(step["value"], self.clock.now(), ctx.vars)   # {"now": true} 지금 시각(초), {"var": v} 다른 변수 값
        self._emit("set", path=path, var=name, value=ctx.vars[name])

    def _read_number_memory(self, step, ctx, path):
        """숫자 읽기의 '메모리 먼저'. 돌려줌: 값(정수) 또는 None(화면으로 넘어감). 읽기만 한다."""
        mcfg = step.get("memory")
        if not mcfg:
            return None
        from . import memory as mm
        if not mm.enabled(getattr(self, "base_dir", None)):
            return None                                     # 부가 기능 꺼짐 → 예전처럼 화면으로만
        try:
            v = self._mem_read(mcfg.get("value"), ctx)
            rg = mcfg.get("range")
            if not isinstance(v, (int, float)) or (rg and not (rg[0] <= v <= rg[1])):
                raise StepFailed(t("메모리 값이 말이 안 됨({v})", v=v))
            self._emit("read", path=path, var=step["var"], text="memory", value=int(v), score=1.0, source="memory")
            return int(v)
        except StepFailed as e:
            warned = self.__dict__.setdefault("_mem_warned", set())
            key = str(mcfg.get("value"))
            if key not in warned:                            # 한 실행에 한 번만 알림
                warned.add(key)
                msg = t("메모리 값을 다시 찾아야 해요 — 화면 인식으로 읽음({why})", why=e)
                self._emit("warning", path=path, message=msg)
                try:
                    from . import notify as nt
                    nt.send(t("메모리 값을 다시 찾아야 해요"), msg, channels=("log",), level="warn",
                            source=self.name, root=getattr(self, "base_dir", None))
                except Exception:
                    pass
            return None

    def _do_read_number(self, step, ctx, path, s):
        """영역의 숫자를 읽어 정수로 변수에 넣는다. 못 읽으면 스텝 실패(변수는 그대로).
        memory 가 있으면(부가 기능 켜짐) 메모리로 먼저 읽고, 안 되면 화면으로."""
        mv = self._read_number_memory(step, ctx, path)
        if mv is not None:
            ctx.vars[step["var"]] = mv
            return
        from .numread import parse_number
        r = step["region"]
        ox, oy = self._base(step, ctx)
        region = (int(r[0]) + ox, int(r[1]) + oy, int(r[2]), int(r[3]))
        self.vision.new_frame()
        opts = {"font": step.get("font"),
                "confidence": step["confidence"] if "confidence" in step else None}
        text, score = self.vision.read_text(region, opts)
        part = step.get("part")
        if part is not None and "/" not in text:
            value = None                    # part 를 썼으면 '앞/뒤' 꼴이어야 한다
        else:
            value = parse_number(text, part or "first")
        self._emit("read", path=path, var=step["var"], text=text, value=value, score=round(score, 3))
        if value is None:
            raise StepFailed(t("숫자를 못 읽음 — 읽힌 글자 {got}", got=repr(text)) if text
                             else t("숫자를 못 읽음 — 영역에 숫자가 안 보임"))
        ctx.vars[step["var"]] = value

    @staticmethod
    def _value_of(v, ctx):
        """{"var": 이름} 이면 그 변수 값(없으면 None), 아니면 그대로."""
        if isinstance(v, dict) and set(v) == {"var"}:
            return ctx.vars.get(v["var"])
        return v

    def _do_set_result(self, step, ctx, path, s):
        self.value = self._value_of(step["value"], ctx)

    def _do_return(self, step, ctx, path, s):
        raise _Return(self._value_of(step["value"], ctx) if "value" in step else self.value)

    def _do_launch(self, step, ctx, path, s):
        """프로그램·주소 실행(게임 다시 켜기 등). 기다리기는 wait_window 로."""
        launcher = self.launcher
        if launcher is None:
            import os
            if not hasattr(os, "startfile"):
                raise StepFailed(t("이 환경에서는 launch 를 쓸 수 없음"))
            launcher = os.startfile
        try:
            launcher(step["target"])
        except Exception as e:
            raise StepFailed(t("실행 실패: {target} — {error}", target=step['target'], error=e))
        self._emit("launch", path=path, target=step["target"])

    def _do_close_window(self, step, ctx, path, s):
        """대상 창을 정상 종료(WM_CLOSE). 게임이 멈췄을 때 다시 켜기 전에."""
        win = self._get_window()
        if not win.close(float(step.get("timeout", 30))):
            raise StepFailed(t("창이 닫히지 않음(시간 초과)"))
        self._emit("window_closed", path=path)

    def _do_wait_window(self, step, ctx, path, s):
        """대상 창이 (다시) 생길 때까지 기다림. 창이 없어도 실패하지 않고 기다린다."""
        timeout = float(step.get("timeout", 120))
        start = self.clock.now()
        while True:
            self._check_stop()
            ok = False
            try:
                ok = self._get_window().is_open()
            except StepFailed:
                self._window = None          # 아직 없음 → 다음에 새로 찾기
            if ok:
                return
            if self.clock.now() - start >= timeout:
                raise StepFailed(t("{timeout:g}초 안에 창이 안 생김", timeout=timeout))
            self._sleep(1.0)

    def _do_snapshot(self, step, ctx, path, s):
        """지금 화면(창이 있으면 그 창)을 PNG 로 저장 — 모르는 화면을 나중에 보고 템플릿을 만들 때."""
        import os
        import time as _t
        name = step.get("name") or self.name
        d = self.snapshot_dir or os.path.join("logs", "snapshots")
        safe = "".join(ch for ch in name if ch not in '\\/:*?"<>|')
        fp = os.path.join(d, f"{_t.strftime('%Y%m%d_%H%M%S')}_{safe}.png")
        save = getattr(self.vision, "save_region", None)
        if save is None:
            raise StepFailed(t("이 환경은 화면 저장을 지원하지 않음"))
        try:
            region = None
            if self.macro.get("window"):
                ox, oy = self._origin()
                size = getattr(self._get_window(), "client_size", None)
                if size:
                    w, h = size()
                    region = (ox, oy, w, h)
            if region is None:
                region = self.vision.screen_rect()
            save(region, fp)
        except StepFailed:
            raise
        except Exception as e:
            raise StepFailed(t("화면 저장 실패: {error}", error=e))
        self._emit("snapshot", path=path, file=fp)

    # ------------------------------------------------------------ 막히면 AI 한 번 부르기
    # ------------------------------------------------------------ 헛돎 알아채기·스스로 고치기(11-23)
    def _heal_check(self, path: str, is_input: bool = True):
        heal = self._heal
        key = f"{self.name}:{path}" + ("" if is_input else ":찾음")
        if not heal.note(key, is_input):
            return
        img, _region = self._rescue_grab()
        if img is None:
            return
        from .rescue import fingerprint
        fp = fingerprint(img)
        if heal.note_screen(key, fp):
            self._on_stuck(key, path, img, fp)

    def _on_stuck(self, key: str, path: str, img, fp: str):
        heal = self._heal
        heal.busy = True
        try:
            ev = heal.evidence(key, img, list(self._recent), detail=t("같은 화면에서 같은 스텝이 계속 눌림(헛돎)"))
            plan = heal.plan(key, fp)
            action = plan["action"] if plan else t("없음")
            heal.log(사건="막힘", 위치=key, 대처=action, 증거=ev)
            self._emit("selfheal", path=path, stuck=key, action=action, evidence=ev)
            if plan is None:
                self._emit("warning", path=path, message=t("헛돎: 해 볼 대처를 다 해 봄 — 사람 확인이 필요함({key})", key=key))
                return
            saved = plan.get("saved")
            steps = (saved or {}).get("steps")
            ctx = self._cur_ctx or Context({})
            s = dict(self.settings, timeout=1.0)
            if steps:
                self._exec_steps(steps, ctx, path + ".heal")
            elif action == "close":
                self._heal_close(ctx, s, path)
            elif action == "recover":
                self._exec_steps([{"type": "call", "macro": heal.cfg["recover_macro"], "on_fail": "skip"}],
                                 ctx, path + ".heal")
            elif action == "ai":
                steps = self._heal_ai(key, path, img, fp)
                if steps is None:
                    heal.log(위치=key, 단계="ai", 결과="안 통함", 이유=t("AI 답 없음·거부"))
                    return
            heal.started(key, fp, action, saved, steps)
            if action == "rest":
                heal.rest(self.name)
                if len(self._call_stack) > 1:            # 하위 매크로면 지금 끝내고, 부르는 쪽은 한동안 건너뜀
                    raise _Return(t("쉬는 중"))
                self._sleep(min(float(heal.cfg["rest_min"]) * 60.0, 3600.0))
        finally:
            heal.busy = False

    def _heal_close(self, ctx, s: dict, path: str) -> bool:
        """닫기류 대상 누르기: 매크로가 정한 닫기 대상(그림 등) → 창 요소 '닫기·취소'. 하나 누르면 True."""
        from .selfheal import GENERIC_CLOSE_NAMES
        cands = list(self._heal.cfg.get("close_targets") or [])
        if self._heal.cfg.get("generic_close", True):
            cands += [{"element": {"name": n, "type": "button"}} for n in GENERIC_CLOSE_NAMES
                      if n in ("닫기", "취소", "Close", "Cancel")]      # '확인·계속'은 무언가를 진행시킬 수 있어 뺌. 대상 프로그램의 언어는 우리 화면 언어와 따로라 둘 다 봄
        for tg in cands:
            try:
                ok, _p = self._await({"exists": tg}, ctx, s, 0.5, path)
                if not ok:
                    continue
                pos = self._locate(tg, ctx, s, path)
                self._click_at(pos, "left", 1, s, path + ".heal")
                return True
            except (_Stopped, _Flow):
                raise
            except Exception:
                continue
        return False

    def _heal_ai(self, key: str, path: str, img, fp: str):
        """AI 한 번: 증거를 넘기고 스텝을 받아(안전 검사 통과 때만) 실행. 실행한 스텝 또는 None."""
        import json as _json
        import os as _os
        import time as _t
        from .rescue import DEFAULTS, check_safe
        rescuer = self.rescuer
        ai = getattr(rescuer, "ai", None)
        if rescuer is None or ai is None or not ai.available() or not getattr(ai, "consented", lambda: True)():
            return None
        cfg = {**DEFAULTS, **(self.macro.get("ai_rescue") or {}), "on": True}
        if rescuer.limits.blocked(cfg, f"heal|{key}", fp):
            return None
        _os.makedirs(rescuer.state_dir, exist_ok=True)
        safe = "".join(ch for ch in self.name if ch not in '\\/:*?"<>|')
        shot = _os.path.join(rescuer.state_dir, f"{_t.strftime('%Y%m%d_%H%M%S')}_{safe}_stuck.png")
        try:
            import cv2 as _cv2
            _cv2.imencode(".png", img)[1].tofile(shot)
        except Exception:
            return None
        win = ""
        try:
            win = self._get_window().describe() if self.macro.get("window") else t("화면 전체")
        except Exception:
            pass
        fields = {"purpose": self.macro.get("description") or t("(목적 설명 없음)"), "name": self.name,
                  "step": key, "reason": t("같은 화면에서 이 스텝이 계속 반복됨(헛돎) — 화면을 원래 흐름으로 되돌릴 스텝"),
                  "window": win, "log": "\n".join(_json.dumps(e, ensure_ascii=False, default=str)
                                                  for e in list(self._recent)[-30:])}
        try:
            fix, _why, _raw = rescuer.ask_ai(fields, shot)
        except Exception:
            rescuer.limits.record(f"heal|{key}", fp, False)
            return None
        c = _Checker()
        c.steps("heal", fix, 0)
        if not fix or check_safe(fix, cfg, rescuer.image_exists) + c.errors:
            rescuer.limits.record(f"heal|{key}", fp, False)
            return None
        rescuer.limits.record(f"heal|{key}", fp, True)
        self._exec_steps(fix, self._cur_ctx or Context({}), path + ".heal")
        return fix

    def _rescue_grab(self):
        """막힌 순간의 화면(창이 있으면 그 창). (그림, 영역) 또는 (None, None)."""
        grab = getattr(self.vision, "grab", None)
        if grab is None:
            return None, None
        try:
            region = None
            if self.macro.get("window"):
                ox, oy = self._origin()
                size = getattr(self._get_window(), "client_size", None)
                if size:
                    w, h = size()
                    region = (ox, oy, w, h)
            if region is None:
                region = self.vision.screen_rect()
            cfg = self.macro.get("window") or {}
            if cfg and not self._background and cfg.get("activate", True):     # 다른 창이 덮고 있으면 지문이 달라짐
                try:
                    if self._get_window().activate():
                        self._sleep(0.2)
                except _Stopped:
                    raise
                except Exception:
                    pass
            if hasattr(self.vision, "new_frame"):
                self.vision.new_frame()
            return grab(region), region
        except _Stopped:
            raise
        except Exception:
            return None, None

    def _apply_fix(self, fix: list, step: dict, ctx: Context, path: str, settings: dict, handler) -> bool:
        """해결 스텝 실행 → 막혔던 스텝 다시 한 번. 둘 다 되면 True."""
        try:
            self._exec_steps(fix, ctx, path + ".rescue")
            self._check_stop()
            handler(step, ctx, path, settings)
            return True
        except StepFailed:
            return False

    def _try_rescue(self, step: dict, ctx: Context, path: str, settings: dict, handler, err: "StepFailed") -> bool:
        import json as _json
        import os as _os
        import time as _t
        from .rescue import DEFAULTS, SAME_SCREEN, check_safe, distance, fingerprint
        cfg = {**DEFAULTS, **(self.macro.get("ai_rescue") or {})}
        rules = self.macro.get("rescues") or []
        if not rules and not cfg.get("on"):
            return False
        key = str(step.get("id") or path)
        img, region = self._rescue_grab()
        if img is None:
            return False
        screen = fingerprint(img)
        size = [int(region[2]), int(region[3])]
        rescuer = self.rescuer
        if _os.environ.get("MACRO_RESCUE_DEBUG") and rescuer is not None:     # 진단용: 지문을 만든 화면 저장
            try:
                import cv2 as _cv2
                _os.makedirs(rescuer.state_dir, exist_ok=True)
                _cv2.imencode(".png", img)[1].tofile(_os.path.join(rescuer.state_dir, "debug_grab.png"))
            except Exception:
                pass
        self._rescuing = True
        try:
            from .rescue import RULE_OFF_AFTER
            for rule in rules:                                    # 1) 저장된 해결 규칙(AI 없음)
                if rule.get("off") or rule.get("step") != key or distance(rule.get("screen", ""), screen) > SAME_SCREEN:
                    continue
                if rule.get("size") and list(rule["size"]) != size:      # 창 크기가 다르면 고정 좌표가 어긋남 → 안 씀
                    continue
                self._emit("rescue", path=path, how="rule", added=rule.get("added"))
                ok = self._apply_fix(rule.get("steps") or [], step, ctx, path, settings, handler)
                before = (rule.get("fails"), rule.get("off"), rule.get("uses"))
                if ok:
                    rule.pop("fails", None)
                    rule["uses"] = int(rule.get("uses") or 0) + 1
                    self._maybe_propose_rule(rule, path, step)
                else:                                             # 연속 실패를 세고, 넘으면 그 해결을 끔
                    rule["fails"] = int(rule.get("fails") or 0) + 1
                    if rule["fails"] >= RULE_OFF_AFTER:
                        rule["off"] = True
                if rescuer is not None:
                    rescuer.log(macro=self.name, step=key, how="rule_off" if rule.get("off") else "rule", ok=ok,
                                screen=screen, fails=rule.get("fails", 0), added=rule.get("added"))
                    if (rule.get("fails"), rule.get("off"), rule.get("uses")) != before:
                        try:
                            rescuer.update_rule(self.name, rule)
                        except Exception:
                            pass
                if rule.get("off"):
                    self._emit("warning", path=path,
                               message=t("저장된 해결이 {n}번 연속 안 통해서 껐음", n=rule.get("fails")))
                if ok:
                    return True
            if not cfg.get("on"):
                return False
            ai = getattr(rescuer, "ai", None)
            if rescuer is None or ai is None or not ai.available():
                self._emit("warning", path=path, message=t("막힘: AI 연결이 없어 부르지 않음(이 컴퓨터에 명령줄 AI가 없음)"))
                return False
            if not getattr(ai, "consented", lambda: True)():
                self._emit("warning", path=path, message=t("막힘: 화면 사진 전송에 동의하지 않아 AI를 부르지 않음"))
                rescuer.log(macro=self.name, step=key, how="no_consent", screen=screen)
                return False
            if self._near_miss_now(step):                # 기준에 살짝 모자라 놓친 것이면 AI 대신 값 조정(스스로 고치기)이 맡음
                rescuer.log(macro=self.name, step=key, how="blocked", why="near_miss_tuning", screen=screen)
                return False
            limit_key = f"{self.name}|{key}"
            why_not = rescuer.limits.blocked(cfg, limit_key, screen)
            if why_not:
                self._emit("warning", path=path, message=t("막힘: {why}", why=why_not))
                rescuer.log(macro=self.name, step=key, how="blocked", why=why_not, screen=screen)
                return False
            _os.makedirs(rescuer.state_dir, exist_ok=True)
            safe = "".join(ch for ch in self.name if ch not in '\\/:*?"<>|')
            shot = _os.path.join(rescuer.state_dir, f"{_t.strftime('%Y%m%d_%H%M%S')}_{safe}.png")
            try:
                self.vision.save_region(region, shot)
            except Exception as e:
                self._emit("warning", path=path, message=t("막힘: 화면 사진을 못 찍음 — {error}", error=e))
                return False
            win = ""
            try:
                win = self._get_window().describe() if self.macro.get("window") else t("화면 전체")
            except Exception:
                pass
            log_lines = "\n".join(_json.dumps(ev, ensure_ascii=False, default=str) for ev in list(self._recent)[-30:])
            fields = {"purpose": self.macro.get("description") or t("(목적 설명 없음)"), "name": self.name,
                      "step": _json.dumps(step, ensure_ascii=False), "reason": err.reason, "window": win,
                      "log": log_lines}
            self._emit("rescue", path=path, how="ai_call", image=shot)
            try:
                fix, why, raw = rescuer.ask_ai(fields, shot)
            except Exception as e:
                rescuer.limits.record(limit_key, screen, False)
                rescuer.log(macro=self.name, step=key, how="ai_error", error=str(e), image=shot)
                self._emit("warning", path=path, message=t("막힘: AI 호출 실패 — {error}", error=e))
                return False
            c = _Checker()
            c.steps("rescue", fix, 0)
            probs = check_safe(fix, cfg, rescuer.image_exists) + c.errors
            if probs:
                rescuer.limits.record(limit_key, screen, False)
                rescuer.log(macro=self.name, step=key, how="ai_rejected", problems=probs, steps=fix, why=why,
                            image=shot)
                self._emit("warning", path=path, message=t("막힘: AI 제안을 버림 — {p}", p="; ".join(probs[:3])))
                return False
            ok = self._apply_fix(fix, step, ctx, path, settings, handler)
            rescuer.limits.record(limit_key, screen, ok)
            if not ok:
                rescuer.log(macro=self.name, step=key, how="ai_failed", steps=fix, why=why, image=shot)
                self._emit("warning", path=path, message=t("막힘: AI 제안을 해 봤지만 풀리지 않음"))
                return False
            rule = {"step": key, "screen": screen, "size": size, "steps": fix, "reason": err.reason, "why": why, "by": "ai",
                    "added": _t.strftime("%Y-%m-%d %H:%M:%S")}
            self.macro.setdefault("rescues", []).append(rule)
            backup = None
            try:
                backup = rescuer.save_rule(self.name, rule)
            except Exception as e:
                self._emit("warning", path=path, message=t("막힘 해결 규칙 저장 실패: {error}", error=e))
            rescuer.log(macro=self.name, step=key, how="ai_saved", steps=fix, why=why, image=shot, backup=backup)
            self._emit("rescue", path=path, how="ai_saved", why=why)
            return True
        finally:
            self._rescuing = False

    # ------------------------------------------------------------ 오피스 스텝
    def _office(self):
        if self.office is None:
            from .office import OfficeSession
            self.office = OfficeSession()
        return self.office

    def _office_step(self, kind, step, ctx, path):
        from .office import OfficeError, fill_vars
        a = step["action"]
        params = {}
        try:
            for k, v in step.items():
                if k in ("type", "action", "note", "on_fail", "retries", "var"):
                    continue
                v = self._value_of(v, ctx)
                params[k] = fill_vars(v, ctx.vars) if k != "value" or isinstance(v, str) else v
                if k in ("path", "to_file") and isinstance(params[k], str) and params[k]:
                    params[k] = self._abs_path(params[k])     # 상대 경로는 자료 폴더 기준(파일 단계와 같게)
            value = self._office().run(kind, a, params)
        except OfficeError as e:
            raise StepFailed(t("{kind} {action} 실패: {error}", kind=kind, action=a, error=e))
        except Exception as e:      # COM 오류 등
            raise StepFailed(t("{kind} {action} 실패: {error}", kind=kind, action=a, error=e))
        self._emit("office", path=path, app=kind, action=a,
                   value=(str(value)[:200] if value is not None else None))
        if step.get("var") and a in ("read", "last_row", "read_field", "run_macro", "save_as", "print"):
            ctx.vars[step["var"]] = value
            self._emit("set", path=path, var=step["var"], value=value)

    def _do_excel(self, step, ctx, path, s):
        self._office_step("excel", step, ctx, path)

    def _do_word(self, step, ctx, path, s):
        self._office_step("word", step, ctx, path)

    def _do_hwp(self, step, ctx, path, s):
        self._office_step("hwp", step, ctx, path)

    def _office_shutdown(self):
        if self._office_owner and self.office is not None:
            try:
                self.office.shutdown()
            except Exception:
                pass
            self.office = None

    # ------------------------------------------------------------ 웹 요소 스텝
    def _web(self):
        if self.web is None:
            from .web import EgoWeb
            self.web = EgoWeb()
        return self.web

    def _web_has(self, w: dict) -> bool:
        r = self._web().run("exists", selector=w["selector"], state=w.get("state", "visible"),
                            page=w.get("page", "p1"), timeout_ms=300, should_stop=self._stop.is_set)
        if not r.get("ok"):
            raise StepFailed(t("웹 확인 실패: {error}", error=r.get('error')))
        return bool(r.get("value"))

    def _do_web(self, step, ctx, path, s):
        """웹 페이지 요소로 브라우저 조작(에고라이트). 좌표·그림을 쓰지 않는다."""
        import os
        import time as _t
        a = step["action"]
        text = self._value_of(step.get("text", ""), ctx)
        import re as _re

        def fill(v):                                      # 선택자·주소·글자 안의 {변수} 를 값으로(반복 중 행 번호 등).
            from .textops import fill as _fill            # 있는 변수 이름만 바꾸고, 나머지 중괄호는 그대로 둔다
            return _fill(v, ctx.vars)[0]
        selector, url = fill(step.get("selector", "")), fill(step.get("url", ""))
        text = fill(text)
        tmo = step.get("timeout")
        timeout_ms = int(float(tmo if tmo is not None else 5) * 1000)
        shot = ""
        if a == "screenshot":
            d = self.snapshot_dir or os.path.join("logs", "snapshots")
            os.makedirs(d, exist_ok=True)
            name = "".join(ch for ch in (step.get("name") or self.name) if ch not in '\\/:*?"<>|')
            shot = os.path.abspath(os.path.join(d, f"{_t.strftime('%Y%m%d_%H%M%S')}_{name}.png"))
        r = self._web().run(a, selector=selector, url=url,
                            text="" if text is None else str(text), page=step.get("page", "p1"),
                            timeout_ms=timeout_ms, state=step.get("state", "visible"), path=shot,
                            label=step.get("note", "") or "", should_stop=self._stop.is_set)
        self._emit("web", path=path, action=a, selector=step.get("selector"), ok=r.get("ok"),
                   url=r.get("url"), value=(str(r.get("value"))[:200] if r.get("value") is not None else None),
                   error=r.get("error"))
        if not r.get("ok"):
            raise StepFailed(t("웹 {action} 실패: {error}", action=a, error=r.get('error')))
        if a == "download":
            value = self._save_download(step, r.get("value") or {}, ctx, path)
            if step.get("var"):
                ctx.vars[step["var"]] = value
                self._emit("set", path=path, var=step["var"], value=value)
            return
        if step.get("var") and a in ("read", "url", "table"):
            ctx.vars[step["var"]] = r.get("value")
            self._emit("set", path=path, var=step["var"], value=r.get("value") if a != "table" else
                       f"{len(r.get('value') or [])} rows")

    def _save_download(self, step, got: dict, ctx, path) -> str:
        """웹에서 받은 내용을 path(폴더면 받은 이름 그대로)로 저장. 같은 이름은 overwrite(기본 '번호 붙여 새로')."""
        import base64
        import os
        from . import fileops
        from .textops import fill
        dest = self._abs_path(fill(step.get("path") or "", ctx.vars)[0]) or self._abs_path("downloads")
        name = "".join(ch for ch in (got.get("name") or "download") if ch not in '\\/:*?"<>|') or "download"
        if os.path.isdir(dest) or dest.endswith(("\\", "/")) or not os.path.splitext(dest)[1]:
            os.makedirs(dest, exist_ok=True)
            dest = os.path.join(dest, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        trash = getattr(self, "trash", None) or fileops.to_recycle_bin
        try:
            final = fileops._resolve_clash(dest, step.get("overwrite", "number"), trash)
        except fileops.FileOpError as e:
            raise StepFailed(str(e))
        if final is None:
            return ""
        with open(final, "wb") as fh:
            fh.write(base64.b64decode(got.get("data") or b""))
        self._emit("file", path=path, action="download", src=step.get("url") or step.get("selector") or "", dst=final)
        return final

    def _do_stop(self, step, ctx, path, s):
        raise _MacroStop(step.get("reason", t("stop 스텝")), path)
