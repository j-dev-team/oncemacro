"""한글 자동화 설정 안내(11-19): 한글 보안 승인 모듈이 없는 컴퓨터에서 한글 단계가 숨은 확인 창에 막히지 않게.
- 모듈이 없으면 실행 전에 묻는다: [설정 방법 보기] / [확인 창을 보이게 해서 계속] / [취소]
- 내려받기·등록은 프로그램이 대신 하지 않는다(안내만).
출처: 한컴디벨로퍼 한글 오토메이션 개발 가이드 '보안 승인 모듈' https://developer.hancom.com/hwpautomation
"""
from __future__ import annotations

from gui.v2.i18n import tr

GUIDE_URL = "https://developer.hancom.com/hwpautomation"


def uses_hwp(macro: dict) -> bool:
    """매크로(하위 단계 포함)에 한글 단계가 있는지."""
    def walk(steps):
        for s in steps or []:
            if not isinstance(s, dict):
                continue
            if s.get("type") == "hwp":
                return True
            for k in ("steps", "then", "else"):
                if walk(s.get(k)):
                    return True
        return False
    return walk((macro or {}).get("steps"))


def ready() -> bool:
    try:
        from engine.office import hwp_security_ready
        return hwp_security_ready()
    except Exception:
        return True


def guide_text() -> str:
    return tr(
        "한글 자동화를 쓰려면 한 번 설정이 필요해요.\n"
        "한글은 다른 프로그램이 파일을 열 때마다 '접근을 허용할까요?' 창을 띄웁니다. 한컴이 무료로 주는 "
        "'보안 승인 모듈'을 한 번 등록해 두면 이 창 없이 돌아갑니다.\n\n"
        "1. 한컴디벨로퍼의 한글 오토메이션 개발 가이드를 엽니다: {url}\n"
        "   '보안 승인 모듈' 항목에서 '보안모듈(Automation).zip'을 내려받습니다.\n"
        "2. 압축을 풀고, 안의 DLL 파일을 지울 일 없는 폴더(예: 문서\\한글자동화)에 둡니다.\n"
        "3. 레지스트리 편집기에서 HKEY_CURRENT_USER\\Software\\HNC\\HwpAutomation\\Modules 에\n"
        "   문자열 값을 하나 만듭니다. 이름: FilePathCheckerModuleExample / 값: 그 DLL 파일의 전체 경로\n"
        "4. 이 프로그램을 다시 켜고, 설정 → 환경 점검에서 '한글 자동 승인'이 '됨'인지 봅니다.\n\n"
        "※ 한컴 안내: 개인의 비상업적 이용은 자유, 상업적 목적(판매용 솔루션 등)은 한컴의 별도 라이선스가 필요합니다.\n"
        "※ 설정하지 않아도, 실행할 때 '확인 창을 보이게 해서 계속'을 고르면 창이 뜰 때마다 직접 눌러 쓸 수 있어요."
    ).format(url=GUIDE_URL)


def show_guide(parent=None):
    from PySide6.QtWidgets import QApplication, QMessageBox
    box = QMessageBox(parent)
    box.setWindowTitle(tr("한글 자동화 설정"))
    box.setText(guide_text())
    copy = box.addButton(tr("주소 복사"), QMessageBox.ActionRole)
    box.addButton(tr("닫기"), QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is copy:
        QApplication.clipboard().setText(GUIDE_URL)


def ask_before_run(parent=None) -> bool:
    """한글 단계가 있는 매크로를 돌리기 전에(모듈이 없을 때만). True = 계속."""
    from PySide6.QtWidgets import QMessageBox
    from engine import office
    if ready() or office.HWP_ALLOW_PROMPT:
        return True
    box = QMessageBox(parent)
    box.setWindowTitle(tr("한글 자동화 설정"))
    box.setIcon(QMessageBox.Information)
    box.setText(tr("한글 자동화를 쓰려면 한 번 설정이 필요해요.\n\n"
                   "지금은 한글이 파일을 열 때마다 '접근 허용' 확인 창을 띄웁니다. 어떻게 할까요?"))
    guide = box.addButton(tr("설정 방법 보기"), QMessageBox.HelpRole)
    go = box.addButton(tr("확인 창을 보이게 해서 계속"), QMessageBox.AcceptRole)
    box.addButton(tr("취소"), QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is guide:
        show_guide(parent)
        return False
    if box.clickedButton() is go:
        office.HWP_ALLOW_PROMPT = True      # 이 프로그램이 켜져 있는 동안: 한글 창을 보이고 사람이 확인 창에 답함
        return True
    return False
