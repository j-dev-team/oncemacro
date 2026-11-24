"""
화면 숫자 읽기 (read_number 스텝의 실제 구현, Qt 없음).

방식: 숫자 전용 템플릿 매칭. 글꼴 폴더에 글자 조각 그림(0~9, 쉼표, 빗금, 점)을 두고,
영역 위로 조각들을 밀어 가며 맞는 곳을 찾아 왼쪽부터 이어 붙인다.

- 글꼴 폴더: image/ 아래 폴더 하나 = 글꼴 하나. 파일 이름은 `글자[_변형].png`
  (예: `3.png`, `3_2.png`, `쉼표.png`, `빗금_2.png`, `점.png`). 같은 글자를 여러 장 둘 수 있다
  (게임이 글자를 반 픽셀씩 밀어 그려서 모양이 조금씩 다를 때).
  조각은 사방 1px 여백을 포함해 자른다(읽을 때 여백은 떼고 쓴다).
- 폴더 안에 하위 폴더가 있으면 하위 폴더 하나하나가 글꼴이고, 가장 잘 맞는 글꼴의 결과를 쓴다.
- 비교에 쓰는 값은 '가장 어두운 채널'(B·G·R 중 최솟값). 흰 글자는 밝게, 금색·빨간 글자는
  둘 다 검은 실루엣으로 나와 글자 색·배경 색이 달라도 같은 조각으로 읽힌다.
- 글자를 빠뜨리고 일부만 읽는 것을 막는 검사: 쉼표 자리(세 자리마다), 0 으로 시작하는 수,
  읽은 줄 바로 옆에 남은 글자 무늬 → 어긋나면 글자열 끝에 '?' 를 붙이거나 해석(parse_number)이 실패한다.
- 작은 글꼴(조각 높이 16px 미만)은 3배로 키워서 비교한다(반 픽셀 어긋남 흡수).
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from .i18n import t

DEFAULT_FONT = "fonts/numbers"      # read_number 에 font 를 안 쓰면 이 폴더(이미지 폴더 기준)
DEFAULT_CONFIDENCE = 0.88                # 실측: 제대로 읽힌 글자는 0.92 이상, 다른 크기 글꼴에 헛맞은 건 0.86 이하
SMALL_HEIGHT = 16                        # 이보다 낮은 글꼴은 키워서 비교
SMALL_SCALE = 3
NAMES = {"쉼표": ",", "빗금": "/", "점": ".", "comma": ",", "slash": "/", "dot": "."}     # ko-key (글꼴 폴더 파일 이름; 영어 이름도 됨)
_PUNCT = ",/."
CONFIG_NAME = "설정.json"
PUNCT_CONFIDENCE = 0.5                   # 기호는 숫자 사이 틈에서만 보므로 기준을 낮춘다


class FontError(FileNotFoundError):
    pass


def feature(bgr: np.ndarray) -> np.ndarray:
    """비교용 흑백: 채널 최솟값."""
    if bgr.ndim == 2:
        return bgr
    return bgr[:, :, :3].min(axis=2)


def _read(path: str) -> np.ndarray:
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FontError(t("숫자 조각을 읽을 수 없음: {path}", path=path))
    return img


def _up(gray: np.ndarray, scale: int) -> np.ndarray:
    if scale == 1:
        return gray
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


class Font:
    """글꼴 하나: (글자, 조각) 목록."""

    def __init__(self, folder: str):
        self.folder = folder
        raw: List[Tuple[str, np.ndarray]] = []
        for fn in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(fn)
            if ext.lower() != ".png":
                continue
            key = stem.split("_")[0]
            ch = NAMES.get(key, key)
            if len(ch) != 1 or not (ch.isdigit() or ch in _PUNCT):
                continue
            raw.append((ch, feature(_read(os.path.join(folder, fn)))))
        if not any(ch.isdigit() for ch, _ in raw):
            raise FontError(t("숫자 조각(0.png ~ 9.png)이 없음: {folder}", folder=folder))
        digit_h = max(g.shape[0] for ch, g in raw if ch.isdigit()) - 2
        self.scale = SMALL_SCALE if digit_h < SMALL_HEIGHT else 1
        k = self.scale
        self.glyphs: List[Tuple[str, np.ndarray]] = []
        for ch, g in raw:
            if g.shape[0] < 3 or g.shape[1] < 3:
                continue
            self.glyphs.append((ch, _up(g, k)[k:-k, k:-k].copy()))     # 여백 1px 떼기
        self.digit_w = int(np.median([g.shape[1] for ch, g in self.glyphs if ch.isdigit()]))
        self.digit_h = int(np.median([g.shape[0] for ch, g in self.glyphs if ch.isdigit()]))
        # 글자가 배경보다 밝은 글꼴인지(흰 글자) 어두운 글꼴인지(금색·빨간 글자의 실루엣)
        dg = [g.astype(np.float32) for ch, g in raw if ch.isdigit()]
        edge = np.mean([np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]]).mean() for g in dg])
        self.bright = bool(np.mean([g[1:-1, 1:-1].mean() for g in dg]) > edge)
        # 줄 옆 검사 띠(숫자 너비 대비 [건너뛸 폭, 볼 폭]). 글자 옆에 아이콘이 바짝 붙는 글꼴은
        # 폴더의 설정.json {"옆검사": [0.07, 0.1]} 로 좁힌다
        self.guard = (0.2, 0.28)
        from .fsnames import pick
        cfg = pick(folder, CONFIG_NAME)                    # 11-24: 설정.json 이 없으면 settings.json
        if os.path.exists(cfg):
            with open(cfg, "r", encoding="utf-8") as fh:
                cfgd = json.load(fh)
                g = cfgd.get("옆검사") or cfgd.get("side_guard")
            if g:
                self.guard = (float(g[0]), float(g[1]))
        self.stamp = _stamp(folder)


def _stamp(folder: str):
    try:
        return tuple(sorted((fn, os.path.getmtime(os.path.join(folder, fn))) for fn in os.listdir(folder)))
    except OSError:
        return None


_fonts: Dict[str, Font] = {}


def load_fonts(folder: str) -> List[Font]:
    """폴더(글꼴 하나) 또는 그 하위 폴더들(글꼴 여럿). 파일이 바뀌면 다시 읽는다."""
    if not os.path.isdir(folder):
        raise FontError(t("숫자 글꼴 폴더 없음: {folder}", folder=folder))
    subs = [os.path.join(folder, d) for d in sorted(os.listdir(folder))
            if os.path.isdir(os.path.join(folder, d))]
    out = []
    for d in (subs or [folder]):
        f = _fonts.get(d)
        if f is None or f.stamp != _stamp(d):
            f = Font(d)
            _fonts[d] = f
        out.append(f)
    return out


# ---------------------------------------------------------------- 읽기

def _hits(img: np.ndarray, font: Font, conf: float, digits: bool = True
          ) -> List[Tuple[float, int, int, int, int, str]]:
    """기준 이상으로 맞는 곳 전부: (점수, x, y, 너비, 높이, 글자). digits=False 면 기호 조각만."""
    out = []
    if img.size == 0:
        return out
    ih, iw = img.shape
    total, sq = cv2.integral2(img, sdepth=cv2.CV_64F)      # 후보 자리의 명암(표준편차)을 바로 구하려고
    for ch, g in font.glyphs:
        if ch.isdigit() != digits:
            continue
        gh, gw = g.shape
        if gh > ih or gw > iw:
            continue
        res = cv2.matchTemplate(img, g, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.nonzero(res >= conf)                   # NaN·음수는 여기서 걸러진다
        if len(ys) == 0:
            continue
        sc = res[ys, xs]
        keep = np.isfinite(sc) & (sc <= 1.01)
        # 밋밋한 곳(무늬 없는 배경)은 점수가 헛나오므로 뺀다
        n = float(gw * gh)
        s1 = total[ys + gh, xs + gw] - total[ys, xs + gw] - total[ys + gh, xs] + total[ys, xs]
        s2 = sq[ys + gh, xs + gw] - sq[ys, xs + gw] - sq[ys + gh, xs] + sq[ys, xs]
        keep &= (s2 / n - (s1 / n) ** 2) >= 144.0
        ys, xs, sc = ys[keep], xs[keep], sc[keep]
        if len(ys) == 0:
            continue
        # 주변(3x3)보다 높은 봉우리만
        grid = np.zeros((res.shape[0] + 2, res.shape[1] + 2), np.float32)
        grid[ys + 1, xs + 1] = sc
        peak = np.ones(len(ys), bool)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                peak &= sc >= grid[ys + dy, xs + dx]
        for x, y, v in zip(xs[peak].tolist(), ys[peak].tolist(), sc[peak].tolist()):
            out.append((float(v), x, y, gw, gh, ch))
    return out


def _overlap(a, b) -> float:
    """가로로 겹치는 비율(좁은 쪽 기준)."""
    lo, hi = max(a[1], b[1]), min(a[1] + a[3], b[1] + b[3])
    return max(0, hi - lo) / float(min(a[3], b[3]))


def _read_font(img: np.ndarray, font: Font, conf: float) -> Tuple[str, float, float]:
    """글자들이 빈틈없이 이어지는 가장 좋은 줄 하나를 고른다(글자 점수×너비 합이 최대).
    좁은 조각(1·쉼표)이 다른 글자 일부에 헛맞아도, 제자리 글자와 겹치면 줄에 못 끼므로 걸러진다."""
    k = font.scale
    big = _up(img, k)
    hits = _hits(big, font, conf)
    if not hits:
        return "", 0.0, 0.0
    row_tol = font.digit_h * 0.35
    # 기호(쉼표·빗금)는 숫자가 있는 줄 둘레에서만 찾는다(조각이 작아 아무 데나 맞으므로)
    top = max(0, min(h[2] for h in hits) - font.digit_h)
    left = max(0, min(h[1] for h in hits) - 2 * font.digit_w)
    band = big[top:max(h[2] + h[4] for h in hits) + font.digit_h,
               left:max(h[1] + h[3] for h in hits) + 2 * font.digit_w]
    for sc, x, y, w, h_, ch in _hits(band, font, min(conf, PUNCT_CONFIDENCE), digits=False):
        if any(abs(y + top - d[2]) <= row_tol and abs(x + left - d[1]) <= 3 * font.digit_w for d in hits[:400]):
            hits.append((sc, x + left, y + top, w, h_, ch))
    hits.sort(key=lambda h: (h[1], h[2]))
    reach = max(h[3] for h in hits) + font.digit_w
    back = max(1.0, font.digit_w * 0.2)        # 앞 글자와 겹쳐도 되는 폭
    ahead = max(1.0, font.digit_w * 0.3)       # 앞 글자와 떨어져도 되는 폭
    n = len(hits)
    total = [0.0] * n
    prev: List[Optional[int]] = [None] * n
    for i, h in enumerate(hits):
        base = (h[0] - 0.4) * h[3]
        best, arg = 0.0, None
        for j in range(i - 1, -1, -1):
            o = hits[j]
            if o[1] < h[1] - reach:
                break
            d = h[1] - (o[1] + o[3])
            if -back <= d <= ahead and o[1] < h[1] and abs(o[2] - h[2]) <= row_tol                     and (o[5].isdigit() or h[5].isdigit()) and total[j] - abs(d) * 0.6 > best:
                best, arg = total[j] - abs(d) * 0.6, j      # 겹치거나 벌어진 만큼 감점
        total[i], prev[i] = base + best, arg
    i = max(range(n), key=lambda q: total[q])
    weight = total[i] / float(font.digit_w)         # 글꼴끼리 비교할 값(대략 글자 수 × 점수)
    chain = []
    while i is not None:
        chain.append(hits[i])
        i = prev[i]
    chain.reverse()
    while chain and not chain[0][5].isdigit():      # 줄 앞뒤의 기호는 버림
        chain.pop(0)
    while chain and not chain[-1][5].isdigit():
        chain.pop()
    if not chain:
        return "", 0.0, 0.0
    text = "".join(h[5] for h in chain)
    score = min(h[0] for h in chain if h[5].isdigit())
    # 줄 바로 옆에 못 끼운 숫자가 있으면 글자를 빠뜨렸을 수 있다 → '?' 를 붙여 해석이 실패하게
    x0, x1, y = chain[0][1], chain[-1][1] + chain[-1][3], chain[0][2]
    for h in hits:
        if not h[5].isdigit() or abs(h[2] - y) > row_tol:
            continue
        if any(_overlap(h, o) >= 0.45 for o in chain):
            continue
        if x0 - 2.0 * font.digit_w <= h[1] + h[3] / 2.0 <= x1 + 2.0 * font.digit_w:
            text += "?"
            break
    else:
        # 줄 양옆에 바로 붙어서 글자 색(밝기) 픽셀이 남아 있어도 빠뜨린 것으로 본다
        h = chain[0][4]
        skip = max(1, int(round(font.digit_w * font.guard[0])))    # 글자 자신의 번진 가장자리는 건너뜀
        bw = max(2, int(round(font.digit_w * font.guard[1])))
        inside = big[y:y + h, x0:x1]
        lo, hi = float(np.percentile(inside, 5)), float(np.percentile(inside, 95))
        for side in (big[y:y + h, max(0, x0 - skip - bw):max(0, x0 - skip)],
                     big[y:y + h, x1 + skip:x1 + skip + bw]):
            if side.shape[1] < bw:          # 영역 가장자리에 붙어 있으면 잘린 숫자일 수 있다
                text += "?"
                break
            if hi - lo < 30:
                continue
            ink = side >= lo + 0.7 * (hi - lo) if font.bright else side <= hi - 0.7 * (hi - lo)
            if float(ink.mean()) >= 0.08:
                text += "?"
                break
    return text, score, weight


def read_text(bgr: np.ndarray, fonts: List[Font], confidence: float = DEFAULT_CONFIDENCE) -> Tuple[str, float]:
    """그림에서 숫자·기호 글자열을 읽는다. (글자열, 가장 낮은 글자 점수). 못 읽으면 ("", 0)."""
    if bgr is None or bgr.size == 0:
        return "", 0.0
    img = np.ascontiguousarray(feature(bgr))
    best, best_w = ("", 0.0), 0.0
    for f in fonts:
        text, score, weight = _read_font(img, f, confidence)
        if text and weight > best_w:
            best, best_w = (text, score), weight
    return best


# ---------------------------------------------------------------- 해석

_NUM = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d+$")


def parse_number(text: str, part: str = "first") -> Optional[int]:
    """'3,695/9,937' → 3695 (part='second' 면 9937). '11,500,000' → 11500000. 형식이 안 맞으면 None.
    쉼표 자리(세 자리마다)가 틀리면 글자를 빠뜨린 것으로 보고 None."""
    if "?" in (text or ""):               # 글자를 빠뜨렸을 수 있다는 표시 → 믿지 않는다
        return None
    tokens = [t for t in (text or "").split(" ") if any(c.isdigit() for c in t)]
    if not tokens:
        return None
    tok = max(tokens, key=lambda t: sum(c.isdigit() for c in t))    # 여러 덩어리면 숫자가 가장 많은 것
    parts = tok.split("/")
    if len(parts) > 2:
        return None
    if part == "second":
        if len(parts) != 2:
            return None
        s = parts[1]
    else:
        s = parts[0]
    if not _NUM.match(s) or (len(s) > 1 and s[0] == "0"):     # 0 으로 시작하면 앞 글자를 빠뜨린 것
        return None
    return int(s.replace(",", ""))
