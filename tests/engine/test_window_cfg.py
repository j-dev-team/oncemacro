"""window 설정 검사: wrapper(false = 호환 모드)."""
from engine import new_macro, validate_macro


def test_wrapper_flag_validates():
    ok = new_macro("w", [], window={"title": "메모장", "background": True, "wrapper": False})
    assert validate_macro(ok) == []
    bad = new_macro("w", [], window={"title": "메모장", "background": True, "wrapper": "no"})
    assert any("wrapper" in e for e in validate_macro(bad))
