"""
실제 인식 백엔드: mss 로 화면 캡처, OpenCV 로 템플릿 매칭.

- 기본: 흑백 + TM_CCOEFF_NORMED 단일 배율
- multiscale: 0.8~1.2 배율 탐색 (느림, 선택)
- color_check: 매칭된 영역의 평균 색 차이로 한 번 더 확인 (선택)
- PNG 투명 영역은 마스크로 처리
- 폴링 한 번(new_frame) 안에서는 같은 영역을 다시 캡처하지 않음
"""
from __future__ import annotations

import os
import threading
from typing import Dict, Optional, Tuple

import cv2
import mss
import numpy as np
from .i18n import t

from .backends import Match, Vision

_SCALES = [1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2]


class TemplateError(FileNotFoundError):
    pass


def read_image(path: str) -> np.ndarray:
    """한글 경로도 읽히게 imdecode 사용. BGR 또는 BGRA."""
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise TemplateError(t("이미지를 읽을 수 없음: {path}", path=path))
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


class _Template:
    def __init__(self, path: str):
        img = read_image(path)
        self.mask = None
        if img.shape[2] == 4:
            alpha = img[:, :, 3]
            if (alpha < 250).any():
                self.mask = (alpha >= 128).astype(np.uint8) * 255
            img = img[:, :, :3]
        self.bgr = img
        self.gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.mtime = os.path.getmtime(path)


BLANK_FALLBACK = 100   # 연속 검정 캡처 수(폴링 0.1초 기준 약 10초)


class MssVision(Vision):
    def __init__(self, image_root: str):
        self.image_root = os.path.abspath(image_root)
        self._local = threading.local()
        self._templates: Dict[str, _Template] = {}
        self._frame: Dict[Tuple, np.ndarray] = {}
        self._source = None          # '뒤에서 실행': 지금 대상 창 핸들을 돌려주는 함수
        self.source_blank = False    # 그 창이 창 단위 캡처를 지원 안 해 화면 캡처로 대신했는지
        self._blank_run = 0          # 연속으로 검정만 나온 횟수(화면 전환 중 잠깐 검정인 건 정상)

    def bind_window(self, source) -> None:
        self._source = source
        self.source_blank = False
        self._blank_run = 0
        self._frame.clear()

    # ------------------------------------------------------------ 캡처
    def _sct(self):
        s = getattr(self._local, "sct", None)
        if s is None:
            s = mss.mss()
            self._local.sct = s
        return s

    def screen_rect(self) -> Tuple[int, int, int, int]:
        if self._source is not None and not self.source_blank:
            from .win_capture import client_origin, client_size
            h = self._source()
            ox, oy = client_origin(h)
            w, hh = client_size(h)
            return (ox, oy, w, hh)
        m = self._sct().monitors[0]          # 모든 모니터를 합친 가상 화면
        return (m["left"], m["top"], m["width"], m["height"])

    def new_frame(self) -> None:
        self._frame.clear()

    def grab(self, region: Optional[Tuple[int, int, int, int]] = None) -> np.ndarray:
        """BGR 이미지. region 은 화면 절대좌표 (x, y, w, h). 화면 밖은 잘라냄."""
        sx, sy, sw, sh = self.screen_rect()
        if region is None:
            region = (sx, sy, sw, sh)
        x, y, w, h = (int(v) for v in region)
        x2, y2 = min(x + w, sx + sw), min(y + h, sy + sh)
        x, y = max(x, sx), max(y, sy)
        key = (x, y, x2, y2)
        if key in self._frame:
            return self._frame[key]
        if x2 <= x or y2 <= y:
            img = np.zeros((0, 0, 3), np.uint8)
        elif self._source is not None and not self.source_blank:
            full = self._frame.get("__window__")
            if full is None:
                from .win_capture import capture_window, looks_blank
                full = capture_window(self._source())
                if looks_blank(full):
                    # 화면 전환 중 잠깐 검정은 그대로 쓴다. 한참(약 10초) 계속 검정이면 창 단위 캡처를
                    # 지원 안 하는 창으로 보고 화면 캡처로 바꾼다
                    self._blank_run += 1
                    if self._blank_run >= BLANK_FALLBACK:
                        self.source_blank = True
                        return self.grab(region)
                else:
                    self._blank_run = 0
                self._frame["__window__"] = full
            img = full[y - sy:y2 - sy, x - sx:x2 - sx].copy()
        else:
            shot = self._sct().grab({"left": x, "top": y, "width": x2 - x, "height": y2 - y})
            img = np.asarray(shot)[:, :, :3].copy()
        self._frame[key] = img
        return img

    def _clip_origin(self, region) -> Tuple[int, int]:
        sx, sy, _, _ = self.screen_rect()
        if region is None:
            return sx, sy
        return max(int(region[0]), sx), max(int(region[1]), sy)

    # ------------------------------------------------------------ 템플릿
    def resolve(self, image: str) -> str:
        p = image if os.path.isabs(image) else os.path.join(self.image_root, image)
        return os.path.normpath(p)

    def template(self, image: str) -> _Template:
        path = self.resolve(image)
        if not os.path.exists(path):
            raise TemplateError(t("템플릿 파일 없음: {path}", path=path))
        tpl = self._templates.get(path)
        if tpl is None or tpl.mtime != os.path.getmtime(path):
            tpl = _Template(path)
            self._templates[path] = tpl
        return tpl

    # ------------------------------------------------------------ 매칭
    def match(self, image, region, opts) -> Match:
        tpl = self.template(image)
        screen = self.grab(region)
        ox, oy = self._clip_origin(region)
        conf = float(opts.get("confidence", 0.8))
        scales = _SCALES if opts.get("multiscale") else [1.0]
        if screen.size == 0:
            return Match(False, None, 0.0)
        sgray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

        best = (-1.0, None, 1.0)   # score, loc, scale
        for sc in scales:
            tg, mask = tpl.gray, tpl.mask
            if sc != 1.0:
                tg = cv2.resize(tg, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
                if mask is not None:
                    mask = cv2.resize(mask, (tg.shape[1], tg.shape[0]), interpolation=cv2.INTER_NEAREST)
            if tg.shape[0] > sgray.shape[0] or tg.shape[1] > sgray.shape[1]:
                continue
            if mask is not None:
                res = cv2.matchTemplate(sgray, tg, cv2.TM_CCORR_NORMED, mask=mask)
            else:
                res = cv2.matchTemplate(sgray, tg, cv2.TM_CCOEFF_NORMED)
            res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx > best[0]:
                best = (mx, loc, sc)
            if mx >= 0.99:
                break

        score, loc, sc = best
        if loc is None:
            return Match(False, None, 0.0)
        th, tw = int(round(tpl.gray.shape[0] * sc)), int(round(tpl.gray.shape[1] * sc))
        if score < conf:
            return Match(False, None, float(score))

        cc = opts.get("color_check")
        if cc is not None:
            patch = screen[loc[1]:loc[1] + th, loc[0]:loc[0] + tw]
            tb = tpl.bgr if sc == 1.0 else cv2.resize(tpl.bgr, (tw, th), interpolation=cv2.INTER_AREA)
            if patch.shape != tb.shape:
                return Match(False, None, float(score))
            diff = cv2.absdiff(patch, tb).astype(np.float32)
            if tpl.mask is not None:
                m = tpl.mask if sc == 1.0 else cv2.resize(tpl.mask, (tw, th), interpolation=cv2.INTER_NEAREST)
                diff = diff[m > 0]
            sim = 1.0 - float(diff.mean()) / 255.0
            if sim < float(cc):
                return Match(False, None, float(min(score, sim)))

        cx = ox + loc[0] + tw // 2
        cy = oy + loc[1] + th // 2
        return Match(True, (int(cx), int(cy)), float(score))

    def match_all(self, image, region, opts):
        """기준 이상으로 맞는 곳 모두(점수 높은 것부터 고르고 템플릿 크기만큼 겹치는 건 버림). 중심 화면좌표 목록."""
        t = self.template(image)
        screen = self.grab(region)
        if screen.size == 0:
            return []
        ox, oy = self._clip_origin(region)
        conf = float(opts.get("confidence", 0.8))
        cc = opts.get("color_check")
        sgray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tg, mask = t.gray, t.mask
        if tg.shape[0] > sgray.shape[0] or tg.shape[1] > sgray.shape[1]:
            return []
        if mask is not None:
            res = cv2.matchTemplate(sgray, tg, cv2.TM_CCORR_NORMED, mask=mask)
        else:
            res = cv2.matchTemplate(sgray, tg, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        th, tw = tg.shape[:2]
        ys, xs = np.where(res >= conf)
        cand = sorted(zip(res[ys, xs].tolist(), xs.tolist(), ys.tolist()), reverse=True)
        taken: list = []
        out = []
        for score, x, y in cand:
            if any(abs(x - a) < tw * 0.6 and abs(y - b) < th * 0.6 for a, b in taken):
                continue
            if cc is not None:
                patch = screen[y:y + th, x:x + tw]
                diff = cv2.absdiff(patch, t.bgr).astype(np.float32)
                if t.mask is not None:
                    diff = diff[t.mask > 0]
                if 1.0 - float(diff.mean()) / 255.0 < float(cc):
                    continue
            taken.append((x, y))
            out.append((int(ox + x + tw // 2), int(oy + y + th // 2)))
            if len(out) >= 200:
                break
        return out

    def pixel(self, x, y):
        img = self.grab((x, y, 1, 1))
        if img.size == 0:
            return (0, 0, 0)
        b, g, r = (int(v) for v in img[0, 0])
        return (r, g, b)

    def count_color(self, region, rgb, tolerance):
        img = self.grab(region)
        if img.size == 0:
            return 0, None
        target = np.array([rgb[2], rgb[1], rgb[0]], dtype=np.int16)     # BGR
        mask = (np.abs(img.astype(np.int16) - target) <= tolerance).all(axis=2)
        count = int(mask.sum())
        if not count:
            return 0, None
        ys, xs = np.nonzero(mask)
        ox, oy = self._clip_origin(region)
        return count, (int(ox + xs.mean()), int(oy + ys.mean()))

    def color_blob(self, region, rgb, tolerance):
        img = self.grab(region)
        if img.size == 0:
            return 0.0, None
        target = np.array([rgb[2], rgb[1], rgb[0]], dtype=np.int16)     # BGR
        mask = (np.abs(img.astype(np.int16) - target) <= tolerance).all(axis=2).astype(np.uint8) * 255
        if not mask.any():
            return 0.0, None
        # 덩어리 안쪽 구멍(말풍선 속 그림 등)을 메운 뒤 가장자리에서 가장 먼 점
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(mask)
        cv2.drawContours(filled, contours, -1, 255, -1)
        dist = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
        _, depth, _, loc = cv2.minMaxLoc(dist)
        ox, oy = self._clip_origin(region)
        return float(depth), (int(ox + loc[0]), int(oy + loc[1]))

    def read_text(self, region, opts):
        """영역의 숫자 읽기(숫자 조각 템플릿 매칭, engine/numread.py)."""
        from . import numread
        fonts = numread.load_fonts(self.resolve(opts.get("font") or numread.DEFAULT_FONT))
        conf = opts.get("confidence")
        return numread.read_text(self.grab(region), fonts,
                                 numread.DEFAULT_CONFIDENCE if conf is None else float(conf))

    def count_vivid(self, region, min_saturation, min_value, hues=None):
        img = self.grab(region)
        if img.size == 0:
            return 0, None
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = (hsv[:, :, 1] >= min_saturation) & (hsv[:, :, 2] >= min_value)
        if hues:
            h = hsv[:, :, 0]
            in_range = np.zeros_like(mask)
            for lo, hi in hues:
                in_range |= (h >= lo) & (h <= hi)
            mask &= in_range
        count = int(mask.sum())
        if not count:
            return 0, None
        ys, xs = np.nonzero(mask)
        ox, oy = self._clip_origin(region)
        return count, (int(ox + xs.mean()), int(oy + ys.mean()))

    def runner_up(self, image: str, region: Optional[Tuple[int, int, int, int]]
                  ) -> Tuple[float, Optional[Tuple[int, int]], float]:
        """가장 잘 맞는 곳을 빼고 두 번째로 잘 맞는 곳의 (형태 점수, 중심 화면좌표, 색 유사도).
        형태 점수가 confidence 이상이고 색 유사도도 color_check 이상이어야 실제로 헷갈린다."""
        t = self.template(image)
        screen = self.grab(region)
        if screen.size == 0 or t.gray.shape[0] > screen.shape[0] or t.gray.shape[1] > screen.shape[1]:
            return 0.0, None, 0.0
        sgray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        if t.mask is not None:
            res = cv2.matchTemplate(sgray, t.gray, cv2.TM_CCORR_NORMED, mask=t.mask)
        else:
            res = cv2.matchTemplate(sgray, t.gray, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)
        _, _, _, loc = cv2.minMaxLoc(res)
        h, w = t.gray.shape
        y0, x0 = max(0, loc[1] - h // 2), max(0, loc[0] - w // 2)
        res[y0:loc[1] + h // 2 + 1, x0:loc[0] + w // 2 + 1] = -1.0
        _, mx2, _, loc2 = cv2.minMaxLoc(res)
        if mx2 <= -1.0:
            return 0.0, None, 0.0
        patch = screen[loc2[1]:loc2[1] + h, loc2[0]:loc2[0] + w]
        diff = cv2.absdiff(patch, t.bgr).astype(np.float32)
        if t.mask is not None:
            diff = diff[t.mask > 0]
        color_sim = 1.0 - float(diff.mean()) / 255.0
        ox, oy = self._clip_origin(region)
        return float(mx2), (int(ox + loc2[0] + w // 2), int(oy + loc2[1] + h // 2)), color_sim

    def save_region(self, region: Tuple[int, int, int, int], path: str) -> str:
        """화면 일부를 PNG 로 저장(템플릿 만들기용). 한글 경로 지원."""
        self.new_frame()
        img = self.grab(region)
        if img.size == 0:
            raise ValueError(t("저장할 영역이 화면 밖임"))
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise ValueError(t("PNG 인코딩 실패"))
        buf.tofile(path)
        return path
