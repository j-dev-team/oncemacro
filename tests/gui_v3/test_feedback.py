"""문제·의견 보내기: 사람이 고른 것만 묶음에 넣음(화면 사진·매크로는 기본 빼기)."""
import json
import os
import zipfile

from gui.v3.feedback import make_report


def test_report_has_defaults_and_no_private_files(tmp_path):
    (tmp_path / "logs" / "runs").mkdir(parents=True)
    (tmp_path / "logs" / "runs" / "20261124_000000_m.jsonl").write_text(
        json.dumps({"event": "run_end", "depth": 0, "result": {"status": "failed", "duration": 3,
                                                               "error": {"reason": "창 없음", "path": "steps[1]"}}}) + "\n",
        encoding="utf-8")
    ev = tmp_path / "logs" / "selfheal" / "evidence" / "20261124_000000_m"
    ev.mkdir(parents=True)
    (ev / "info.json").write_text("{}", encoding="utf-8")
    (ev / "screen.png").write_bytes(b"png")
    (tmp_path / "macros_v2").mkdir()
    (tmp_path / "macros_v2" / "내것.json").write_text("{}", encoding="utf-8")
    p = make_report(str(tmp_path), note="멈춤")
    names = zipfile.ZipFile(p).namelist()
    assert "info.json" in names and "recent_runs.json" in names
    assert not any(n.endswith(".png") for n in names) and not any(n.startswith("macros/") for n in names)
    runs = json.loads(zipfile.ZipFile(p).read("recent_runs.json"))
    assert runs[0]["status"] == "failed" and runs[0]["where"] == "steps[1]"
    p2 = make_report(str(tmp_path), include_screens=True, include_macros=True)
    names2 = zipfile.ZipFile(p2).namelist()
    assert any(n.endswith("screen.png") for n in names2) and "macros/내것.json" in names2
    assert os.path.dirname(p) == str(tmp_path / "logs" / "feedback")
