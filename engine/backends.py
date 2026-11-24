"""
엔진이 바깥 세상과 만나는 인터페이스 (시계·창·인식·입력).

실제 구현(Win32/OpenCV)과 테스트용 가짜 구현이 같은 메서드를 가진다.
엔진은 이 인터페이스만 쓰므로 화면 없이도 실행 의미를 테스트할 수 있다.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from .i18n import t

Pos = Tuple[int, int]


@dataclass
class Match:
    found: bool
    pos: Optional[Pos] = None   # 화면 절대좌표 (중심)
    score: float = 0.0          # 최고 점수 (못 찾았을 때도 기록)


class WindowNotFound(RuntimeError):
    pass


# ---------------------------------------------------------------- 인터페이스

class Clock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        """seconds 동안 대기. 중간에 정지되면 False."""
        if seconds <= 0:
            return not stop.is_set()
        return not stop.wait(seconds)


class Window:
    """좌표 기준점. window 설정이 없으면 화면 전체(원점 0,0)."""

    def origin(self) -> Pos:
        return (0, 0)

    def activate(self) -> Optional[bool]:
        """맨 앞으로. 실패했으면 False (None 은 '해당 없음')."""
        return None

    def describe(self) -> str:
        return t("화면 전체")

    def warnings(self) -> List[str]:
        return []

    def close(self, timeout: float) -> bool:
        """창(프로그램)을 정상 종료 요청하고 사라질 때까지 기다림. 지원 안 하면 False."""
        return False

    def is_open(self) -> bool:
        """창이 지금 있고 최소화가 아닌지(다시 찾기 포함)."""
        return True

    def background_input(self) -> Optional["Input"]:
        """'뒤에서 실행'용 입력(진짜 마우스·포커스를 안 씀). 지원 안 하면 None."""
        return None

    def unhide(self) -> None:
        """'숨겨서 실행'으로 숨긴 창을 원래대로(숨긴 게 없으면 아무것도 안 함)."""
        return None

    def capture_source(self):
        """'뒤에서 실행'용 화면 출처(Vision.bind_window 에 넘김). 지원 안 하면 None."""
        return None

    def element_hwnd(self) -> Optional[int]:
        """창 요소를 찾을 창 핸들. None 이면 맨 앞 창."""
        return None

    def find_element(self, spec: dict) -> Optional[Tuple[int, int, int, int]]:
        """창 요소(버튼 등)를 이름으로 찾아 화면 기준 (x, y, 너비, 높이). 없으면 None."""
        from . import win_uia
        return win_uia.find(self.element_hwnd(), spec)

    def set_element_value(self, spec: dict, text: str) -> bool:
        """입력 칸에 글자를 키보드 없이 넣음. 못 하면 False(그때는 그 칸을 누르고 키로 입력)."""
        from . import win_uia
        return win_uia.set_value(self.element_hwnd(), spec, text)

    def invoke_element(self, spec: dict, open_: bool = False) -> bool:
        """창 요소를 마우스 없이 누름(뒤에서 실행용). open_=더블클릭(열기). 못 하면 False(그때는 보통 클릭)."""
        from . import win_uia
        try:
            return win_uia.invoke(self.element_hwnd(), spec, open_)
        except Exception:
            return False


class Vision:
    def match(self, image: str, region: Optional[Tuple[int, int, int, int]], opts: dict) -> Match:
        raise NotImplementedError

    def match_all(self, image: str, region: Optional[Tuple[int, int, int, int]], opts: dict) -> List[Pos]:
        """기준(confidence) 이상으로 맞는 곳을 모두(겹치는 건 하나로). 화면 절대좌표 중심점 목록."""
        raise NotImplementedError

    def pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        raise NotImplementedError

    def count_color(self, region: Tuple[int, int, int, int], rgb: Tuple[int, int, int],
                    tolerance: int) -> Tuple[int, Optional[Pos]]:
        """영역 안에서 rgb 와 각 채널 차이가 tolerance 이하인 픽셀 수와 그 중심(화면좌표)."""
        raise NotImplementedError

    def color_blob(self, region: Tuple[int, int, int, int], rgb: Tuple[int, int, int],
                   tolerance: int) -> Tuple[float, Optional[Pos]]:
        """영역 안 그 색 픽셀 덩어리들(안쪽 구멍은 메움) 중 가장 두꺼운 곳.
        (두께 = 가장자리까지 거리 px, 그 점의 화면좌표). 없으면 (0, None).
        안의 그림이 매번 달라지는 말풍선·카드처럼 '틀 색'만 같은 것을 누를 때 쓴다."""
        raise NotImplementedError

    def count_vivid(self, region: Tuple[int, int, int, int], min_saturation: int,
                    min_value: int, hues=None) -> Tuple[int, Optional[Pos]]:
        """영역 안에서 HSV 채도·밝기(0~255)가 기준 이상인 픽셀 수와 그 중심.
        hues 가 있으면 색상(H, 0~180)이 그 범위들 중 하나에 드는 픽셀만 센다."""
        raise NotImplementedError

    def read_text(self, region: Tuple[int, int, int, int], opts: dict) -> Tuple[str, float]:
        """영역 안의 숫자 글자열(예: '3,695/9,937')과 가장 낮은 글자 점수. 못 읽으면 ("", 0).
        opts: font(글꼴 폴더, 이미지 폴더 기준), confidence. 글자를 빠뜨렸을 수 있으면 끝에 '?'."""
        raise NotImplementedError

    def new_frame(self) -> None:
        """폴링 한 번이 시작될 때 호출. 실제 구현은 여기서 캡처 캐시를 비운다."""

    def bind_window(self, source) -> None:
        """'뒤에서 실행': 화면 대신 그 창만 직접 캡처(source=None 이면 원래대로)."""


class Input:
    def move(self, x: int, y: int) -> None: raise NotImplementedError
    def down(self, button: str) -> None: raise NotImplementedError
    def up(self, button: str) -> None: raise NotImplementedError
    def key_down(self, key: str) -> None: raise NotImplementedError
    def key_up(self, key: str) -> None: raise NotImplementedError
    def type_text(self, text: str) -> None: raise NotImplementedError
    def position(self) -> Pos: raise NotImplementedError
    def scroll(self, amount: int, horizontal: bool = False) -> None: raise NotImplementedError


WindowFactory = Callable[[Optional[dict]], Window]


def null_window_factory(cfg: Optional[dict]) -> Window:
    if cfg:
        raise WindowNotFound(t("창 기능은 실제 백엔드에서만 지원"))
    return Window()


# ---------------------------------------------------------------- 가짜 구현 (테스트용)

class FakeClock(Clock):
    """가상 시간. sleep 은 즉시 시간만 앞으로 감. schedule 로 특정 시각에 일을 끼워넣음."""

    def __init__(self, limit: float = 10_000.0):
        self.t = 0.0
        self.limit = limit
        self._jobs: List[Tuple[float, Callable[[], None]]] = []

    def now(self) -> float:
        return self.t

    def schedule(self, at: float, fn: Callable[[], None]) -> None:
        self._jobs.append((at, fn))
        self._jobs.sort(key=lambda j: j[0])

    def _run_due(self):
        while self._jobs and self._jobs[0][0] <= self.t:
            _, fn = self._jobs.pop(0)
            fn()

    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        if stop.is_set():
            return False
        end = self.t + max(0.0, seconds)
        while self._jobs and self._jobs[0][0] <= end:
            self.t = max(self.t, self._jobs[0][0])
            self._run_due()
            if stop.is_set():
                return False
        self.t = end
        if self.t > self.limit:
            raise RuntimeError(t("FakeClock 시간 한도 초과 ({limit}s) — 무한 루프 의심", limit=self.limit))
        return not stop.is_set()


class FakeWindow(Window):
    def __init__(self, origin: Pos = (0, 0), bg_input: Optional["Input"] = None):
        self._origin = origin
        self.activated = 0
        self.bg_input = bg_input
        self.open = True
        self.closed = 0

    def close(self, timeout: float) -> bool:
        self.closed += 1
        self.open = False
        return True

    def is_open(self) -> bool:
        return self.open

    def background_input(self):
        return self.bg_input

    def capture_source(self):
        return "fake-window" if self.bg_input is not None else None

    def origin(self) -> Pos:
        return self._origin

    def activate(self) -> None:
        self.activated += 1

    # 시험용: 메뉴·잠깐 앞에서
    menus: dict = None
    commands: list = None
    focus_log: list = None

    def menu_command(self, path: str) -> int:
        if not self.menus:
            raise ValueError(t("이 창에는 표준 메뉴가 없음"))
        key = " > ".join(p.strip() for p in path.split(">"))
        if key not in self.menus:
            raise ValueError(t("메뉴에 '{path}' 이 없음", path=path))
        self.commands = (self.commands or []) + [self.menus[key]]
        return self.menus[key]

    def focus_snapshot(self):
        self.focus_log = (self.focus_log or []) + ["snapshot"]
        return ("prev", (1, 2))

    def focus_restore(self, snap) -> None:
        self.focus_log = (self.focus_log or []) + ["restore"]

    elements: list = None         # 시험용: [{"name":..,"type":..,"rect":[x,y,w,h]}] (화면 기준)

    def invoke_element(self, spec: dict, open_: bool = False) -> bool:
        return False                                  # 시험용 가짜 창: 늘 보통 클릭으로

    values: dict = None                               # 시험용: set_element_value 로 넣은 값 {요소 이름: 글자}

    def set_element_value(self, spec: dict, text: str) -> bool:
        if self.values is None:
            return False
        self.values[spec.get("name")] = text
        return True

    def find_element(self, spec: dict):
        n = 0
        for e in self.elements or []:
            if "name" in spec and (e.get("name") != spec["name"] if spec.get("match") != "contains"
                                   else spec["name"] not in e.get("name", "")):
                continue
            if spec.get("type") not in (None, "any") and e.get("type") != spec["type"]:
                continue
            if "id" in spec and e.get("id") != spec["id"]:
                continue
            if n == int(spec.get("index", 0)):
                return tuple(e["rect"])
            n += 1
        return None

    busy: int = 0                 # 시험용: 이만큼 '사람이 쓰는 중'으로 답함

    def user_active(self) -> bool:
        if self.busy > 0:
            self.busy -= 1
            return True
        return False


@dataclass
class Appearance:
    image: str
    pos: Pos
    start: float = 0.0
    end: float = float("inf")
    score: float = 0.95


class FakeVision(Vision):
    """시간대별로 어떤 이미지가 어디 보이는지 미리 정해둔 가짜 화면."""

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.items: List[Appearance] = []
        self.pixels: Dict[Pos, Tuple[int, int, int]] = {}
        self.blobs: List[tuple] = []
        self.thick_blobs: List[tuple] = []
        self.texts: List[tuple] = []
        self.match_calls = 0
        self.bound = None

    def bind_window(self, source) -> None:
        self.bound = source

    def show(self, image: str, pos: Pos, start: float = 0.0, end: float = float("inf"),
             score: float = 0.95) -> Appearance:
        a = Appearance(image, pos, start, end, score)
        self.items.append(a)
        return a

    def hide(self, image: str, at: Optional[float] = None) -> None:
        t = self.clock.now() if at is None else at
        for a in self.items:
            if a.image == image and a.end > t:
                a.end = t

    def match_all(self, image, region, opts) -> List[Pos]:
        t = self.clock.now()
        conf = opts.get("confidence", 0.8)
        out = []
        for a in self.items:
            if a.image != image or not (a.start <= t < a.end) or a.score < conf:
                continue
            if region is not None:
                x, y, w, h = region
                if not (x <= a.pos[0] < x + w and y <= a.pos[1] < y + h):
                    continue
            out.append(a.pos)
        return out

    def match(self, image, region, opts) -> Match:
        self.match_calls += 1
        t = self.clock.now()
        conf = opts.get("confidence", 0.8)
        best = Match(False, None, 0.3)
        for a in self.items:
            if a.image != image or not (a.start <= t < a.end):
                continue
            if region is not None:
                x, y, w, h = region
                if not (x <= a.pos[0] < x + w and y <= a.pos[1] < y + h):
                    continue
            if a.score >= conf:
                return Match(True, a.pos, a.score)
            if a.score > best.score:
                best = Match(False, None, a.score)
        return best

    def pixel(self, x, y):
        return self.pixels.get((x, y), (0, 0, 0))

    def show_text(self, text: str, pos: Pos, start: float = 0.0, end: float = float("inf"),
                  score: float = 0.95):
        """pos 에 숫자 글자열 text 가 보이게 한다(read_text 시험용)."""
        self.texts.append((text, pos, start, end, score))

    def read_text(self, region, opts):
        t = self.clock.now()
        x, y, w, h = region
        conf = opts.get("confidence")
        for text, pos, start, end, score in self.texts:
            if start <= t < end and x <= pos[0] < x + w and y <= pos[1] < y + h                     and (conf is None or score >= conf):
                return text, score
        return "", 0.0

    def add_blob(self, rgb, pos: Pos, count: int, start: float = 0.0, end: float = float("inf")):
        """count 개 픽셀짜리 색 덩어리를 pos 에 둔다(count_color 시험용)."""
        self.blobs.append((tuple(rgb), pos, count, start, end))

    def count_color(self, region, rgb, tolerance):
        t = self.clock.now()
        x, y, w, h = region
        total, sx, sy = 0, 0, 0
        for c, pos, n, start, end in getattr(self, "blobs", []):
            if not (start <= t < end) or not (x <= pos[0] < x + w and y <= pos[1] < y + h):
                continue
            if all(abs(a - b) <= tolerance for a, b in zip(c, rgb)):
                total += n
                sx += pos[0] * n
                sy += pos[1] * n
        return total, ((sx // total, sy // total) if total else None)

    def add_color_blob(self, rgb, pos: Pos, depth: float, start: float = 0.0, end: float = float("inf")):
        """두께 depth 인 색 덩어리를 pos 에 둔다(color_blob 시험용)."""
        self.thick_blobs.append((tuple(rgb), pos, depth, start, end))

    def color_blob(self, region, rgb, tolerance):
        t = self.clock.now()
        x, y, w, h = region
        best = (0.0, None)
        for c, pos, depth, start, end in self.thick_blobs:
            if not (start <= t < end) or not (x <= pos[0] < x + w and y <= pos[1] < y + h):
                continue
            if all(abs(a - b) <= tolerance for a, b in zip(c, rgb)) and depth > best[0]:
                best = (float(depth), pos)
        return best

    def count_vivid(self, region, min_saturation, min_value, hues=None):
        import colorsys
        t = self.clock.now()
        x, y, w, h = region
        total, sx, sy = 0, 0, 0
        for c, pos, n, start, end in self.blobs:
            if not (start <= t < end) or not (x <= pos[0] < x + w and y <= pos[1] < y + h):
                continue
            hue, sat, val = colorsys.rgb_to_hsv(*(v / 255.0 for v in c))
            if hues and not any(lo <= hue * 180 <= hi for lo, hi in hues):
                continue
            if sat * 255 >= min_saturation and val * 255 >= min_value:
                total += n
                sx += pos[0] * n
                sy += pos[1] * n
        return total, ((sx // total, sy // total) if total else None)


class FakeInput(Input):
    """입력을 시각과 함께 기록. on_click 훅으로 클릭에 반응하는 가짜 세계를 만들 수 있음."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.events: List[tuple] = []
        self.pos: Pos = (0, 0)
        self.on_click: Optional[Callable[[Pos, str], None]] = None
        self._down_at: Optional[Pos] = None

    def _rec(self, *ev):
        self.events.append((round(self.clock.now(), 4),) + ev)

    def move(self, x, y):
        self.pos = (x, y)
        self._rec("move", x, y)

    def down(self, button):
        self._down_at = self.pos
        self._rec("down", button)

    def up(self, button):
        self._rec("up", button)
        if self.on_click and self._down_at == self.pos:
            self.on_click(self.pos, button)

    def key_down(self, key):
        self._rec("key_down", key)

    def key_up(self, key):
        self._rec("key_up", key)

    def type_text(self, text):
        self._rec("type", text)

    def scroll(self, amount, horizontal=False):
        self._rec("scroll", int(amount), bool(horizontal))

    def position(self):
        return self.pos

    def clicks(self) -> List[Pos]:
        """down→up 쌍이 이루어진 좌표 목록."""
        out, cur = [], None
        for ev in self.events:
            if ev[1] == "move":
                cur = (ev[2], ev[3])
            elif ev[1] == "up":
                out.append(cur)
        return out
