"""사무 기능 단계의 편집기 입력칸(글자 만들기·날짜·계산·글자 비교 조건)."""
import pytest
from PySide6.QtWidgets import QComboBox, QLineEdit

from engine.model import validate_macro
from gui.v2.model import StepNode, default_step
from gui.v2.store import MacroStore
from gui.v3.editor.cond_editor import CondEditor
from gui.v3.editor.macro_editor import MacroEditorDialog
from gui.v3.editor.step_form import StepForm


@pytest.fixture
def store(tmp_path):
    return MacroStore(str(tmp_path))


def _combo_with(form, data):
    for c in form.findChildren(QComboBox):
        if c.findData(data) >= 0:
            return c
    raise AssertionError(data)


def _edit_by_placeholder(form, part):
    for e in form.findChildren(QLineEdit):
        if part in e.placeholderText():
            return e
    raise AssertionError(part)


def test_text_form_extract(qapp):
    node = StepNode(default_step("text"))
    f = StepForm()
    f.set_node(node)
    f.show()
    c = _combo_with(f, "extract")
    c.setCurrentIndex(c.findData("extract"))
    _edit_by_placeholder(f, "재직_").setText("{원문}")
    _edit_by_placeholder(f, "괄호 안만").setText(r"([\d,]+)원")
    assert node.data["action"] == "extract" and node.data["pattern"] == r"([\d,]+)원"
    assert node.data["text"] == "{원문}"
    m = {"version": 2, "name": "a", "steps": [node.data]}
    assert validate_macro(m) == []
    # 필요 없는 칸은 숨김
    assert not _edit_by_placeholder(f, "비우면 지움").isVisible()


def test_date_and_calc_forms(qapp):
    node = StepNode(default_step("date"))
    f = StepForm()
    f.set_node(node)
    _edit_by_placeholder(f, "yyyy-MM-dd,").setText("yyyyMMdd")
    assert node.data["format"] == "yyyyMMdd"
    node2 = StepNode(default_step("calc"))
    f2 = StepForm()
    f2.set_node(node2)
    _edit_by_placeholder(f2, "가격 * 수량").setText("a * 2")
    assert node2.data["expr"] == "a * 2"
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data, node2.data]}) == []


def test_cond_editor_text_ops_roundtrip(qapp):
    ce = CondEditor()
    ce.set_cond({"var": "상태", "contains": "완료"})
    assert ce.cond() == {"var": "상태", "contains": "완료"}
    ce.set_cond({"var": "상태", "is_empty": True})
    assert ce.cond() == {"var": "상태", "is_empty": True}
    ce.var_op.setCurrentIndex(ce.var_op.findData("starts_with"))
    ce.var_val.set_literal("처리")
    assert ce.cond() == {"var": "상태", "starts_with": "처리"}


def test_palette_and_editor_add_new_steps(qapp, store):
    store.create("m")
    dlg = MacroEditorDialog(store, "m")
    for t in ("text", "date", "calc"):
        dlg.add_step(t)
    assert [n.type for n in dlg.model.steps] == ["text", "date", "calc"]
    assert "고칠 곳" in dlg.status.text()          # 비어 있는 계산식


def test_clipboard_form(qapp):
    node = StepNode(default_step("clipboard"))
    f = StepForm()
    f.set_node(node)
    f.show()
    assert node.data == {"type": "clipboard", "action": "copy", "var": "복사한글"}
    c = _combo_with(f, "write")
    c.setCurrentIndex(c.findData("write"))
    _edit_by_placeholder(f, "그 값으로 바뀜").setText("번호 {번호}")
    assert node.data["action"] == "write" and node.data["text"] == "번호 {번호}"
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []


def test_file_form_and_cond(qapp):
    node = StepNode(default_step("file"))
    f = StepForm()
    f.set_node(node)
    f.show()
    _edit_by_placeholder(f, "보고서.xlsx").setText("받은편지/{파일}")
    _edit_by_placeholder(f, "폴더면 그 안에").setText("보관/{달}/")
    c = _combo_with(f, "replace")
    c.setCurrentIndex(c.findData("replace"))
    assert node.data == {"type": "file", "action": "copy", "path": "받은편지/{파일}", "to": "보관/{달}/",
                         "overwrite": "replace"}
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []
    ce = CondEditor()
    ce.set_cond({"file": {"path": "a.xlsx", "exists": False}})
    assert ce.cond() == {"file": {"path": "a.xlsx", "exists": False}}


def test_each_form_switch_sources(qapp, store):
    node = StepNode(default_step("each"))
    f = StepForm()
    f.set_node(node)
    f.show()
    _edit_by_placeholder(f, "목록이 든 변수").setText("파일들")
    assert node.data["list"] == "파일들"
    c = _combo_with(f, "rows")
    c.setCurrentIndex(c.findData("rows"))
    _edit_by_placeholder(f, "비우면 지금 시트").setText("명단")
    _edit_by_placeholder(f, "기본: 제목 다음 줄").setText("3")
    assert "list" not in node.data and node.data["rows"] == {"sheet": "명단", "from": 3}
    assert validate_macro({"version": 2, "name": "a", "steps": [node.to_dict()]}) == []
    store.create("m")
    dlg = MacroEditorDialog(store, "m")
    dlg.add_step("each")
    dlg.add_inside("type_text")
    assert dlg.model.steps[0].children("steps")[0].type == "type_text"


def test_ask_dialog_kinds_and_timeout(qapp):
    from PySide6.QtCore import QTimer
    from gui.v3.ask_dialog import AskDialog
    d = AskDialog({"kind": "choose", "message": "어느 지점?", "options": ["강남", "부산"], "default": "부산"})
    d._ok()
    assert (d.status, d.value) == ("ok", "부산")
    d = AskDialog({"kind": "confirm", "message": "진행?"})
    d._done("ok", False)
    assert (d.status, d.value) == ("ok", False)
    d = AskDialog({"kind": "input", "message": "몇 월?", "timeout": 1})
    QTimer.singleShot(50, d._tick)                 # 1초 → 0초: 시간이 지나면 timeout 으로 닫힘
    d.exec()
    assert d.status == "timeout"


def test_run_thread_asks_screen_and_continues(qapp, fake_env):
    from gui.v3.run_thread import RunThread
    from tests.gui_v3.conftest import wait_until
    m = {"version": 2, "name": "m", "steps": [
        {"type": "ask", "kind": "input", "var": "달", "message": "몇 월?"},
        {"type": "type_text", "text": "{달}월"}]}
    t = RunThread(m, env_factory=lambda: fake_env, emergency_hotkey=None, write_trace=False)
    asked = []
    t.ask_requested.connect(lambda req: (asked.append(req), t.answer("ok", "11")))
    done = []
    t.run_finished.connect(done.append)
    t.start()
    assert wait_until(qapp, lambda: bool(done), 10)
    assert done[0]["status"] == "ok", done[0]
    assert asked and asked[0]["message"] == "몇 월?"
    assert [e[2] for e in fake_env.input.events if e[1] == "type"] == ["11월"]


def test_ask_notify_forms(qapp):
    node = StepNode(default_step("ask"))
    f = StepForm()
    f.set_node(node)
    f.show()
    c = _combo_with(f, "choose")
    c.setCurrentIndex(c.findData("choose"))
    _edit_by_placeholder(f, "쉼표로 나눈").setText("강남, 부산")
    _edit_by_placeholder(f, "몇 월 자료").setText("어느 지점?")
    assert node.data["options"] == ["강남", "부산"] and node.data["kind"] == "choose"
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []
    n2 = StepNode(default_step("notify"))
    f2 = StepForm()
    f2.set_node(n2)
    from PySide6.QtWidgets import QCheckBox, QPlainTextEdit
    f2.findChildren(QPlainTextEdit)[0].setPlainText("끝")
    [b for b in f2.findChildren(QCheckBox) if b.text() in ("소리",)][0].setChecked(True)
    assert n2.data["channels"] == ["toast", "sound"] and n2.data["message"] == "끝"
    assert validate_macro({"version": 2, "name": "a", "steps": [n2.data]}) == []


def test_web_table_download_and_csv_forms(qapp):
    node = StepNode({"type": "web", "action": "table", "var": "표"})
    f = StepForm()
    f.set_node(node)
    f.show()
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []
    n2 = StepNode({"type": "web", "action": "download", "selector": "a.x"})
    f2 = StepForm()
    f2.set_node(n2)
    _edit_by_placeholder(f2, "비우면 자료 폴더").setText("보관/{달}")
    assert n2.data["path"] == "보관/{달}"
    n3 = StepNode({"type": "file", "action": "write_csv", "path": "a.csv", "data": ""})
    f3 = StepForm()
    f3.set_node(n3)
    f3.show()
    _edit_by_placeholder(f3, "표가 든 변수").setText("표")
    assert n3.data["data"] == "표"
    assert validate_macro({"version": 2, "name": "a", "steps": [n2.data, n3.data]}) == []


def test_file_permanent_checkbox_only_for_delete(qapp):
    from PySide6.QtWidgets import QCheckBox
    node = StepNode({"type": "file", "action": "delete", "path": "a.txt"})
    f = StepForm()
    f.set_node(node)
    f.show()
    box = [b for b in f.findChildren(QCheckBox) if "영구 삭제" in b.text()][0]
    assert box.isVisible() and not box.isChecked()
    box.setChecked(True)
    assert node.data["permanent"] is True
    c = _combo_with(f, "copy")
    c.setCurrentIndex(c.findData("copy"))
    assert "permanent" not in node.data and not box.isVisible()


def test_pdf_and_print_forms(qapp):
    node = StepNode(default_step("pdf"))
    f = StepForm()
    f.set_node(node)
    f.show()
    c = _combo_with(f, "extract")
    c.setCurrentIndex(c.findData("extract"))
    _edit_by_placeholder(f, "청구서.pdf").setText("{파일}")
    _edit_by_placeholder(f, "괄호 안만").setText(r"합계:\s*([\d,]+)")
    assert node.data["action"] == "extract" and node.data["path"] == "{파일}"
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []
    n2 = StepNode({"type": "excel", "action": "print"})
    f2 = StepForm()
    f2.set_node(n2)
    _edit_by_placeholder(f2, "비우면 프린터로").setText("출력/{오늘}.pdf")
    assert n2.data["to_file"] == "출력/{오늘}.pdf"
    assert validate_macro({"version": 2, "name": "a", "steps": [n2.data]}) == []


def test_mail_form(qapp):
    node = StepNode(default_step("mail"))
    f = StepForm()
    f.set_node(node)
    f.show()
    _edit_by_placeholder(f, "예: 거래처").setText("거래처")
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []
    c = _combo_with(f, "send")
    c.setCurrentIndex(c.findData("send"))
    _edit_by_placeholder(f, "여러 명은").setText("boss@example.invalid")
    assert node.data["action"] == "send" and "send_now" not in node.data
    v = _combo_with(f, "server")       # 단계 종류 고르기에도 'web' 이 있어서 메일 길 고르기로 찾음
    v.setCurrentIndex(v.findData("web"))
    assert node.data["via"] == "web" and node.data["service"] == "naver"
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []


def test_mail_accounts_dialog_keeps_password_out_of_file(qapp, tmp_path):
    from gui.v3.mail_accounts import MailAccountsDialog
    saved = {}

    class Cred:
        def save(self, name, user, pw):
            saved[name] = (user, pw)

        def delete(self, name):
            saved.pop(name, None)
    d = MailAccountsDialog(str(tmp_path), cred=Cred())
    d.name.setText("회사")
    d.preset.setCurrentIndex(d.preset.findData("naver"))
    d.user.setText("me@example.com")
    d.password.setText("앱비밀번호")
    assert d.save()
    raw = (tmp_path / "settings" / "mail_accounts.json").read_text(encoding="utf-8")
    assert "imap.naver.com" in raw and "앱비밀번호" not in raw
    assert saved["회사"] == ("me@example.com", "앱비밀번호") and d.password.text() == ""


def test_list_form_and_rows_group(qapp):
    node = StepNode(default_step("list"))
    f = StepForm()
    f.set_node(node)
    f.show()
    from PySide6.QtWidgets import QPlainTextEdit
    f.findChildren(QPlainTextEdit)[0].setPlainText('{"날짜": "{날짜}", "금액": "{금액}"}')
    assert node.data["value"] == {"날짜": "{날짜}", "금액": "{금액}"}
    c = _combo_with(f, "sort")
    c.setCurrentIndex(c.findData("sort"))
    _edit_by_placeholder(f, "정렬할 칸").setText("날짜, 시간")
    assert node.data["action"] == "sort" and node.data["by"] == "날짜, 시간"
    assert validate_macro({"version": 2, "name": "a", "steps": [node.data]}) == []
    n2 = StepNode({"type": "each", "var": "건", "rows": {}, "steps": []})
    f2 = StepForm()
    f2.set_node(n2)
    f2.show()
    _edit_by_placeholder(f2, "새 건이 시작되는 칸").setText("A")
    assert n2.data["rows"]["group_by"] == "A"
