"""
실제 인식 백엔드(MssVision)를 가짜 화면(numpy 이미지)으로 시험. 화면 캡처는 쓰지 않는다.
"""
import cv2
import numpy as np
import pytest

from engine.win_vision import MssVision, TemplateError


class ScreenVision(MssVision):
    def __init__(self, screen, root):
        super().__init__(str(root))
        self.screen = screen

    def screen_rect(self):
        return (0, 0, self.screen.shape[1], self.screen.shape[0])

    def grab(self, region=None):
        if region is None:
            return self.screen
        x, y, w, h = region
        x2, y2 = min(x + w, self.screen.shape[1]), min(y + h, self.screen.shape[0])
        x, y = max(0, x), max(0, y)
        return self.screen[y:y2, x:x2]


def _noise_screen(w=800, h=600, seed=1):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    return cv2.GaussianBlur(img, (5, 5), 0)


def _save(path, img):
    ok, buf = cv2.imencode(".png", img)
    buf.tofile(str(path))
    return str(path)


@pytest.fixture
def setup(tmp_path):
    screen = _noise_screen()
    tpl = screen[200:240, 300:360].copy()           # 60x40, 중심 (330, 220)
    path = _save(tmp_path / "버튼.png", tpl)          # 한글 파일명
    return ScreenVision(screen, tmp_path), screen, tpl, path


def test_full_screen_match_center(setup):
    v, *_ = setup
    m = v.match("버튼.png", None, {"confidence": 0.8})
    assert m.found and m.pos == (330, 220) and m.score > 0.99


def test_region_offset_is_absolute(setup):
    v, *_ = setup
    m = v.match("버튼.png", (250, 150, 200, 200), {"confidence": 0.8})
    assert m.found and m.pos == (330, 220)


def test_region_without_target_reports_score(setup):
    v, *_ = setup
    m = v.match("버튼.png", (500, 400, 200, 150), {"confidence": 0.8})
    assert not m.found and 0 < m.score < 0.8


def test_region_partly_offscreen_is_clipped(setup):
    v, *_ = setup
    m = v.match("버튼.png", (-100, -100, 600, 500), {"confidence": 0.8})
    assert m.found and m.pos == (330, 220)


def test_multiscale_finds_scaled(setup, tmp_path):
    v, screen, tpl, _ = setup
    big = cv2.resize(tpl, None, fx=1.1, fy=1.1, interpolation=cv2.INTER_LINEAR)
    _save(tmp_path / "큰.png", big)
    assert not v.match("큰.png", None, {"confidence": 0.9}).found
    m = v.match("큰.png", None, {"confidence": 0.85, "multiscale": True})
    assert m.found and abs(m.pos[0] - 330) <= 3 and abs(m.pos[1] - 220) <= 3


def test_color_check_rejects_recolored(setup, tmp_path):
    v, screen, tpl, _ = setup
    tinted = np.clip(tpl.astype(int) + [0, 0, 90], 0, 255).astype(np.uint8)   # 빨강 강하게
    _save(tmp_path / "색.png", tinted)
    assert v.match("색.png", None, {"confidence": 0.8}).found          # 흑백으론 비슷
    assert not v.match("색.png", None, {"confidence": 0.8, "color_check": 0.9}).found


def test_alpha_mask_ignores_background(tmp_path):
    screen = _noise_screen(seed=2)
    icon = np.zeros((40, 40, 3), np.uint8)
    cv2.circle(icon, (20, 20), 12, (255, 255, 255), -1)
    screen[100:140, 500:540][icon[:, :, 0] > 0] = 255        # 배경 위에 원만 그림
    rgba = np.dstack([icon, np.where(icon[:, :, 0] > 0, 255, 0).astype(np.uint8)])
    _save(tmp_path / "원.png", rgba)
    v = ScreenVision(screen, tmp_path)
    m = v.match("원.png", None, {"confidence": 0.9})
    assert m.found and abs(m.pos[0] - 520) <= 1 and abs(m.pos[1] - 120) <= 1


def test_pixel_rgb_order(tmp_path):
    screen = np.zeros((10, 10, 3), np.uint8)
    screen[3, 4] = (10, 20, 30)          # BGR
    v = ScreenVision(screen, tmp_path)
    assert v.pixel(4, 3) == (30, 20, 10)


def test_missing_template(tmp_path):
    v = ScreenVision(_noise_screen(), tmp_path)
    with pytest.raises(TemplateError):
        v.match("없음.png", None, {})


def test_count_color_in_region(tmp_path):
    screen = np.zeros((100, 200, 3), np.uint8)
    screen[40:45, 50:60] = (230, 180, 0)          # BGR → RGB (0,180,230)
    v = ScreenVision(screen, tmp_path)
    n, c = v.count_color((0, 0, 200, 100), (0, 180, 230), 10)
    assert n == 50 and abs(c[0] - 54) <= 1 and abs(c[1] - 42) <= 1
    n, _ = v.count_color((100, 0, 100, 100), (0, 180, 230), 10)
    assert n == 0


def test_count_vivid(tmp_path):
    screen = np.full((60, 200, 3), 200, np.uint8)            # 회색 바탕
    screen[10:20, 10:30] = (209, 200, 39)                    # BGR 하늘색
    screen[30:40, 10:30] = (60, 60, 60)                      # 진한 회색 글자
    v = ScreenVision(screen, tmp_path)
    n, _ = v.count_vivid((0, 0, 200, 60), 110, 110)
    assert n == 200


def test_color_blob_picks_inside_thickest_bubble(tmp_path):
    screen = np.full((300, 400, 3), 90, np.uint8)
    cream = (211, 229, 236)                                   # BGR
    # 말풍선 두 개: 작은 것(가려짐)과 큰 것. 큰 것 안에는 다른 색 그림이 있음(구멍)
    cv2.rectangle(screen, (20, 20), (40, 40), cream, -1)
    cv2.rectangle(screen, (200, 100), (240, 140), cream, -1)
    cv2.circle(screen, (220, 120), 12, (30, 140, 40), -1)     # 안쪽 아이콘
    cv2.line(screen, (60, 200), (300, 200), cream, 2)          # 가는 선
    v = ScreenVision(screen, tmp_path)
    depth, pos = v.color_blob((0, 0, 400, 300), (236, 229, 211), 10)
    assert depth >= 18 and abs(pos[0] - 220) <= 3 and abs(pos[1] - 120) <= 3
    depth, pos = v.color_blob((50, 180, 300, 40), (236, 229, 211), 10)
    assert depth < 3
    assert v.color_blob((0, 250, 50, 50), (236, 229, 211), 10) == (0.0, None)


def test_check_template_self_and_runner_up(setup):
    from engine.templates import check_template
    v, screen, tpl, path = setup
    r = check_template(v, "버튼.png", None, samples=2, interval=0)
    assert r["self_match"] and r["found_at"] == [330, 220] and r["self_score"] > 0.99
    assert "warning" not in r and "animated" not in r
    # 같은 그림을 다른 곳에 하나 더 그리면 헷갈림 경고
    screen[400:440, 100:160] = tpl
    r2 = check_template(v, "버튼.png", None, samples=1, interval=0)
    assert "warning" in r2
