"""한글 보안 승인 모듈이 없을 때: 숨은 확인 창에 2분 막히지 않고 바로 '설정 필요'로 실패(사람이 고르면 창을 보이고 계속)."""
import time

import pytest

from engine import office


def test_no_module_fails_fast_without_starting_hwp(monkeypatch):
    monkeypatch.setattr(office, "hwp_security_ready", lambda: False)
    monkeypatch.setattr(office, "HWP_ALLOW_PROMPT", False)
    started = []
    monkeypatch.setattr(office, "_com", lambda: started.append(1) or (_ for _ in ()).throw(AssertionError("켜면 안 됨")))
    app = office.HwpApp()
    t0 = time.time()
    with pytest.raises(office.OfficeError) as e:
        app._ensure()
    assert "설정이 필요" in str(e.value) and time.time() - t0 < 2
    assert started == []                              # 한글을 켜려고 하지도 않음


def test_module_names_only_existing_files(monkeypatch, tmp_path):
    import winreg
    dll = tmp_path / "m.dll"
    dll.write_bytes(b"x")
    vals = [("없는모듈", str(tmp_path / "없음.dll"), 1), ("있는모듈", str(dll), 1)]

    class K:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(winreg, "OpenKey", lambda *a, **k: K())

    def enum(k, i):
        if i >= len(vals):
            raise OSError
        return vals[i]
    monkeypatch.setattr(winreg, "EnumValue", enum)
    assert office._hwp_module_names() == ["있는모듈"]
    vals.pop()
    assert office._hwp_module_names() == [] and not office.hwp_security_ready()


def test_uses_hwp_finds_nested_steps():
    from gui.v3.hwp_setup import uses_hwp
    assert uses_hwp({"steps": [{"type": "if", "cond": {}, "then": [{"type": "group", "steps": [{"type": "hwp", "action": "open"}]}]}]})
    assert not uses_hwp({"steps": [{"type": "excel", "action": "open"}]})


def test_toast_delivered_missing_db_is_unknown(monkeypatch, tmp_path):
    from engine import notify
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert notify.toast_delivered("아무거나", time.time()) is None
