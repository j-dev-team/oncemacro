"""
'AI 연결하기' 창: 여러 AI 프로그램(Claude·Codex·제미나이·Cursor)에 이 매크로 프로그램의 MCP 서버를 붙이는 설정 글.

설정 형식은 각 공식 문서 기준(2026-11-17 확인):
- Claude 데스크톱: %APPDATA%\\Claude\\claude_desktop_config.json  {"mcpServers": {이름: {command, args, env}}}
- Claude Code: 프로젝트 .mcp.json(같은 JSON) 또는 `claude mcp add`
- Codex(CLI·데스크톱 앱): ~/.codex/config.toml  [mcp_servers.이름] command/args/cwd + [mcp_servers.이름.env]
- 제미나이 CLI: ~/.gemini/settings.json  {"mcpServers": {이름: {command, args, env, cwd}}} (이름에 밑줄 쓰지 말 것)
- Cursor: ~/.cursor/mcp.json  {"mcpServers": {이름: {type: "stdio", command, args, env}}}
- ChatGPT 웹: 내 컴퓨터의(stdio) MCP 는 직접 못 붙음(원격 MCP 만)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from gui.v2.i18n import tr

SERVER_NAME = "macro"


def project_root() -> str:
    from engine.real import MACRO_ROOT
    return os.path.dirname(os.path.abspath(MACRO_ROOT))


def launch_spec() -> Optional[dict]:
    """MCP 서버를 띄울 명령. 실행 파일(MacroManager.exe --mcp)이 있으면 그것(파이썬 필요 없음),
    없으면 이 컴퓨터의 파이썬(가상환경). 둘 다 못 찾으면 None."""
    root = project_root()
    exe = sys.executable if getattr(sys, "frozen", False) else None
    if not exe:
        for c in (os.path.join(root, "dist", "MacroManager.exe"), os.path.join(root, "MacroManager.exe"),
                  os.path.join(root, "OnceMacro.exe")):
            if os.path.exists(c):
                exe = c
                break
    if exe:
        from gui.v2.i18n import current
        args = ["--mcp"] + (["--lang", "en"] if current() == "en" else [])     # 영어 화면이면 AI 설명서도 영어판
        return {"command": exe, "args": args, "env": {}, "cwd": os.path.dirname(exe)}
    cands = [os.path.join(root, "venv", "Scripts", "python.exe"), os.path.join(root, ".venv", "Scripts", "python.exe")]
    if not getattr(sys, "frozen", False):
        cands.insert(0, sys.executable)
    py = next((c for c in cands if c and os.path.exists(c)), None)
    if not py:
        return None
    from gui.v2.i18n import current
    return {"command": py, "args": ["-m", "engine.mcp_server"] + (["--lang", "en"] if current() == "en" else []),
            "env": {"PYTHONPATH": root, "PYTHONIOENCODING": "utf-8"}, "cwd": root}


def _json_block(spec: dict, cursor: bool = False, with_cwd: bool = False) -> str:
    s = {}
    if cursor:
        s["type"] = "stdio"
    s.update({"command": spec["command"], "args": spec["args"]})
    if spec["env"]:
        s["env"] = spec["env"]
    if with_cwd:
        s["cwd"] = spec["cwd"]
    return json.dumps({"mcpServers": {SERVER_NAME: s}}, ensure_ascii=False, indent=2)


def _toml_block(spec: dict) -> str:
    q = lambda v: json.dumps(v, ensure_ascii=False)        # TOML 기본 문자열은 JSON 문자열과 같은 꼴
    lines = [f"[mcp_servers.{SERVER_NAME}]",
             f"command = {q(spec['command'])}",
             f"args = [{', '.join(q(a) for a in spec['args'])}]",
             f"cwd = {q(spec['cwd'])}"]
    if spec["env"]:
        lines += ["", f"[mcp_servers.{SERVER_NAME}.env]"] + [f"{k} = {q(v)}" for k, v in spec["env"].items()]
    return "\n".join(lines)


def request_text() -> str:
    return tr(
    "macro MCP 도구만 써서 매크로를 만들어 줘. 코드를 새로 짜지 말고 이미 있는 스텝을 붙여.\n"
    "순서: macro_reference 읽기 → (웹이면) macro_web_view 로 페이지 보기 / (프로그램이면) macro_list_windows·"
    "macro_screenshot 으로 화면 보기 → macro_test_step 으로 한 스텝씩 시험 → macro_save → macro_run 으로 확인.\n"
    "할 일: (예) https://example.com 에서 ○○을 검색해 첫 결과 제목을 읽어 오기\n"
    "매크로 이름: (예) 웹_예시")


def entries() -> List[Tuple[str, str, str, str]]:
    """(탭 이름, 설정 파일 위치 안내, 붙여 넣을 글, 덧붙임) 목록."""
    spec = launch_spec()
    if spec is None:
        miss = tr("이 컴퓨터에서 MCP 서버를 띄울 파이썬(가상환경)을 찾지 못했습니다. "
                  "매크로 프로그램 폴더에 venv 를 만들고 필요한 패키지를 설치한 뒤 다시 여세요.")
        return [(tr("안내"), "", miss, "")]
    claude_desktop = _json_block(spec)
    return [
        (tr("Claude 데스크톱"), r"%APPDATA%\Claude\claude_desktop_config.json  " + tr("(설정 → 개발자 → 설정 편집)"),
         claude_desktop, tr("파일에 이미 mcpServers 가 있으면 그 안에 \"macro\" 부분만 넣으세요. 저장 뒤 Claude 를 완전히 껐다 켜세요.")),
        ("Claude Code", tr("프로젝트 폴더의 .mcp.json  (또는 터미널에서 claude mcp add)"),
         claude_desktop, tr("같은 형식입니다. 새 대화부터 macro 도구가 보입니다.")),
        (tr("Codex (CLI·데스크톱)"), r"%USERPROFILE%\.codex\config.toml",
         _toml_block(spec), tr("파일 맨 아래에 붙여 넣으세요. 데스크톱 앱은 설정 → MCP servers → Add server(STDIO)로도 넣을 수 있습니다.")),
        (tr("제미나이 CLI"), r"%USERPROFILE%\.gemini\settings.json  " + tr("(프로젝트만이면 .gemini\\settings.json)"),
         _json_block(spec, with_cwd=True), tr("이미 다른 설정이 있으면 mcpServers 부분만 합쳐 넣으세요.")),
        ("Cursor", r"%USERPROFILE%\.cursor\mcp.json  " + tr("(프로젝트만이면 .cursor\\mcp.json)"),
         _json_block(spec, cursor=True), tr("저장 뒤 Cursor 설정의 MCP 목록에서 macro 가 켜졌는지 확인하세요.")),
        (tr("ChatGPT 웹"), "",
         tr("ChatGPT 웹은 내 컴퓨터에서 도는 MCP 서버에 직접 붙지 않습니다(인터넷 주소로 여는 원격 MCP 만 받음).\n"
            "같은 회사의 Codex(CLI·데스크톱 앱)는 'Codex' 탭 설정으로 붙일 수 있습니다."), ""),
        (tr("공통 요청 글"), tr("어느 AI 에나 연결한 뒤 이 글을 붙여 넣고 '할 일'만 바꾸세요."), request_text(), ""),
    ]


STATUS_TEXT = {"connected": "연결됨", "different": "다른 설정이 있음(바꾸기)", "absent": "아직 안 됨",
               "broken": "설정 파일이 깨져 있음", "missing": "이 컴퓨터에 없음"}


def show_dialog(parent=None, exec_: bool = True):
    """AI 연결: ① 깔린 AI를 찾아 [연결하기] 한 번 → ② 할 일을 적어 'AI에게 시키기' → (고급) 설정 글 직접 넣기."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                                   QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)
    from . import ai_setup
    d = QDialog(parent)
    d.setWindowTitle(tr("AI 연결하기"))
    d.resize(760, 600)
    v = QVBoxLayout(d)
    top = QLabel(tr("AI가 이 프로그램의 도구로 화면·웹을 보고 이미 있는 스텝을 붙여 매크로를 만듭니다. "
                    "만든 뒤에는 AI 없이 이 프로그램으로 돌리므로 토큰이 들지 않습니다."))
    top.setWordWrap(True)
    v.addWidget(top)
    spec = launch_spec()

    # ① 한 번에 연결
    g1 = QGroupBox(tr("① 쓰는 AI에 연결하기"))
    grid = QGridLayout(g1)
    d._rows = {}
    if spec is None:
        grid.addWidget(QLabel(tr("이 컴퓨터에서 MCP 서버를 띄울 파이썬(가상환경)을 찾지 못했습니다.")), 0, 0)
    else:
        for r, c in enumerate(ai_setup.clients()):
            name = QLabel("<b>" + c["name"] + "</b>")
            st = QLabel()
            btn = QPushButton(tr("연결하기"))

            def refresh(c=c, st=st, btn=btn):
                k = ai_setup.status(c, spec)
                st.setText(tr(STATUS_TEXT[k]))
                btn.setEnabled(k in ("absent", "different"))
                btn.setText(tr("다시 연결") if k == "different" else tr("연결하기"))
                return k

            def do(_=False, c=c, refresh=refresh):
                res = ai_setup.connect(c, spec)
                refresh()
                if res["ok"]:
                    msg = res["message"] + "\n" + tr(ai_setup.AFTER.get(c["key"], ""))
                    if res.get("backup"):
                        msg += "\n" + tr("원래 설정은 따로 남겨 두었습니다: {p}").format(p=res["backup"])
                    QMessageBox.information(d, tr("AI 연결하기"), msg)
                else:
                    QMessageBox.warning(d, tr("AI 연결하기"), res["message"])
            btn.clicked.connect(do)
            refresh()
            grid.addWidget(name, r, 0)
            grid.addWidget(st, r, 1)
            grid.addWidget(btn, r, 2)
            d._rows[c["key"]] = (c, st, btn, refresh)
        grid.setColumnStretch(1, 1)
        note = QLabel(tr("[연결하기]를 누르면 그 AI의 설정 파일에 'macro' 한 칸만 넣습니다. 다른 설정은 그대로 두고, 원래 파일은 따로 남겨 둡니다."))
        note.setWordWrap(True)
        note.setObjectName("Muted")
        grid.addWidget(note, len(d._rows), 0, 1, 3)
    v.addWidget(g1)

    # ② AI에게 시키기
    g2 = QGroupBox(tr("② AI에게 시키기"))
    gv = QVBoxLayout(g2)
    task = QLineEdit()
    task.setPlaceholderText(tr("할 일 (예: 이 웹 페이지에서 오늘 환율을 읽어 엑셀에 적기)"))
    mname = QLineEdit()
    mname.setPlaceholderText(tr("매크로 이름(선택)"))
    gv.addWidget(task)
    gv.addWidget(mname)
    row = QHBoxLayout()
    copy_b = QPushButton(tr("요청 글 복사"))
    copy_b.clicked.connect(lambda: (QApplication.clipboard().setText(ai_setup.request(task.text(), mname.text())),
                                    hint.setText(tr("복사했습니다. 연결한 AI 대화창에 붙여 넣으세요."))))
    row.addWidget(copy_b)
    d._start_buttons = {}
    for key, label in (("claude_code", tr("Claude Code 로 바로 시작")), ("codex", tr("Codex 로 바로 시작")),
                       ("gemini", tr("제미나이로 바로 시작"))):
        import shutil as _sh
        if _sh.which({"claude_code": "claude", "codex": "codex", "gemini": "gemini"}[key]):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, k=key: ai_setup.start_cli(k, ai_setup.request(task.text(), mname.text()),
                                                                         project_root()))
            row.addWidget(b)
            d._start_buttons[key] = b
    row.addStretch(1)
    gv.addLayout(row)
    hint = QLabel(tr("데스크톱 AI는 요청 글을 복사해 붙여 넣고, 터미널 AI는 [바로 시작]을 누르면 새 창에서 시작합니다."))
    hint.setWordWrap(True)
    hint.setObjectName("Muted")
    gv.addWidget(hint)
    v.addWidget(g2)

    # 고급: 직접 넣기
    adv_btn = QPushButton(tr("고급: 설정 글 직접 넣기…"))
    adv_btn.setCheckable(True)
    v.addWidget(adv_btn, 0, Qt.AlignLeft)
    tabs = QTabWidget()
    tabs.setVisible(False)
    adv_btn.toggled.connect(tabs.setVisible)
    v.addWidget(tabs, 1)
    for title, where, text, note_ in entries():
        w = QWidget()
        tv = QVBoxLayout(w)
        if where:
            lw = QLabel("<b>" + tr("넣을 곳") + "</b>: " + where)
            lw.setWordWrap(True)
            lw.setTextInteractionFlags(lw.textInteractionFlags() | Qt.TextSelectableByMouse)
            tv.addWidget(lw)
        te = QPlainTextEdit(text)
        te.setReadOnly(True)
        tv.addWidget(te, 1)
        if note_:
            ln = QLabel(note_)
            ln.setWordWrap(True)
            ln.setStyleSheet("color:#666")
            tv.addWidget(ln)
        cb = QPushButton(tr("복사"))
        cb.clicked.connect(lambda _=False, t=text: QApplication.clipboard().setText(t))
        tv.addWidget(cb)
        tabs.addTab(w, title)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    d._task, d._name, d._copy = task, mname, copy_b
    if exec_:
        d.exec()
    return d
