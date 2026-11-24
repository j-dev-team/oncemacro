"""
화면에서 고르기: 좌표·색 찍기, 영역 지정, 템플릿 잘라 저장.

- 화면 전체(모든 모니터)를 mss 로 찍어 그 위에 반투명 오버레이를 띄우고 클릭/드래그를 받는다.
- 고르는 동안 편집기·메인 창은 숨겨서 찍힌 화면에 안 나오게 한다.
- 결과 좌표는 매크로 기준으로 바꿔 돌려준다: window 가 있으면 그 창 클라이언트 기준, 없으면 화면 절대좌표.
- 템플릿은 image/<폴더>/<이름>.png 로 저장하고 engine.templates.check_template 로 검사 결과를 보여준다.
"""
from __future__ import annotations

import os
from typing import Callable, List, Optional, Tuple

from gui.v2.i18n import tr

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QInputDialog, QMessageBox, QWidget)


def grab_screen():
    """(BGR 이미지, (left, top)) — 가상 화면 전체."""
    import mss
    with mss.mss() as s:
        m = s.monitors[0]
        shot = s.grab(m)
        img = np.asarray(shot)[:, :, :3].copy()
        return img, (m["left"], m["top"])



class Concealed:
    """이 프로그램의 창들을 잠깐 안 보이게. hide() 를 쓰면 실행 중인 대화상자(exec_)가 닫혀 버려서
    다른 길로 숨긴다. with Concealed(widgets): ..."""

    def __init__(self, widgets):
        self.widgets = [w for w in widgets if w is not None and w.isVisible()]
        self.saved = []

    def __enter__(self):
        for w in self.widgets:
            self.saved.append((w, w.windowOpacity()))
            w.setWindowOpacity(0.0)
        QApplication.processEvents()
        return self

    def __exit__(self, *exc):
        for w, op in self.saved:
            try:
                w.setWindowOpacity(op or 1.0)
            except RuntimeError:
                pass
        QApplication.processEvents()
        return False

class Overlay(QDialog):
    """mode: 'point' | 'region'. exec_() 뒤 result_point / result_rect (화면 절대좌표)."""

    def __init__(self, img: np.ndarray, origin: Tuple[int, int], mode: str, hint: str,
                 frame_rect: Optional[Tuple[int, int, int, int]] = None):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.mode = mode
        self.hint = hint
        self.origin = origin
        self.frame_rect = frame_rect
        self.img = img
        h, w = img.shape[:2]
        rgb = np.ascontiguousarray(img[:, :, ::-1])
        self.qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self.pix = QPixmap.fromImage(self.qimg)
        self.setGeometry(origin[0], origin[1], w, h)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.start: Optional[QPoint] = None
        self.cur: Optional[QPoint] = None
        self.result_point: Optional[Tuple[int, int]] = None
        self.result_rect: Optional[Tuple[int, int, int, int]] = None

    def showEvent(self, e):
        super().showEvent(e)
        self.activateWindow()
        self.raise_()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.reject()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.reject()
            return
        self.start = e.pos()
        self.cur = e.pos()
        if self.mode == "point":
            p = e.pos()
            self.result_point = (p.x() + self.origin[0], p.y() + self.origin[1])
            self.accept()

    def mouseMoveEvent(self, e):
        self.cur = e.pos()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.mode != "region" or self.start is None:
            return
        r = QRect(self.start, e.pos()).normalized()
        if r.width() >= 3 and r.height() >= 3:
            self.result_rect = (r.x() + self.origin[0], r.y() + self.origin[1], r.width(), r.height())
            self.accept()
        else:
            self.start = None
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 70))
        if self.frame_rect:
            fx, fy, fw, fh = self.frame_rect
            p.setPen(QPen(QColor(0, 200, 255), 2, Qt.DashLine))
            p.drawRect(fx - self.origin[0], fy - self.origin[1], fw, fh)
        if self.mode == "region" and self.start is not None and self.cur is not None:
            r = QRect(self.start, self.cur).normalized()
            p.drawPixmap(r, self.pix, r)
            p.setPen(QPen(QColor(255, 60, 60), 2))
            p.drawRect(r)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r.bottomLeft() + QPoint(2, 16), f"{r.width()}×{r.height()}")
        if self.cur is not None:
            self._magnifier(p, self.cur)
        p.setFont(QFont("Malgun Gothic", 12, QFont.Bold))
        p.setPen(QColor(255, 255, 255))
        p.fillRect(QRect(20, 20, 760, 34), QColor(0, 0, 0, 170))
        p.drawText(QRect(30, 20, 750, 34), Qt.AlignVCenter, self.hint + "   " + tr("(Esc·오른쪽 클릭 = 취소)"))
        p.end()

    def _magnifier(self, p: QPainter, pos: QPoint):
        src = QRect(pos.x() - 10, pos.y() - 10, 21, 21)
        dst = QRect(pos.x() + 20, pos.y() + 20, 126, 126)
        if dst.right() > self.width():
            dst.moveRight(pos.x() - 20)
        if dst.bottom() > self.height():
            dst.moveBottom(pos.y() - 20)
        p.drawPixmap(dst, self.pix, src)
        p.setPen(QPen(QColor(255, 60, 60), 1))
        p.drawRect(dst)
        c = dst.center()
        p.drawLine(c.x() - 6, c.y(), c.x() + 6, c.y())
        p.drawLine(c.x(), c.y() - 6, c.x(), c.y() + 6)
        x, y = pos.x(), pos.y()
        if 0 <= y < self.img.shape[0] and 0 <= x < self.img.shape[1]:
            b, g, r = (int(v) for v in self.img[y, x])
            p.fillRect(QRect(dst.left(), dst.bottom() + 2, 126, 18), QColor(0, 0, 0, 190))
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRect(dst.left() + 4, dst.bottom() + 2, 122, 18), Qt.AlignVCenter,
                       f"({x + self.origin[0]},{y + self.origin[1]}) {r},{g},{b}")


class ScreenTools:
    """편집기가 쓰는 '화면에서 고르기'. window_title() 은 지금 매크로의 창 제목(없으면 None)."""

    def __init__(self, parent: QWidget, window_title: Callable[[], Optional[str]],
                 default_folder: Callable[[], str], hide_widgets: Callable[[], List[QWidget]]):
        self.parent = parent
        self.window_title = window_title
        self.default_folder = default_folder
        self.hide_widgets = hide_widgets
        self.last_screen = None

    # ------------------------------------------------------------ 좌표 기준
    def _origin(self) -> Optional[Tuple[int, int, Optional[Tuple[int, int, int, int]]]]:
        title = self.window_title()
        if not title:
            return 0, 0, None
        try:
            from engine.win_window import find_window
            info = find_window({"title": title})
        except Exception as e:
            QMessageBox.warning(self.parent, tr("화면에서 고르기"),
                                tr("매크로 창 '{title}' 을(를) 찾지 못했습니다.\n창을 띄운 뒤 다시 하세요.\n({e})").format(title=title, e=e))
            return None
        cx, cy, cw, ch = info.client
        return cx, cy, (cx, cy, cw, ch)

    def _activate_target(self):
        title = self.window_title()
        if not title:
            return
        try:
            from engine.win_window import Win32Window
            Win32Window({"title": title}).activate()
        except Exception:
            pass

    def _overlay(self, mode: str, hint: str):
        org = self._origin()
        if org is None:
            return None, None
        ox, oy, frame = org
        with Concealed(self.hide_widgets()):
            self._activate_target()
            self._wait(0.35)
            img, origin = grab_screen()
            self.last_screen = (img, origin)
            ov = Overlay(img, origin, mode, hint, frame)
            ok = ov.exec()
        if not ok:
            return None, None
        return ov, (ox, oy)

    @staticmethod
    def _wait(sec: float):
        loop_end = QTimer()
        loop_end.setSingleShot(True)
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        loop_end.timeout.connect(loop.quit)
        loop_end.start(int(sec * 1000))
        loop.exec()

    # ------------------------------------------------------------ 고르기
    def pick_point(self) -> Optional[List[int]]:
        ov, o = self._overlay("point", tr("클릭할 위치를 누르세요"))
        if ov is None or ov.result_point is None:
            return None
        return [ov.result_point[0] - o[0], ov.result_point[1] - o[1]]

    def pick_element(self) -> Optional[dict]:
        """누른 곳의 창 요소(버튼·입력칸 등) → {"name","type","target",...}. 이름 있는 요소가 없으면 {}."""
        org = self._origin()
        if org is None:
            return None
        title = self.window_title()
        hwnd = None
        if title:
            try:
                from engine.win_window import find_window
                hwnd = find_window({"title": title}).hwnd
            except Exception:
                hwnd = None
        with Concealed(self.hide_widgets()):
            self._activate_target()
            self._wait(0.35)
            img, origin = grab_screen()
            self.last_screen = (img, origin)
            ov = Overlay(img, origin, "point", tr("누를 버튼·입력칸을 누르세요"), org[2])
            ok = ov.exec()
            if not ok or ov.result_point is None:
                return None
            self._wait(0.15)                              # 덮개가 사라진 뒤 진짜 창에서 찾기
            try:
                from engine import win_uia
                return win_uia.element_at(ov.result_point[0], ov.result_point[1], hwnd) or {}
            except Exception:
                return {}

    def pick_color(self) -> Optional[Tuple[List[int], List[int]]]:
        ov, o = self._overlay("point", tr("색을 가져올 점을 누르세요"))
        if ov is None or ov.result_point is None:
            return None
        img, origin = self.last_screen
        x, y = ov.result_point[0] - origin[0], ov.result_point[1] - origin[1]
        b, g, r = (int(v) for v in img[y, x])
        return [ov.result_point[0] - o[0], ov.result_point[1] - o[1]], [r, g, b]

    def pick_region(self) -> Optional[List[int]]:
        ov, o = self._overlay("region", tr("영역을 끌어서 지정하세요"))
        if ov is None or ov.result_rect is None:
            return None
        x, y, w, h = ov.result_rect
        return [x - o[0], y - o[1], w, h]

    def capture_template(self) -> Optional[dict]:
        """영역을 잘라 템플릿으로 저장하고 검사. {path, recommended_confidence?, report} 를 돌려준다."""
        ov, o = self._overlay("region", tr("템플릿으로 쓸 부분을 끌어서 자르세요 (버튼 글자·아이콘만, 배경은 적게)"))
        if ov is None or ov.result_rect is None:
            return None
        ax, ay, w, h = ov.result_rect
        if w < 4 or h < 4:
            QMessageBox.warning(self.parent, tr("템플릿"), tr("너비·높이가 4px 이상이어야 합니다."))
            return None
        folder, ok = QInputDialog.getText(self.parent, tr("템플릿 저장"), tr("image/ 아래 폴더:"), text=self.default_folder())
        if not ok:
            return None
        name, ok = QInputDialog.getText(self.parent, tr("템플릿 저장"), tr("파일 이름(확장자 없이):"))
        name = (name or "").strip()
        folder = (folder or "").strip().strip("/").replace("\\", "/")
        bad = set('\\:*?"<>|')
        if not ok or not name or any(c in bad for c in name + folder) or "/" in name or ".." in folder:
            if ok:
                QMessageBox.warning(self.parent, tr("템플릿"), tr("이름·폴더에 쓸 수 없는 문자가 있습니다."))
            return None
        from engine.real import IMAGE_ROOT
        from engine.templates import check_template
        from engine.win_vision import MssVision
        rel = f"{folder}/{name}.png" if folder else f"{name}.png"
        path = os.path.join(IMAGE_ROOT, *rel.split("/"))
        if os.path.exists(path) and QMessageBox.question(
                self.parent, tr("템플릿"), tr("{rel} 이(가) 이미 있습니다. 덮어쓸까요?").format(rel=rel),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return None
        # 오버레이에 쓴 스크린샷에서 잘라 저장(지금 화면이 바뀌었을 수 있으므로)
        import cv2
        img, origin = self.last_screen
        crop = img[ay - origin[1]: ay - origin[1] + h, ax - origin[0]: ax - origin[0] + w]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ok_enc, buf = cv2.imencode(".png", crop)
        buf.tofile(path)
        # 검사는 실제 화면에서(반짝임 확인)
        org = self._origin()
        search = org[2] if org and org[2] else None
        with Concealed(self.hide_widgets()):
            self._activate_target()
            self._wait(0.3)
            chk = check_template(MssVision(IMAGE_ROOT), rel, search)
        lines = [tr("저장: image/{rel} ({w}×{h})").format(rel=rel, w=w, h=h),
                 tr("자기 자리에서 찾기: {res} (점수 {score})").format(
                     res=tr("성공") if chk['self_match'] else tr("실패"), score=chk['self_score'])]
        if chk.get("animated"):
            lines.append(chk["note"])
        if chk.get("warning"):
            lines.append(tr("주의: ") + chk["warning"])
        if not chk.get("animated") and not chk.get("warning") and chk["self_match"]:
            lines.append(tr("좋음: 바로 찾아지고 다른 곳과 헷갈리지 않습니다."))
        QMessageBox.information(self.parent, tr("템플릿 검사"), "\n".join(lines))
        out = {"path": rel, "report": chk}
        if chk.get("recommended_confidence"):
            out["recommended_confidence"] = chk["recommended_confidence"]
        return out
