"""시험 공통: 알림 센터 확인 스레드는 끔(진짜 알림 기록을 읽지 않게)."""
import os

os.environ.setdefault("MACRO_NO_TOAST_CHECK", "1")
