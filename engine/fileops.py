"""파일·폴더 단계(Qt 없음).

지우기는 항상 휴지통으로(되살릴 수 있게). 같은 이름이 있을 때는 기본 '실패'이고, 단계마다
건너뛰기 / 번호 붙여 새로 / 바꾸기(원래 파일은 휴지통으로) 를 고른다.
드라이브 맨 위와 윈도우 시스템 폴더 자체는 통째로 지우거나 옮기지 않는다.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import sys
import time
import zipfile
from typing import Callable, List, Optional

from .i18n import current, row_item, t

ACTIONS = ("copy", "move", "rename", "delete", "mkdir", "list", "exists", "info", "read_text", "write_text",
           "zip", "unzip", "read_csv", "write_csv")
OVERWRITE = ("fail", "skip", "number", "replace")


class FileOpError(Exception):
    pass


# ---------------------------------------------------------------- 휴지통
def to_recycle_bin(path: str) -> None:
    """휴지통으로 보낸다(윈도우 SHFileOperation, FOF_ALLOWUNDO). 윈도우가 아니면 실패."""
    if sys.platform != "win32":
        raise FileOpError(t("휴지통은 윈도우에서만 됨"))
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", ctypes.c_uint), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0\0"
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r != 0 or op.fAnyOperationsAborted or os.path.exists(path):
        raise FileOpError(t("휴지통으로 보내지 못함: {path} (코드 {code})", path=path, code=r))


# ---------------------------------------------------------------- 지킴
def _protected(path: str) -> bool:
    p = os.path.normcase(os.path.abspath(path)).rstrip("\\/")
    drive, rest = os.path.splitdrive(p)
    if not rest.strip("\\/"):
        return True                                   # 드라이브 맨 위
    win = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows")).rstrip("\\/")
    names = [win] + [os.path.normcase(os.environ.get(k, "")).rstrip("\\/")
                     for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "USERPROFILE")]
    return p in [n for n in names if n]


def _guard(path: str, what: str) -> None:
    if _protected(path):
        raise FileOpError(t("이 폴더 자체는 {what} 수 없음(드라이브·시스템 폴더): {path}", what=what, path=path))


# ---------------------------------------------------------------- 도우미
def numbered(path: str) -> str:
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def _target(src: str, dst: str) -> str:
    """dst 가 있는 폴더면 그 안에 같은 이름으로."""
    if os.path.isdir(dst):
        return os.path.join(dst, os.path.basename(src))
    if dst.endswith(("\\", "/")):
        return os.path.join(dst, os.path.basename(src))
    return dst


def _resolve_clash(dst: str, mode: str, trash: Callable[[str], None]) -> Optional[str]:
    """같은 이름이 있을 때. 돌려줌: 쓸 경로, None 이면 건너뜀."""
    if not os.path.exists(dst):
        return dst
    if mode == "skip":
        return None
    if mode == "number":
        return numbered(dst)
    if mode == "replace":
        trash(dst)
        return dst
    raise FileOpError(t("같은 이름이 이미 있음: {path}", path=dst))


def list_files(folder: str, pattern: str = "*", sub: bool = False, kind: str = "files",
               sort: str = "name") -> List[str]:
    if not os.path.isdir(folder):
        raise FileOpError(t("폴더가 없음: {path}", path=folder))
    pats = [p.strip() for p in (pattern or "*").split(";") if p.strip()] or ["*"]
    out = []
    walker = os.walk(folder) if sub else [(folder, [d for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d))],
                                           [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))])]
    for root, dirs, files in walker:
        names = files if kind == "files" else dirs
        for n in names:
            if any(fnmatch.fnmatch(n.lower(), p.lower()) for p in pats):
                out.append(os.path.join(root, n))
    if sort == "modified":
        out.sort(key=lambda p: os.path.getmtime(p))
    elif sort == "newest":
        out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    else:
        out.sort(key=lambda p: p.lower())
    return out


def run(action: str, p: dict, trash: Callable[[str], None] = to_recycle_bin) -> dict:
    """파일 동작 하나. 돌려줌: {"value": 변수에 넣을 값, "changed": [(무엇, 원래, 새)] }."""
    a = action
    path = p.get("path", "")
    out = {"value": None, "changed": []}
    if a == "exists":
        out["value"] = os.path.exists(path)
        return out
    if a == "mkdir":
        os.makedirs(path, exist_ok=True)
        out["value"] = path
        out["changed"].append(("mkdir", path, ""))
        return out
    if a == "list":
        out["value"] = list_files(path, p.get("pattern", "*"), bool(p.get("sub")), p.get("kind", "files"),
                                  p.get("sort", "name"))
        return out
    if not os.path.exists(path):
        raise FileOpError(t("파일이 없음: {path}", path=path))
    if a == "info":
        st = os.stat(path)
        out["value"] = {"이름": os.path.basename(path), "확장자": os.path.splitext(path)[1].lstrip("."),
                        "폴더": os.path.dirname(os.path.abspath(path)), "크기": st.st_size,
                        "수정": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                        "폴더임": os.path.isdir(path)}
        v = out["value"]                       # 영어 이름으로도(name·ext·folder·size·modified·is_folder)
        v.update({"name": v["이름"], "ext": v["확장자"], "folder": v["폴더"], "size": v["크기"], "modified": v["수정"],
                  "is_folder": v["폴더임"]})
        return out
    if a == "read_text":
        with open(path, encoding=p.get("encoding") or "utf-8-sig", errors="replace") as fh:
            out["value"] = fh.read()
        return out
    if a == "delete":
        _guard(path, t("지울"))
        if p.get("permanent"):                      # 고급: 휴지통을 거치지 않고 영구 삭제(되살릴 수 없음)
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            out["changed"].append(("delete_permanent", path, t("영구 삭제")))
            return out
        trash(path)
        out["changed"].append(("delete", path, t("휴지통")))
        return out
    mode = p.get("overwrite", "fail")
    if a in ("copy", "move"):
        if a == "move":
            _guard(path, t("옮길"))
        to = p.get("to", "")
        if not to:
            raise FileOpError(t("'{k}' 필요", k="to"))
        want = os.path.abspath(_target(path, to))
        os.makedirs(os.path.dirname(want), exist_ok=True)            # 없는 폴더면 만든다
        dst = _resolve_clash(want, mode, trash)
        if dst is None:
            out["value"] = ""
            out["changed"].append(("skip", path, to))
            return out
        if a == "copy":
            if os.path.isdir(path):
                shutil.copytree(path, dst)
            else:
                shutil.copy2(path, dst)
        else:
            shutil.move(path, dst)
        out["value"] = dst
        out["changed"].append((a, path, dst))
        return out
    if a == "rename":
        _guard(path, t("이름 바꿀"))
        name = p.get("name", "")
        if not name or any(c in name for c in '\\/:*?"<>|'):
            raise FileOpError(t("새 이름이 비었거나 쓸 수 없는 글자가 있음: {name}", name=name))
        dst = _resolve_clash(os.path.join(os.path.dirname(os.path.abspath(path)), name), mode, trash)
        if dst is None:
            out["value"] = ""
            out["changed"].append(("skip", path, name))
            return out
        os.rename(path, dst)
        out["value"] = dst
        out["changed"].append(("rename", path, dst))
        return out
    if a == "zip":
        to = p.get("to") or (os.path.abspath(path).rstrip("\\/") + ".zip")
        dst = _resolve_clash(os.path.abspath(to), mode, trash)
        if dst is None:
            return out
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        fp = os.path.join(root, f)
                        z.write(fp, os.path.relpath(fp, os.path.dirname(os.path.abspath(path))))
            else:
                z.write(path, os.path.basename(path))
        out["value"] = dst
        out["changed"].append(("zip", path, dst))
        return out
    if a == "unzip":
        to = p.get("to") or os.path.splitext(os.path.abspath(path))[0]
        os.makedirs(to, exist_ok=True)
        root = os.path.abspath(to)
        with zipfile.ZipFile(path) as z:
            for m in z.namelist():
                target = os.path.abspath(os.path.join(root, m))
                if os.path.commonpath([root, target]) != root:
                    raise FileOpError(t("압축 파일 안에 폴더 밖으로 나가는 경로가 있음: {name}", name=m))
            for m in z.namelist():
                target = os.path.abspath(os.path.join(root, m))
                if m.endswith("/"):
                    os.makedirs(target, exist_ok=True)
                    continue
                dst = _resolve_clash(target, mode, trash)
                if dst is None:
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(m) as src_f, open(dst, "wb") as out_f:
                    shutil.copyfileobj(src_f, out_f)
        out["value"] = to
        out["changed"].append(("unzip", path, to))
        return out
    raise FileOpError(t("모르는 파일 동작 '{action}'", action=a))


def read_csv(path: str, header: bool = True, sep: str = ",", encoding: str = "") -> list:
    """CSV → 줄 목록. 제목 줄이 있으면 줄마다 {제목: 값, "1": 값, ..., "행"·"row": 번호}, 없으면 {"1": .., ...}."""
    import csv
    enc = encoding or "utf-8-sig"
    try:
        fh = open(path, encoding=enc, newline="")
        rows = list(csv.reader(fh, delimiter=sep or ","))
    except UnicodeDecodeError:
        fh.close()
        fh = open(path, encoding="cp949", newline="")          # 엑셀이 한글 윈도우에서 저장한 CSV
        rows = list(csv.reader(fh, delimiter=sep or ","))
    finally:
        try:
            fh.close()
        except Exception:
            pass
    head = [h.strip() for h in rows[0]] if header and rows else []
    out = []
    for n, r in enumerate(rows[1:] if header else rows, 1):
        if not any(c.strip() for c in r):
            continue
        o = row_item(n)
        for i, c in enumerate(r):
            o[str(i + 1)] = c
            if i < len(head) and head[i]:
                o[head[i]] = c
        out.append(o)
    return out


def write_csv(path: str, data, append: bool, mode: str, trash, sep: str = ",") -> dict:
    """줄 목록 → CSV(엑셀에서 한글이 안 깨지게 utf-8-sig). [{제목: 값}] 이면 제목 줄도 씀."""
    import csv
    from .office import table_grid
    grid = table_grid(data)
    if grid is None:
        raise FileOpError(t("CSV 로 쓸 표(줄 목록)가 아님"))
    out = {"value": path, "changed": []}
    if os.path.exists(path) and not append:
        dst = _resolve_clash(path, mode, trash)
        if dst is None:
            out["value"] = ""
            return out
        path = dst
    elif append and os.path.exists(path) and data and isinstance(data[0], dict):
        grid = grid[1:]                           # 이어 쓸 때는 제목 줄 빼고
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a" if append else "w", encoding="utf-8-sig" if not (append and os.path.exists(path)) else "utf-8",
              newline="") as fh:
        csv.writer(fh, delimiter=sep or ",").writerows(["" if c is None else c for c in r] for r in grid)
    out["value"] = path
    out["changed"].append(("append" if append else "write", path, ""))
    return out


def write_text(path: str, text: str, append: bool, mode: str, trash) -> dict:
    out = {"value": path, "changed": []}
    if os.path.exists(path) and not append:
        dst = _resolve_clash(path, mode, trash)
        if dst is None:
            out["value"] = ""
            return out
        path = dst
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "a" if append else "w", encoding="utf-8") as fh:
        fh.write(text)
    out["value"] = path
    out["changed"].append(("append" if append else "write", path, ""))
    return out
