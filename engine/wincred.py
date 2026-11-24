"""윈도우 자격 증명 관리자에 비밀번호 보관(Qt 없음, 추가 부품 없음).

매크로 파일·설정 파일·실행 기록에는 비밀번호를 절대 남기지 않는다. 사용자가 설정 화면에서 직접 넣은 것만 여기 둔다.
이름: "MacroManager/mail/<계정 이름>"
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

PREFIX = "MacroManager/mail/"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


if sys.platform == "win32":
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _adv = ctypes.windll.advapi32
    _adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    _adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    _adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _adv.CredFree.argtypes = [ctypes.c_void_p]


def save(name: str, user: str, password: str) -> None:
    if sys.platform != "win32":
        raise OSError("windows only")
    blob = password.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))
    c = CREDENTIAL()
    c.Type = CRED_TYPE_GENERIC
    c.TargetName = PREFIX + name
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    c.UserName = user
    if not _adv.CredWriteW(ctypes.byref(c), 0):
        raise OSError(ctypes.WinError())


def load(name: str) -> Optional[str]:
    if sys.platform != "win32":
        return None
    p = ctypes.POINTER(CREDENTIAL)()
    if not _adv.CredReadW(PREFIX + name, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        return None
    try:
        n = p.contents.CredentialBlobSize
        return ctypes.string_at(p.contents.CredentialBlob, n).decode("utf-16-le")
    finally:
        _adv.CredFree(p)


def delete(name: str) -> bool:
    if sys.platform != "win32":
        return False
    return bool(_adv.CredDeleteW(PREFIX + name, CRED_TYPE_GENERIC, 0))
