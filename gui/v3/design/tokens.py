"""새 화면 디자인 값(한 곳). 색·간격·글자·모서리·움직임 길이·촘촘함은 여기서만 정한다.
시안 A(머티리얼 계열): 둥근 모서리, 색 면, 알약 모양 선택 표시, 왼쪽 레일(아이콘 + 글자)."""
from __future__ import annotations

from typing import Dict

FONT_FAMILIES = ["Pretendard", "Noto Sans KR", "Malgun Gothic"]
MONO_FAMILY = "Consolas"

COLORS: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#F7F7FB", "surface": "#FFFFFF", "surface2": "#EEF0F8", "nav": "#F1F2FA",
        "line": "#E3E5EE", "text": "#1A1C23", "muted": "#5D6170", "accent": "#4F5BD5",
        "accent_soft": "#E2E5FB", "on_accent": "#FFFFFF", "ok": "#1E8E5A", "warn": "#B7791F",
        "bad": "#C2413A", "sel": "#E2E5FB", "hover": "#ECEEF8", "guide": "#DADCE8", "run_bg": "#E8EBFC",
    },
    "dark": {
        "bg": "#121318", "surface": "#1B1D24", "surface2": "#23262F", "nav": "#16171D",
        "line": "#2E313B", "text": "#E6E7EE", "muted": "#A0A4B4", "accent": "#A9B2FF",
        "accent_soft": "#2E3463", "on_accent": "#151838", "ok": "#4CC38A", "warn": "#E5B45A",
        "bad": "#F2777A", "sel": "#2E3463", "hover": "#252833", "guide": "#30333E", "run_bg": "#262B52",
    },
}

SHAPE = {"radius_s": 8, "radius_m": 12, "radius_l": 16, "radius_btn": 18}
SPACE = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 20, "xxl": 32}
TYPE = {"small": 12, "body": 14, "input": 14, "subtitle": 16, "title": 22, "hero": 28}

# 촘촘함 2단계: 편안하게(기본) / 촘촘하게(스텝 많은 편집)
DENSITY = {
    "comfortable": {"row_main": 52, "row_steps": 34, "row_palette": 32, "control_h": 36, "pad": 20, "gap": 16},
    "compact": {"row_main": 40, "row_steps": 25, "row_palette": 26, "control_h": 30, "pad": 14, "gap": 10},
}

# 움직임 길이(ms). 0 이면 움직임 끔(움직임 줄이기)
MOTION = {"hover": 100, "toggle": 150, "list": 180, "panel": 200, "dialog_in": 220, "dialog_out": 150, "pulse": 1000}

NAV_W = 84


def build(theme: str = "light", density: str = "comfortable", scale: float = 1.0) -> dict:
    """테마·촘촘함·글자 배율을 합친 값 묶음 하나."""
    t = dict(COLORS["dark" if theme == "dark" else "light"])
    t.update(SHAPE)
    t.update(DENSITY.get(density, DENSITY["comfortable"]))
    for k, v in TYPE.items():
        t["font_" + k] = round(v * scale)
    t["theme"] = "dark" if theme == "dark" else "light"
    t["density"] = density
    t["scale"] = scale
    t["nav_w"] = NAV_W
    return t
