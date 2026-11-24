"""알림 보내기(Qt 없음). 매크로의 '알림' 단계와 멈춤 지킴이(감시)가 같이 쓴다.

통로:
- toast  : 윈도우 알림(오른쪽 아래). 창을 앞으로 가져오지 않는다.
- sound  : 짧은 소리
- log    : <자료 폴더>/logs/notify/notify.jsonl 에 한 줄(항상 같이 남김)
- webhook: 메신저 웹훅 주소로 글 보내기(슬랙·디스코드·팀즈 등이 받는 {"text": ..., "content": ...})

웹훅 주소는 단계의 url, 없으면 <자료 폴더>/settings/notify.json 의 {"webhook": "..."} 를 쓴다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Iterable, List, Optional

from .i18n import t

CHANNELS = ("toast", "sound", "log", "webhook")


def _root() -> str:
    try:
        from .real import PROJECT_ROOT
        return PROJECT_ROOT
    except Exception:
        return os.getcwd()


def load_config(root: Optional[str] = None) -> dict:
    p = os.path.join(root or _root(), "settings", "notify.json")
    try:
        with open(p, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def write_log(title: str, message: str, level: str = "info", source: str = "", root: Optional[str] = None) -> str:
    d = os.path.join(root or _root(), "logs", "notify")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "notify.jsonl")
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "level": level, "source": source,
                             "title": title, "message": message}, ensure_ascii=False) + "\n")
    return p


def toast(title: str, message: str) -> None:
    """윈도우 알림. PowerShell 의 윈도우 알림 기능을 창 없이 부른다(설치 필요 없음)."""
    if sys.platform != "win32":
        raise OSError(t("윈도우 알림은 윈도우에서만 됨"))

    def esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;").replace("'", "&apos;"))
    xml = f"<toast><visual><binding template='ToastGeneric'><text>{esc(title)}</text><text>{esc(message)}</text>" \
          f"</binding></visual></toast>"
    app = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null;"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null;"
          "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml($env:MACRO_TOAST_XML);"
          f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}')"
          ".Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    env = dict(os.environ, MACRO_TOAST_XML=xml)
    subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env,
                     creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_TOAST_APP = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"


def toast_delivered(title: str, since: float, message: str = "") -> Optional[bool]:
    """윈도우 알림이 알림 센터에 실제로 들어왔는지(11-19: 사람 없이 '알림이 떴나' 확인용).
    since(time.time()) 뒤에 같은 제목(과 글)이 들어왔으면 True, 없으면 False, 기록을 못 읽으면 None.
    알림 센터 기록 파일을 복사해서 읽기만 한다(원본은 건드리지 않음). 방해 금지 중이면 들어와도 화면엔 안 뜰 수 있음."""
    if sys.platform != "win32":
        return None
    import shutil
    import sqlite3
    import tempfile
    src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Notifications")
    if not os.path.exists(os.path.join(src, "wpndatabase.db")):
        return None
    tmp = tempfile.mkdtemp(prefix="macro_wpn_")
    try:
        for f in ("wpndatabase.db", "wpndatabase.db-wal", "wpndatabase.db-shm"):
            fp = os.path.join(src, f)
            if os.path.exists(fp):
                shutil.copy2(fp, tmp)
        con = sqlite3.connect(os.path.join(tmp, "wpndatabase.db"))
        try:
            ft = int((since + 11644473600) * 10_000_000) - 50_000_000     # 1601년 기준 100ns(5초 여유)
            rows = con.execute("SELECT n.Payload FROM Notification n JOIN NotificationHandler h ON h.RecordId = n.HandlerId "
                               "WHERE h.PrimaryId = ? AND n.ArrivalTime >= ?", (_TOAST_APP, ft)).fetchall()
        finally:
            con.close()
        for (payload,) in rows:
            text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload or "")
            if title in text and (not message or message[:40] in text):
                return True
        return False
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _check_toast_later(title: str, message: str, since: float, root: Optional[str], wait: float = 3.0):
    """보낸 뒤 몇 초 있다 알림 센터를 보고 결과를 notify.jsonl 에 한 줄 더(AI·기록에서 '떴나'를 알 수 있게)."""
    import threading

    def run():
        time.sleep(wait)
        ok = toast_delivered(title, since, message)
        try:
            d = os.path.join(root or _root(), "logs", "notify")
            with open(os.path.join(d, "notify.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": "toast_check", "title": title,
                                     "delivered": ok}, ensure_ascii=False) + "\n")
        except OSError:
            pass
    threading.Thread(target=run, daemon=True).start()


def sound(level: str = "info") -> None:
    if sys.platform == "win32":
        import winsound
        winsound.MessageBeep(0x30 if level in ("warning", "error") else 0x40)


def webhook(url: str, title: str, message: str, timeout: float = 10.0) -> None:
    import urllib.request
    if not url.lower().startswith(("https://", "http://")):
        raise OSError(t("웹훅 주소는 https:// 로 시작해야 함"))
    text = f"{title}\n{message}" if title else message
    body = json.dumps({"text": text, "content": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8",
                                                          "User-Agent": "OnceMacro-notify"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status >= 300:
            raise OSError(t("웹훅 응답 {code}", code=r.status))


def send(title: str, message: str, channels: Iterable[str] = ("toast",), level: str = "info", url: str = "",
         source: str = "", root: Optional[str] = None) -> List[str]:
    """알림 보내기. 돌려줌: 실패한 통로 설명 목록(빈 목록 = 다 됨). 기록 파일에는 항상 남긴다."""
    errors: List[str] = []
    try:
        write_log(title, message, level, source, root)
    except OSError as e:
        errors.append(f"log: {e}")
    for ch in channels:
        try:
            if ch == "toast":
                t0 = time.time()
                toast(title, message)
                if os.environ.get("MACRO_NO_TOAST_CHECK") != "1":
                    _check_toast_later(title, message, t0, root)
            elif ch == "sound":
                sound(level)
            elif ch == "webhook":
                u = url or load_config(root).get("webhook", "")
                if not u:
                    raise OSError(t("웹훅 주소가 없음(단계의 주소나 settings/notify.json 의 webhook)"))
                webhook(u, title, message)
        except Exception as e:
            errors.append(f"{ch}: {e}")
    return errors
