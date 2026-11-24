"""화면에 보여 주는 도움말 글(Qt 없음). 언어에 맞는 판은 main_help()·background_help() 로 얻는다."""
from gui.v2.i18n import current

BACKGROUND_HELP = """<b>뒤에서 실행이란</b><br>
보통 매크로는 <b>진짜 마우스</b>를 움직여 누릅니다. 그동안 컴퓨터를 쓸 수 없고, 대상 창이 맨 앞에 있어야 합니다.<br>
'뒤에서 실행'을 켜면 대상 창이 다른 창 뒤에 있어도 매크로가 그 창을 다룹니다.<br>
<ul>
<li>진짜 마우스·키보드 초점을 쓰지 않습니다 → 매크로가 도는 동안 다른 작업을 해도 됩니다.</li>
<li>화면도 그 창만 따로 찍어서 봅니다.</li>
<li>저장 창·확인 창·설정 창, Ctrl+Shift+S 같은 단축키도 됩니다.</li>
</ul>
<b>언제 켜나요</b>
<ul>
<li>오래 혼자 도는 매크로</li>
<li>매크로를 돌리면서 같은 컴퓨터로 다른 일을 하고 싶을 때</li>
</ul>
<b>조건·주의</b>
<ul>
<li>'대상 창'(창 제목 일부)을 꼭 넣어야 켤 수 있습니다.</li>
<li>대상 창이 <b>최소화</b>돼 있으면, 그림 찾기·위치 클릭·화면 보기가 필요할 때 창을 화면에 안 보이게 되살려서 이어 갑니다. 끝나면 다시 최소화됩니다.</li>
<li><b>키 입력</b>은 프로그램에 따라 안 먹을 수 있습니다(예: 일부 게임은 Esc 가 안 먹음). 이럴 땐 화면 버튼 클릭으로 바꾸세요.</li>
<li>한 프로그램은 한 매크로가 다루는 동안 다른 곳(AI의 스텝 시험 등)에서 동시에 다루면 안 먹을 수 있습니다.
   그럴 땐 돌던 매크로를 멈추고 시험한 뒤 다시 켜세요.</li>
<li>'뒤에서 실행을 시작하지 못함' 오류가 나면 관리자 권한으로 도는 프로그램인지 보고, '호환 모드'를 켜 보세요.</li>
<li>웹 요소 스텝(web)은 이것과 상관없이 웹 자동화 브라우저를 직접 다룹니다.</li>
</ul>
<b>숨겨서 실행</b>
<ul>
<li>'뒤에서 실행' 옆 '숨겨서 실행'을 켜면, 매크로가 도는 동안 대상 창이 화면에 안 보입니다.</li>
<li>끝나면(오류·정지 포함) 창이 원래대로 돌아옵니다. 매크로 프로그램이 갑자기 꺼져도 몇 초 안에 돌아옵니다.</li>
<li>최소화된 창에 클릭 없이 글자만 넣으면 일부 프로그램(엑셀·계산기)은 글자를 놓칩니다. 먼저 그 칸을 누르거나, 창 요소·엑셀 스텝을 쓰세요.</li>
</ul>
<b>호환 모드</b>
<ul>
<li>'고급 설정 → 뒤에서 실행 방식 → 호환 모드'를 켜면 다른 방식으로 돌립니다.</li>
<li>어떤 프로그램에서 뒤에서 실행이 시작되지 않거나 보안 프로그램과 부딪힐 때 켜 보세요.</li>
<li>대신 일부 프로그램은 호환 모드에서 클릭이 안 먹을 수 있습니다. 그럴 땐 칸을 끄세요.</li>
</ul>"""

MAIN_HELP = """<b>기본</b>
<ul>
<li>더블클릭: 편집 · F5: 실행 · Shift+F5: 중지 · 끌어서 놓기: 그룹 이동</li>
<li>실행 중 어디서든 <b>Ctrl+Shift+F12</b> 를 누르면 즉시 멈춥니다.</li>
<li>왼쪽 목록에서 매크로 아래 들어 있는 것은 그 매크로가 불러 쓰는 매크로입니다(▸ 로 펼치기). '매크로' 메뉴에서 한 줄 목록으로 바꿀 수 있습니다.</li>
</ul>
<b>위 도구 모음</b>
<ul>
<li>녹화: 마우스·키보드를 받아 적어 새 매크로로(끝내기 F9)</li>
<li>핫키: 실행/정지 키(같은 키 = 실행·정지 번갈아) · 예약: 매일 몇 시 / 몇 분마다(이 프로그램이 켜져 있을 때)</li>
<li>AI 연결하기: Claude·Codex·제미나이·Cursor 등 AI에 붙이는 설정 글과 요청 글(만든 뒤엔 토큰 없이 반복)</li>
<li>실행 기록: 실행할 때마다 남는 기록 폴더 열기</li>
</ul>
<b>편집기</b>
<ul>
<li>오른쪽 '부품 상자'에서 스텝을 더블클릭해 넣고, 가운데에서 값을 고칩니다. '이 스텝 시험'으로 하나씩 확인.</li>
<li>웹 요소 스텝: 좌표·그림 대신 버튼 글자·입력칸으로 웹 자동화 브라우저를 다룹니다.</li>
<li>오피스 스텝(엑셀·한글·워드): 셀·누름틀·책갈피를 이름으로 읽고 써서 문서 작업을 자동화합니다. PDF 저장도 됩니다.</li>
</ul>
<b>막히면 AI 한 번 부르기</b>
<ul>
<li>매크로 편집 창의 '막히면 AI 한 번 부르기'에서 켭니다. <b>기본은 꺼져 있습니다.</b></li>
<li>언제: 스텝이 다시 시도까지 다 실패해 실행이 멈추기 직전에만 부릅니다. 평소에는 AI 없이 돕니다.</li>
<li>무엇을 보내나: 그 순간의 화면 사진, 직전 실행 기록, 실패한 스텝이 이 컴퓨터의 AI 프로그램으로 갑니다. 화면에 개인정보가 보이면 함께 갈 수 있습니다.</li>
<li>한도: 시간당·하루 횟수를 정할 수 있고, 같은 스텝·같은 화면으로는 하루 안에 다시 부르지 않습니다.</li>
<li>AI는 이미 있는 스텝으로만 답하고, 결제·로그인·금지 구역 같은 위험한 동작은 걸러냅니다.</li>
<li>고친 뒤 실패했던 스텝이 통과하면 해결 규칙으로 저장돼, 다음부터는 AI 없이 그 방법을 씁니다('저장된 해결 지우기'로 지움).</li>
<li>설정 → 'AI 도우미 설정'에서 쓸 AI 프로그램을 고릅니다.</li>
</ul>
""" + "<hr>" + BACKGROUND_HELP + """"""


BACKGROUND_HELP_EN = """<b>What is "Run in background"?</b><br>
Normally a macro moves the <b>real mouse</b> to click. You cannot use the computer meanwhile, and the target window must stay in front.<br>
With "Run in background" on, the macro works on the target window even when it is behind other windows.<br>
<ul>
<li>The real mouse and keyboard focus are not used, so you can keep working while the macro runs.</li>
<li>The screen is captured from that window alone.</li>
<li>Save As / confirmation / settings dialogs and key combos such as Ctrl+Shift+S work too.</li>
</ul>
<b>When to turn it on</b>
<ul>
<li>Macros that run on their own for a long time</li>
<li>When you want to use the same computer for other work while the macro runs</li>
</ul>
<b>Conditions and cautions</b>
<ul>
<li>You must enter the "Target window" (part of the window title) before you can turn it on.</li>
<li>If the target window is <b>minimized</b>, it is brought back invisibly when picture search, position clicks or screen reading need it, and minimized again at the end.</li>
<li><b>Key presses</b> may not work in some programs (for example, some games ignore Esc). In that case, switch to clicking an on-screen button.</li>
<li>While one macro works on a program, controlling the same program from elsewhere at the same time (such as an AI step test) may not work.
   In that case stop the running macro, test, and turn it on again.</li>
<li>If you get "Could not start Run in background", check whether the program runs as administrator, and try "Compatibility mode".</li>
<li>Web element steps (web) control the web automation browser directly and are not affected.</li>
</ul>
<b>Run hidden</b>
<ul>
<li>Turn on "Run hidden" next to "Run in background" and the target window stays invisible while the macro runs.</li>
<li>At the end (also after an error or a stop) the window comes back as it was. If this program closes suddenly, it comes back within seconds.</li>
<li>Typing into a minimized window without clicking first loses the text in some programs (Excel, Calculator). Click the field first, or use element or Excel steps.</li>
</ul>
<b>Compatibility mode</b>
<ul>
<li>Turn on "Advanced settings > Background mode > Compatibility mode" to run it a different way.</li>
<li>Try it when background mode does not start for a program or conflicts with security software.</li>
<li>Some programs may ignore clicks in compatibility mode. Then turn it off again.</li>
</ul>"""

MAIN_HELP_EN = """<b>Basics</b>
<ul>
<li>Double-click: edit - F5: run - Shift+F5: stop - Drag and drop: move to a group</li>
<li>While a macro runs, press <b>Ctrl+Shift+F12</b> anywhere to stop it at once.</li>
<li>Macros listed under a macro on the left are the ones it calls (expand with the arrow). In the "Macro" menu you can switch to a flat list.</li>
</ul>
<b>Top toolbar</b>
<ul>
<li>Record: capture mouse and keyboard into a new macro (press F9 to finish)</li>
<li>Hotkey: keys to run/stop (same key = toggle run/stop) - Schedule: every day at a time / every N minutes (only while this program is open)</li>
<li>Connect AI: setup text and a request text to attach this program to an AI such as Claude, Codex, Gemini or Cursor (after building, it repeats without tokens)</li>
<li>Run log: open the folder holding a record of every run</li>
</ul>
<b>Editor</b>
<ul>
<li>Double-click a step in the "Parts box" on the right to add it, then edit its values in the middle. Check them one by one with "Test this step".</li>
<li>Web element steps: control the web automation browser by button text and input fields instead of coordinates or images.</li>
<li>Office steps (Excel, Hangul, Word): read and write cells, fields and bookmarks by name to automate documents. Saving as PDF also works.</li>
</ul>
<b>Call an AI once when stuck</b>
<ul>
<li>Turn it on in the macro editor under "Call an AI once when stuck". <b>It is off by default.</b></li>
<li>When: only right before a run stops because a step failed even after its retries. Normally the macro runs without AI.</li>
<li>What is sent: a screenshot of that moment, the recent run record and the failed step go to the AI program on this computer. Personal information visible on screen may be sent with it.</li>
<li>Limits: you set a per-hour and per-day count, and the same step on the same screen is not asked again within a day.</li>
<li>The AI may only answer with existing steps, and risky actions (payment, login, forbidden areas) are filtered out.</li>
<li>If the failed step passes after the fix, it is saved as a fix rule and used next time without AI (clear them with "Clear saved fixes").</li>
<li>Choose which AI program to use in Settings -> "AI helper settings".</li>
</ul>
""" + "<hr>" + BACKGROUND_HELP_EN


def background_help() -> str:
    return BACKGROUND_HELP if current() == "ko" else BACKGROUND_HELP_EN


def main_help() -> str:
    return MAIN_HELP if current() == "ko" else MAIN_HELP_EN


def show_html(parent, title: str, html: str):
    """긴 도움말을 스크롤되는 창으로."""
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.resize(640, 560)
    v = QVBoxLayout(d)
    tb = QTextBrowser()
    tb.setHtml(html)
    v.addWidget(tb)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(d.reject)
    bb.accepted.connect(d.accept)
    v.addWidget(bb)
    d.exec()
