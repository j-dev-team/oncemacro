"""입력을 쓰는 매크로만 입력 잠금을 잡는다(파일·엑셀·알림 매크로는 다른 실행과 같이 돌아도 됨)."""
from engine.inputs import uses_input


def test_uses_input():
    files = {"steps": [{"type": "file", "action": "move"}, {"type": "notify", "message": "x"},
                       {"type": "each", "steps": [{"type": "excel", "action": "read"}]}]}
    assert not uses_input(files)
    assert uses_input({"steps": [{"type": "if", "cond": {}, "then": [{"type": "click"}]}]})
    assert uses_input({"steps": [{"type": "clipboard", "action": "copy"}]})
    assert not uses_input({"steps": [{"type": "clipboard", "action": "read"}]})
    lib = {"하위": {"steps": [{"type": "key", "keys": "a"}]}, "조용": {"steps": [{"type": "delay", "seconds": 1}]}}
    assert uses_input({"steps": [{"type": "call", "macro": "하위"}]}, lib.__getitem__)
    assert not uses_input({"steps": [{"type": "call", "macro": "조용"}]}, lib.__getitem__)
    assert uses_input({"steps": [{"type": "call", "macro": "없음"}]}, lib.__getitem__)   # 모르면 안전하게
    assert uses_input({"steps": [{"type": "call", "macro": "조용"}]})                    # 불러올 길이 없으면 안전하게
