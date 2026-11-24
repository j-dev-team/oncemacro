"""사무 기능 ③: 파일·폴더 단계와 파일 조건(임시 폴더, 휴지통은 가짜)."""
import os
import zipfile

import pytest

from engine import new_macro, validate_macro
from engine import fileops
from tests.engine.test_runner import World


def mk(p, text="x"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def run(steps, base, trash=None):
    w = World()
    r = w.runner(new_macro("m", steps))
    r.base_dir = str(base)
    trashed = []
    r.trash = trash or (lambda p: (trashed.append(p), os.remove(p) if os.path.isfile(p) else __import__("shutil").rmtree(p)))
    res = r.run()
    return res, w, trashed


def test_copy_move_rename_list_with_vars(tmp_path):
    mk(str(tmp_path / "받은편지" / "스캔001.pdf"))
    mk(str(tmp_path / "받은편지" / "스캔002.pdf"))
    mk(str(tmp_path / "받은편지" / "메모.txt"))
    res, w, _ = run([
        {"type": "date", "var": "달", "from": "2026-11-18", "format": "yyyy-MM"},
        {"type": "file", "action": "list", "path": "받은편지", "pattern": "*.pdf", "var": "목록"},
        {"type": "file", "action": "copy", "path": "받은편지/스캔001.pdf", "to": "보관/{달}/"},
        {"type": "file", "action": "move", "path": "받은편지/스캔002.pdf", "to": "보관/{달}/", "var": "옮긴곳"},
        {"type": "file", "action": "rename", "path": "보관/{달}/스캔001.pdf", "name": "{달}_거래처.pdf"},
        {"type": "file", "action": "exists", "path": "보관/{달}/{달}_거래처.pdf", "var": "있음"},
    ], tmp_path)
    assert res.status == "ok", res.error
    got = {e["var"]: e["value"] for e in w.events if e.get("event") == "set"}
    assert [os.path.basename(p) for p in got["목록"]] == ["스캔001.pdf", "스캔002.pdf"]
    assert os.path.exists(tmp_path / "보관" / "2026-11" / "2026-11_거래처.pdf")
    assert not os.path.exists(tmp_path / "받은편지" / "스캔002.pdf")
    assert got["있음"] is True
    files = [e for e in w.events if e.get("event") == "file"]
    assert [e["action"] for e in files] == ["copy", "move", "rename"]


def test_overwrite_modes(tmp_path):
    mk(str(tmp_path / "a.txt"), "새것")
    mk(str(tmp_path / "out" / "a.txt"), "옛것")
    res, _, _ = run([{"type": "file", "action": "copy", "path": "a.txt", "to": "out"}], tmp_path)
    assert res.status == "failed" and "같은 이름" in res.error["reason"]       # 기본: 실패
    res, _, _ = run([{"type": "file", "action": "copy", "path": "a.txt", "to": "out", "overwrite": "skip"}], tmp_path)
    assert res.status == "ok" and open(tmp_path / "out" / "a.txt", encoding="utf-8").read() == "옛것"
    res, _, _ = run([{"type": "file", "action": "copy", "path": "a.txt", "to": "out", "overwrite": "number"}], tmp_path)
    assert res.status == "ok" and os.path.exists(tmp_path / "out" / "a (2).txt")
    res, _, trashed = run([{"type": "file", "action": "copy", "path": "a.txt", "to": "out", "overwrite": "replace"}],
                          tmp_path)
    assert res.status == "ok" and trashed == [str(tmp_path / "out" / "a.txt")]      # 원래 것은 휴지통으로
    assert open(tmp_path / "out" / "a.txt", encoding="utf-8").read() == "새것"


def test_delete_goes_to_trash_and_protected_folders(tmp_path):
    mk(str(tmp_path / "지울것.txt"))
    res, w, trashed = run([{"type": "file", "action": "delete", "path": "지울것.txt"}], tmp_path)
    assert res.status == "ok" and trashed == [str(tmp_path / "지울것.txt")]
    res, _, trashed = run([{"type": "file", "action": "delete", "path": "C:\\"}], tmp_path)
    assert res.status == "failed" and trashed == []
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    res, _, trashed = run([{"type": "file", "action": "move", "path": windir, "to": str(tmp_path)}], tmp_path)
    assert res.status == "failed" and trashed == []


def test_text_read_write_info_zip(tmp_path):
    res, w, _ = run([
        {"type": "file", "action": "write_text", "path": "기록/로그.txt", "text": "첫 줄\n"},
        {"type": "file", "action": "write_text", "path": "기록/로그.txt", "text": "둘째 줄\n", "append": True},
        {"type": "file", "action": "read_text", "path": "기록/로그.txt", "var": "내용"},
        {"type": "file", "action": "info", "path": "기록/로그.txt", "var": "정보"},
        {"type": "file", "action": "zip", "path": "기록", "to": "기록.zip"},
        {"type": "file", "action": "unzip", "path": "기록.zip", "to": "풀림"},
    ], tmp_path)
    assert res.status == "ok", res.error
    got = {e["var"]: e["value"] for e in w.events if e.get("event") == "set"}
    assert got["내용"] == "첫 줄\n둘째 줄\n"
    assert got["정보"]["이름"] == "로그.txt" and got["정보"]["크기"] > 0
    assert os.path.exists(tmp_path / "풀림" / "기록" / "로그.txt")


def test_unzip_refuses_path_escape(tmp_path):
    zp = tmp_path / "나쁜.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("../밖.txt", "x")
    res, _, _ = run([{"type": "file", "action": "unzip", "path": str(zp), "to": "풀림"}], tmp_path)
    assert res.status == "failed" and not os.path.exists(tmp_path / "밖.txt")


def test_file_condition_waits_for_download(tmp_path):
    w = World()
    target = tmp_path / "보고서.xlsx"
    r = w.runner(new_macro("m", [{"type": "wait", "until": {"file": {"path": "보고서.xlsx"}}, "timeout": 10},
                                 {"type": "type_text", "text": "왔다"}]))
    r.base_dir = str(tmp_path)
    mk(str(target))           # 가짜 시계라 미리 만들어 둠: 조건이 파일을 보고 참이 되는지
    res = r.run()
    assert res.status == "ok"
    r2 = w.runner(new_macro("m", [{"type": "wait", "until": {"file": {"path": "없음.xlsx"}}, "timeout": 2}]))
    r2.base_dir = str(tmp_path)
    assert r2.run().status == "failed"


def test_validation(tmp_path):
    assert validate_macro(new_macro("m", [{"type": "file", "action": "copy", "path": "a", "to": "b"},
                                          {"type": "if", "cond": {"file": {"path": "a", "exists": False}}, "then": []}])) == []
    errs = validate_macro(new_macro("m", [{"type": "file", "action": "copy", "path": "a"},
                                          {"type": "file", "action": "rename", "path": "a"},
                                          {"type": "file", "action": "copy", "path": "a", "to": "b", "overwrite": "x"},
                                          {"type": "if", "cond": {"file": {}}, "then": []}]))
    assert len(errs) == 4, errs


def test_numbered_and_protected():
    assert fileops._protected("C:\\") and fileops._protected("D:\\")
    assert not fileops._protected(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp", "x.txt"))


def test_permanent_delete_is_advanced_and_logged(tmp_path):
    (tmp_path / "옛폴더").mkdir()
    (tmp_path / "옛폴더" / "a.txt").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    res, w, trashed = run([{"type": "file", "action": "delete", "path": "b.txt", "permanent": True},
                           {"type": "file", "action": "delete", "path": "옛폴더", "permanent": True}], tmp_path)
    assert res.status == "ok" and trashed == []                    # 휴지통을 거치지 않음
    assert not (tmp_path / "b.txt").exists() and not (tmp_path / "옛폴더").exists()
    assert [e["action"] for e in w.events if e.get("event") == "file"] == ["delete_permanent", "delete_permanent"]
    res, _, _ = run([{"type": "file", "action": "delete", "path": "C:\\", "permanent": True}], tmp_path)
    assert res.status == "failed"                                   # 드라이브·시스템 폴더 자체는 그대로 막음
    errs = validate_macro(new_macro("m", [{"type": "file", "action": "copy", "path": "a", "to": "b", "permanent": True}]))
    assert errs
