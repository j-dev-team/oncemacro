"""매크로 묶음 주고받기: 부르는 매크로·그림까지 파일 하나로, 가져올 때 이름 겹침·그림 겹침 처리, 화면 배율 다르면 알림."""
import os

from engine import pack
from gui.v2.store import MacroStore


def _m(name, steps):
    return {"version": 2, "name": name, "repeat": {"times": 1}, "steps": steps}


def test_roundtrip_with_clash(tmp_path, monkeypatch):
    a_img = tmp_path / "A" / "image"
    (a_img / "g").mkdir(parents=True)
    (a_img / "g" / "ok.png").write_bytes(b"PNG-ok")
    src = MacroStore(str(tmp_path / "A" / "macros_v2"))
    src.save(_m("메인", [{"type": "call", "macro": "하위"},
                        {"type": "click", "target": {"image": "g/ok.png"}}]))
    src.save(_m("하위", [{"type": "wait", "until": {"exists": {"image": "g/ok.png"}}, "timeout": 1}]))
    src.save(_m("상관없음", [{"type": "delay", "seconds": 0}]))
    out = pack.export(src, "메인", str(tmp_path / "묶음"), str(a_img))
    assert out["path"].endswith(".macropack") and out["macros"] == ["메인", "하위"] and out["images"] == 1

    b_img = tmp_path / "B" / "image"
    (b_img / "g").mkdir(parents=True)
    (b_img / "g" / "ok.png").write_bytes(b"PNG-other")          # 같은 이름, 다른 그림
    dst = MacroStore(str(tmp_path / "B" / "macros_v2"))
    dst.save(_m("하위", [{"type": "delay", "seconds": 0}]))       # 같은 이름 매크로
    monkeypatch.setattr(pack, "screen_info", lambda: {"width": 1920, "height": 1080, "scale": 1.5})
    r = pack.import_pack(dst, out["path"], str(b_img))
    new_sub = r["renamed"]["하위"]
    assert new_sub != "하위" and set(r["added"]) == {"메인", new_sub}
    main = dst.load("메인")
    assert main["steps"][0]["macro"] == new_sub                   # 부르는 쪽 이름도 바뀜
    img = main["steps"][1]["target"]["image"]
    assert img != "g/ok.png" and (b_img / img).read_bytes() == b"PNG-ok"
    assert (b_img / "g" / "ok.png").read_bytes() == b"PNG-other"  # 원래 그림 그대로
    assert dst.load("하위")["steps"] == [{"type": "delay", "seconds": 0}]


def test_peek_and_scale_warning(tmp_path, monkeypatch):
    img = tmp_path / "image"
    img.mkdir()
    st = MacroStore(str(tmp_path / "m"))
    st.save(_m("a", [{"type": "delay", "seconds": 0}]))
    monkeypatch.setattr(pack, "screen_info", lambda: {"width": 1600, "height": 900, "scale": 1.0})
    out = pack.export(st, "a", str(tmp_path / "x.macropack"), str(img))
    assert pack.peek(out["path"])["screen"]["scale"] == 1.0
    st2 = MacroStore(str(tmp_path / "m2"))
    monkeypatch.setattr(pack, "screen_info", lambda: {"width": 1600, "height": 900, "scale": 1.25})
    r = pack.import_pack(st2, out["path"], str(img))
    assert r["added"] == ["a"] and "배율" in r["warnings"][0]
