"""
매크로 엔진 v2 MCP 서버 (stdio).

AI가 실제 화면을 보고(스크린샷), 템플릿을 잘라 저장하고, 스텝을 하나씩 시험한 뒤
매크로로 저장·실행할 수 있게 한다. 실제 마우스·키보드를 움직이므로:
- 비상 정지: Ctrl+Shift+F12 (실행·시험 중 항상 켜져 있음), 또는 macro_stop 도구
- 모든 실행에는 시간 제한이 있다(stop 타이머)

실행: python -m engine.mcp_server
"""
import json
import os
import sys
import threading
import time
from typing import Annotated, Any, Dict, List, Optional

import anyio
import ctypes
import ctypes.wintypes
import cv2
import numpy as np
from mcp.server.mcpserver import Image, MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from .backends import WindowNotFound
from .library import MacroNotFound
from .model import DEFAULT_SETTINGS, MacroError, _Checker, ensure_valid, new_macro, validate_macro
from .templates import check_template
from .real import IMAGE_ROOT, MACRO_ROOT, TRACE_ROOT, RealEnv
from .runner import Context
from .trace import JsonlTrace, fanout, trace_path
from .win_input import DEFAULT_EMERGENCY_HOTKEY, EmergencyStop
from .win_window import (Win32Window, client_rect, find_window, is_process_elevated, list_windows,
                         self_elevated)

INSTRUCTIONS = """\
Windows 화면 자동화 매크로를 만드는 도구. 실제 마우스·키보드를 움직인다.
작업 순서:
1) macro_reference() 로 공통 형식과 분야 목록을 먼저 읽고, 필요한 분야만 macro_reference(category=...) 로 펼친다.
2) macro_list_windows 로 대상 창 제목을 찾고, macro_screenshot(window_title=...) 으로 화면을 본다.
   window_title 을 주면 모든 좌표는 그 창 '클라이언트 영역' 기준이다(매크로의 window 와 같은 기준).
   제목줄·메뉴줄은 y 가 음수로 나온다. 작은 버튼은 region 으로 확대해서(최대 4배) 좌표를 다시 읽는다.
3) 일반 프로그램(메모장·엑셀·사무 프로그램 등)의 버튼·입력칸은 먼저 macro_elements 로 이름 목록을 본다.
   목록에 있으면 그 줄의 element 대상을 그대로 쓴다(해상도·배율·테마가 바뀌어도 안 깨짐 — 그림보다 우선).
   목록에 없을 때(게임·그림으로 그린 화면)만 macro_capture_template 으로 잘라 저장한다(돌려준 경로를 image 대상에 그대로 사용).
   중복 경고가 나오면 영역(region)을 좁히거나 더 특징적인 부분을 자른다.
4) macro_test_step 으로 스텝을 하나씩 실제로 시험하고, 결과 화면을 확인한다.
5) 확인된 스텝들로 macro_save, 그다음 macro_run(시간 제한) 으로 전체를 돌려본다.
사용자가 정지를 원하면 macro_stop. 사람이 언제든 Ctrl+Shift+F12 로 끊을 수 있다.
게임·프로그램에 로그인·결제·계정 변경을 대신 하는 매크로는 만들지 않는다.

웹 페이지 매크로(좌표·그림 대신 요소로, 웹 자동화 브라우저):
1) macro_web_view(url=...) 로 페이지를 열고 누를 수 있는 요소 목록을 본다(한 줄에 요소 하나 + 바로 쓸 선택자).
   목록이 길면 filter 로 좁힌다(토큰 절약). 페이지 전체가 필요할 때만 full_page.
2) 목록의 선택자로 web 스텝을 만들어 macro_test_step 으로 하나씩 시험한다(결과로 바뀐 페이지 요소 목록이 같이 옴).
3) 확인된 스텝을 macro_save → macro_run. 코드를 새로 짜지 말고 web 스텝·조건·반복·변수를 조합한다.
엑셀·워드·한글 문서 작업은 excel / word / hwp 스텝(셀·책갈피·누름틀 이름)으로 하고 화면 클릭으로 하지 않는다.
로그인은 사람이 그 브라우저에서 미리 해 둔다. 비밀번호·카드 칸 입력은 엔진이 막는다.
"""

REFERENCE = """\
# 매크로 v2 형식 (요약)

```json
{"version": 2, "name": "이름", "window": {"title": "창 제목 일부"},
 "repeat": {"times": 1} | {"forever": true},
 "on_iteration_fail": {"action": "retry"|"stop", "max_consecutive": 3, "delay": 1.0},
 "settings": {...선택...}, "steps": [ ... ]}
```
- window 가 있으면 모든 좌표·region 은 창 클라이언트 기준. 없으면 화면 절대좌표.
- window.background: true = 뒤에서 실행. 창을 앞으로 안 가져오고(가려져 있어도 됨) 그 창만 캡처,
  진짜 마우스·초점을 쓰지 않으므로 사람이 다른 작업을 해도 됨. 대상 창이 최소화돼 있으면 그림·좌표 클릭·화면 찍기가 필요할 때
  화면에 안 보이게 되살려서 이어 가고, 끝나면 다시 최소화함(창 요소 스텝은 최소화된 채로 됨).
  최소화된 창에 클릭 없이 type_text 만 하면 일부 프로그램(엑셀·계산기)은 글자를 놓침 → 먼저 그 칸을 누를 것.
  계산기(스토어 앱)는 뒤에서 실행일 때 좌표 클릭을 무시함 → element 대상으로 누를 것.
- window.hidden: true (background 와 같이) = 숨겨서 실행. 실행하는 동안 대상 창을 화면에 안 보이게 둠.
  끝나면(오류·정지 포함) 원래대로. 시험할 때도 macro_test_step 에 hidden=true.
  키 입력(key/type_text)은 프로그램에 따라 안 먹을 수 있음(일부 게임은 Esc 안 먹음). 시험할 때도 도구에 background=true 를 준다.
- window.wrapper: false = 호환 모드. 어떤 프로그램에서 뒤에서 실행이 시작되지 않거나 보안 프로그램과 부딪힐 때 켠다.
  대신 일부 프로그램은 호환 모드에서 클릭이 안 먹을 수 있음.
- 회차가 실패하면 retry: 그 회차를 처음부터 다시(실패한 회차는 횟수에 안 셈), 연속 max_consecutive 번 실패하면 종료.

## 대상(target) — 정확히 하나
- {"image": "폴더/파일.png", "region": [x,y,w,h], "confidence": 0.8, "color_check": 0.85, "multiscale": false, "offset": [dx,dy]}
  image 는 image/ 폴더 기준 상대경로(macro_capture_template 이 돌려준 값). region 을 주면 빠르고 오인식이 적다.
- {"color": [r,g,b], "at": [x,y], "tolerance": 10}
- {"color": [r,g,b], "region": [x,y,w,h], "tolerance": 10, "min_pixels": 10}  영역 안 그 색 픽셀이 min_pixels 개 이상이면 있음(위치 = 그 픽셀들의 평균)
- {"color": [r,g,b], "region": [x,y,w,h], "tolerance": 14, "blob_depth": 10}  그 색 덩어리(안쪽 구멍 메움) 중 가장 두꺼운 곳이
  blob_depth px 이상이면 있음, 위치 = 그 안쪽 점. 안의 그림이 매번 바뀌는 말풍선·카드처럼 '틀 색'만 같은 것을 누를 때
- {"vivid": true, "region": [x,y,w,h], "min_pixels": 50, "min_saturation": 110, "min_value": 110, "hues": [[lo,hi],...]}  선명한 색 픽셀 수(H 0~180)
- {"point": [x,y]}
- {"var": "변수이름"}  (remember 로 저장한 좌표)
- {"element": {"name": "확인", "type": "button", "match": "exact|contains", "index": 0, "id": "..."}}  창 요소를 이름으로(macro_elements 목록의 target).
  name 이나 id 중 하나 필요. 창의 대화상자도 같이 찾는다. 나타날 때까지 기다림·exists·gone 조건 모두 됨. offset 가능, anchor 불가

## 조건(cond)
{"exists": <image|color 대상>} | {"gone": <대상>, "for": 초} | {"var": "v", "eq"|"ne"|"gt"|"lt"|"ge"|"le": 값} |
{"var": "v", "is_set": true} | {"not": cond} | {"all": [..]} | {"any": [..]} | {"file": {"path": "..", "exists": true}}
글자 비교: {"var": "v", "contains"|"not_contains"|"starts_with"|"ends_with": "글자"} · {"var": "v", "matches": "정규식"} · {"var": "v", "is_empty": true}.
비교 값 글자 안의 {변수} 도 바뀜. gt/lt/ge/le 는 '1,200' 같은 숫자 글자를 숫자로 비교.

## 글자 안 {변수}
점으로 안쪽 값: {행.이름}(표 한 줄의 칸), {목록.1}(첫째), {정보.크기}(파일 정보). 조건 var·계산식에서도 같음.
type_text.text · launch.target · menu.path · key.keys · snapshot.name · stop.reason · set/set_result/return 의 글자 value 안의 {이름} 은 실행 때 그 변수 값으로 바뀜(오피스·웹 칸은 원래부터). 없는 이름은 글자 그대로 두고 경고.

## 스텝 (모든 스텝 공통: on_fail "fail"(기본)|"skip"|"retry"|{"return": 값}, retries, note, foreground, 설정 키 덮어쓰기)
- foreground: true = '뒤에서 실행'(window.background) 중 이 스텝만 잠깐 앞에서(활성 창·커서를 기억 → 대상 창을 앞으로 → 진짜 입력 → 원래대로 되돌림, 실패해도 되돌림). 연달아 있는 foreground 스텝은 한 번에. 뒤에서 안 먹는 동작(메뉴줄 클릭 등)에만 쓴다. 표준 메뉴는 먼저 menu 스텝을 시도
| type | 필드 | 동작 |
|---|---|---|
| click | target, button(left/right/middle), count(1/2), timeout, verify{cond,timeout,retries} | 대상이 나타나 안정될 때까지 기다렸다 클릭. verify 가 있으면 클릭 후 조건 확인, 안 되면 재클릭 |
| move | target, timeout | 마우스 이동 |
| scroll | amount(칸, +위 -아래, 기본 -3), target(있으면 그 자리로 옮긴 뒤), horizontal | 마우스 휠 |
| menu | path ("서식 > 글꼴") | 창의 표준 메뉴 항목을 이름으로 골라 명령을 보냄. 창을 앞으로 안 가져와서 뒤에서도 됨. 표준 메뉴가 없는 프로그램이면 실패(그때는 클릭에 foreground) |
| drag | from, to, duration_ms | 드래그 |
| mouse_down / mouse_up | target(선택), button | |
| key | keys ("f", "ctrl+c", "alt+tab", "enter", "f5", "num1"), count | 키 입력 |
| type_text | text, target(element, 선택) | 문자열 입력(한글 가능, 클립보드 붙여넣기). "{이름} 님" 처럼 변수 값을 넣을 수 있음. target 에 입력 칸(element)을 주면 그 칸에 바로 넣음 — '뒤에서 실행' 중 뜬 저장 창 같은 대화상자의 칸도 됨 |
| wait | until(cond), timeout | 조건까지 대기. timeout null = 무한 |
| delay | seconds | 고정 대기 |
| remember | var, what("mouse" 또는 대상) | 좌표를 변수로 |
| set | var, value 또는 add | 변수에 값 넣기 / 숫자 더하기(없던 변수는 0부터). 조건 {"var": v, "ge": 3} 등과 같이 씀. value {"now": true} = 지금 시각(초), 조건 값에도 {"now": true, "add": -21600}(6시간 전) 처럼 씀. 이름이 '전역_'으로 시작하면 부른/불린 매크로·반복 회차가 같이 씀(맨 위 실행이 끝날 때까지) |
| text | var, text, action(set 기본/replace/extract/split/slice/trim/upper/lower/length/number/join/pad), find·with·regex, pattern·group·all, sep·index(1=첫째, -1=마지막), start(1부터)·count, width·char, list | 글자 만들기: text(안의 {변수} 채움)를 가공해 var 에. 예: {"type":"text","var":"파일명","text":"재직_{이름}_{오늘}.hwp"} / extract pattern "([\\d,]+)원" 으로 금액만 / number 로 '12,500'→12500 / split sep "," index 2. 없는 변수·못 찾음은 스텝 실패 |
| date | var, action(format 기본/diff), from(없으면 지금; '2026-11-18'·'2026.11.18'·엑셀 날짜 숫자·{변수}), add{years,months,days,hours,minutes}, format("yyyy-MM-dd" 기본; yyyy yy MM M dd d HH mm ss 요일 ddd), to·unit(days/hours/minutes) | 날짜 글자 만들기 / 두 날짜 사이(diff = to - from) |
| file | action(copy/move/rename/delete/mkdir/list/exists/info/read_text/write_text/zip/unzip/read_csv/write_csv), permanent(delete), data(write_csv: 표 변수 이름), header(read_csv, 기본 true), sep, path, to, name, overwrite(fail 기본/skip/number/replace), var, pattern("*.pdf;*.xlsx"), sub, kind(files/folders), sort(name/modified/newest), text, append, encoding | 파일·폴더. 경로 안 {변수} 바뀜, 상대 경로는 자료 폴더 기준. to 가 폴더(또는 \\ 로 끝남)면 그 안에 같은 이름으로, 없는 폴더는 만듦. delete 는 기본 휴지통, permanent=true 면 영구 삭제(되살릴 수 없음, 사람이 원할 때만). 같은 이름이 있으면 overwrite: fail(실패)·skip·number('이름 (2)')·replace(원래 것은 휴지통으로). list 는 경로 목록을 var 에(반복에 씀). info 는 {이름, 확장자, 폴더, 크기, 수정, 폴더임}. 드라이브 맨 위·윈도우 시스템 폴더 자체는 지우기·옮기기·이름 바꾸기 안 됨. 조건 {"file": {"path": "..", "exists": true}} 로 파일이 생길 때까지 기다리기 |
| clipboard | action(read/write/clear/copy/files/save_image), var, text, path, timeout | 클립보드. copy = Ctrl+C 를 누르고 새 글이 올 때까지(timeout, 기본 4초, 절반 지나면 한 번 더 누름) 기다려 var 에(먼저 비우므로 예전 글을 잘못 쓰지 않음, 안 오면 실패) · read = 지금 글을 var 에 · write = text(안의 {변수} 채움)를 넣음 · clear · files = 탐색기에서 복사한 파일 경로 목록을 var 에 · save_image = 복사한 그림을 path(PNG)로. 읽은 글은 text 단계로 가공하고 조건 contains 등으로 판단 |
| calc | var, expr | 계산: "가격 * 수량 * 1.1", "round(합계 / 3, 1)". 변수 이름을 그대로(또는 {이름}) 씀. '1,200' 같은 글자도 숫자로. + - * / // % ** 괄호, round int abs min max float 만 |
| read_number | region [x,y,w,h], var, part("first"/"second"), anchor, font, confidence | 영역의 숫자를 읽어 정수로 변수에 넣음(쉼표 제거). '3,695/9,937' 같은 분수는 앞 숫자, part "second" 면 뒤 숫자. part 를 쓰면 분수 꼴이 아닐 때 실패. 못 읽거나 일부만 읽힌 것 같으면 스텝 실패(on_fail 로 처리). 읽은 값은 조건 {"var": v, "ge": 3000} 으로 씀. font 는 숫자 조각(글꼴) 폴더(image/ 기준 경로; 넓은 영역은 느려지니 꼭 지정). 영역은 숫자 양옆으로 숫자 한 글자 폭쯤 여유를 둘 것. 말풍선이 뜨는 중(크기가 변하는 중)에는 못 읽으니 다 뜬 뒤에 읽기 |
| if | cond, within(초, 기본 0), then[], else[] | 조건 분기 |
| repeat | times N / until cond / while cond / forever true, max_times, max_seconds, steps[] | 반복 (until 은 회차 끝에 확인, while 은 시작 전) |
| each | var, list(변수 이름 또는 목록) / range{from,to,step} / rows{path,sheet,header(1; 0=없음),from,to,cols("A:D"),key_col,group_by(새 건 시작 칸, 예 "A"),group(N줄씩)} / files{path,pattern,sub,sort} / lines(글 변수), index_var, max, reverse, steps[] | 목록마다: 하나씩 var 에 넣고 steps 반복(break/continue 됨). rows = 엑셀 표의 줄(열린 파일 또는 path), 한 줄은 {제목이름: 값, "A": 값, ..., "행"(또는 "row"): 줄번호} → {행.이름}·{행.B}·조건 {"var":"행.부서","contains":"영업"}·계산 "합계 + 행.금액". files = 폴더 안 파일 경로. lines = 글을 줄마다(빈 줄 빼고). 화면 그림을 하나씩은 for_each |
| ask | kind(input/confirm/choose/file/folder), var, message, title, options(목록 또는 변수 이름, 쉼표 글), default, timeout(초) | 사람에게 묻기: 화면 프로그램으로 돌릴 때 맨 위에 창을 띄우고 답을 var 에(confirm 은 true/false). 취소하면 실패. timeout 이 지나면 default. AI(MCP)·명령 줄 실행처럼 창을 못 띄우면 default 를 쓰고(경고), default 가 없으면 실패 → AI로 시험할 때는 default 를 꼭 넣을 것 |
| notify | message, title, channels(["toast"] 기본 / "sound" / "webhook"), url, level(info/warning/error), must | 알림: 윈도우 알림·소리·메신저 웹훅(url, 없으면 settings/notify.json 의 webhook). 항상 logs/notify/notify.jsonl 에도 남김. 못 보내면 경고만(must=true 면 실패) |
| pdf | action(text 기본/extract/table), path, var, pattern·group·all(extract), index·header(table), via("word" = 워드로 열기, 보조) | PDF 읽기: 프로그램에 든 PDF 부품으로(워드 없이) 글 전체 / 규칙으로 값 뽑기 / 표를 줄 목록 [{제목: 값, "1": .., "row": n}]. 스캔(그림) PDF 는 '글자 없음'으로 실패 |
| mail | via(outlook 기본/web/server), service(web: naver/daum/nate/gmail), account(server), action(find/read/save_attachments/mark_read/move/send), var · find: mail_folder, from, subject, unread, has_attachment, days, max → 메일 목록 [{id, from, subject, date, unread, attachments}] · read/save_attachments/mark_read/move: mail(찾기 결과 변수·id) · save_attachments: path, pattern, overwrite(기본 number) → 저장 경로 목록 · move: to_folder · send: to, cc, subject, body, attachments(; 로), send_now | 메일. 보내기는 기본 '임시 보관함 저장', send_now=true 일 때만 바로 보냄(사람이 원할 때만). 보낸·저장한 것은 실행 기록에. outlook 은 켜진 데스크톱 아웃룩을 그대로(계정 필요 없음). web 은 사람이 그 브라우저에 미리 로그인해 둔 웹메일을 다루고, 로그인·인증 화면이 나오면 실패로 멈춤. server 는 설정 → 메일 계정(비밀번호는 윈도우 자격 증명에 보관) |
| list | var, action(add 기본/sort/unique/clear/count), value(add: 글자 또는 줄 {"칸": "{변수}"}; '{이름}' 하나면 원래 값), unique(add), by(sort: "날짜, 시간" 또는 [{key, order(asc/desc), as(auto/number/date/text)}]), order, to_var | 목록 변수: 하나씩 더하기·정렬(숫자·날짜·글자 자동)·같은 것 빼기·개수. 모은 목록은 excel write(cell 부터 제목 줄 포함)·file write_csv 에 그대로 |
| group | steps[] | 묶음. on_fail "skip" 과 같이 쓰면 '중간 실패 시 나머지 건너뛰고 계속' |
| break / continue | | 가장 가까운 repeat |
| call | macro, result_var | 다른 저장된 매크로 실행, 결과값 저장 |
| set_result / return | value | 결과값 지정 / 매크로 정상 종료. value 에 {"var": "이름"} 을 쓰면 그 변수 값 |
| stop | reason | 매크로 실패로 종료 |
| comment | text | 메모 |

## 웹 요소 스텝 (window 없이 씀. 웹 자동화 브라우저, 탭 p1 유지)
| web | action, selector, url, text, var, timeout(초, 기본 5), state, page, name | 아래 동작. selector·url·text 안의 {변수} 는 값으로 바뀜(예: tr:nth-child({행}) — 반복으로 표의 여러 줄 읽기) |
- goto url · click selector · fill selector + text(문자열 또는 {"var": 이름}) · select selector + text(값·보이는 글자) · close(이 매크로가 연 페이지 닫기 — 끝날 때 쓰기)
- press text(키, "Enter"·"Tab"·"Control+A") + selector(선택) · wait selector(+state visible/attached/hidden/detached)
- table selector(비우면 첫 표; CSS·xpath=) + var → 줄 목록 [{제목: 글자, "1": 첫 칸, ..., "행"/"row": 번호}] (each 로 돌거나 excel write·file write_csv 의 값으로) · download selector(링크) 또는 url + path(폴더·파일, 비우면 자료 폴더의 downloads) + overwrite(기본 number) + var(저장한 경로): 로그인된 페이지 안에서 받아 저장
- read selector + var(글자, 입력칸이면 값; CSS·xpath·text= 가능, 여러 개면 ">> nth=0"(첫째)·">> nth=-1"(마지막)) · url var · screenshot name(스냅샷 폴더에 저장)
- macro_web_view 의 선택자 뒤에 "(위치 기준…)"이 붙으면 페이지가 바뀌면 틀릴 수 있음 → 가능하면 글자(text=)나 속성 선택자를 직접 쓸 것
- 조건 {"web": {"selector": "text=로그아웃", "state": "visible"}} — if·wait·repeat 의 until/while 어디서나, all/any/not 과 섞기 가능
- 선택자: macro_web_view 가 주는 것을 그대로(#id, input[name="q"], text="정확한 글자", CSS 경로). 직접 쓸 때는
  text=글자(일부 일치) · text="정확히" · loc=role:button[name='검색'] · xpath=... · CSS. 정확히 하나만 맞아야 함(여러 개면 ">> nth=0")
- 예: [{"type":"web","action":"goto","url":"https://example.com"}, {"type":"web","action":"fill","selector":"#q","text":{"var":"검색어"}},
       {"type":"web","action":"press","selector":"#q","text":"Enter"}, {"type":"web","action":"wait","selector":"#result"},
       {"type":"web","action":"read","selector":"#result","var":"결과"}]

## 오피스 스텝 (window 없이 씀. 엑셀·워드·한글을 자동화 통로로, 화면 좌표 안 씀)
엑셀 new(새 빈 파일, sheet 이름) → write → save_as path + format(xlsx/csv/pdf) + overwrite(새 파일은 기본 fail, 연 파일은 replace; number/skip).
두 줄짜리 거래 표는 rows.group_by 로 한 건씩: {행.A}(첫 줄), {행.줄2.E}(둘째 줄).
excel·word·hwp 의 print: to_file(종이 대신 인쇄 모양 그대로 PDF 로 저장) 또는 printer(비우면 기본 프린터)·copies.
엑셀 write 의 value 에 표(줄 목록 [[..],[..]] 또는 web table·read_csv 결과)를 주면 cell 부터 한 번에 씀(제목 줄 포함).
문자열 칸 안의 {변수} 는 실행 때 변수 값으로 바뀜(예: "cell": "B{행}"). 없는 변수면 스텝 실패.
| type | action | 필드 |
|---|---|---|
| excel | open / read / write / last_row / run_macro / save / save_as / close | path, visible(창 보이기) · sheet(이름·번호, 비우면 지금 시트), cell("A1", "B{행}", "A1:C10" → 줄마다 목록), value, var · last_row: cell 에 열 글자("A") → var 에 마지막 행 번호 · run_macro: name · save_as: path(.pdf 면 PDF) |
| word | open / replace / fill_bookmark / read / save / save_as / close | path · replace: find, text(모두 바꿈) · fill_bookmark: name, text · read: name(비우면 문서 전체), var |
| hwp | open / fill_field / read_field / replace / save / save_as / close | path · fill_field: name(누름틀 이름), text · read_field: name, var · replace: find, text · save_as: path(.pdf 면 PDF) |
- 먼저 open, 끝에 save(또는 save_as)·close. 매크로가 직접 켠 프로그램은 매크로가 끝날 때 닫힘(저장 안 한 변경은 버림).
- 행 반복 예: last_row → set 행=2 → repeat while {"var":"행","le":{"var":"끝"}} [read B{행} → ... → set 행 add 1]
- 스텝 시험(macro_test_step)에서 연 문서는 같은 session 동안 유지됨. 다 끝나면 macro_reset_session 으로 닫음.

## 막히면 AI 한 번 부르기 (매크로 최상위 선택 키 ai_rescue, rescues)
- "ai_rescue": {"on": false(기본 꺼짐), "per_hour": 3, "per_day": 10, "forbid_regions": [[x,y,w,h],...](여기 누르기 금지), "forbid_words": ["글자",...](이 글자가 든 답 금지)}
- 켜면: 스텝이 재시도까지 실패해 실행이 끝나기 직전에만, 그 순간 화면 사진+직전 기록+실패 스텝을 이 컴퓨터의 명령줄 AI에 한 번 넘긴다(시간당·하루 횟수 제한). 답은 이미 있는 스텝(JSON)만 허용하고 결제·로그인 등 금지 규칙으로 거른다.
- 고친 뒤 실패했던 스텝이 통과할 때만 "rescues"(자동 저장되는 해결 규칙: step, screen, steps, added, reason, why, by)에 남고, 다음부터는 같은 스텝·비슷한 화면이면 AI 없이 그 규칙을 쓴다. rescues 는 손으로 쓰지 않는다(지우려면 키를 삭제).

## 설정 기본값 (settings 또는 스텝에서 덮어쓰기)
""" + json.dumps(DEFAULT_SETTINGS, ensure_ascii=False) + """

## 팁
- 클릭이 게임에서 무시되면 click_hold_ms(60→120), move_settle_ms(40→100)를 늘려 시험해 본다.
- 화면 전환을 기다릴 땐 delay 대신 wait{exists/gone} 를 쓴다(더 빠르고 안정적).
- 클릭 후 반응 확인이 필요하면 click.verify 를 쓴다.
"""

INSTRUCTIONS_EN = """\
A tool for building Windows screen-automation macros. It moves the real mouse and keyboard.
Workflow:
1) Read the core format and category list with macro_reference() first, then open only the categories you need with macro_reference(category=...).
2) Find the target window title with macro_list_windows, then look at it with macro_screenshot(window_title=...).
   When window_title is given, every coordinate is relative to that window's client area (same basis as the macro's window).
   The title bar and menu bar have negative y. For small buttons, zoom in with region (up to 4x) and re-read the coordinates.
3) For buttons/fields of ordinary programs (Notepad, Excel, office apps, ...), first list their names with macro_elements.
   If it is listed, use that row's element target as-is (survives resolution/scaling/theme changes — prefer it over images).
   Only when it is not listed (games, custom-drawn screens) crop and save it with macro_capture_template (use the returned path as-is in an image target).
   If a duplicate warning appears, narrow the region or crop a more distinctive part.
4) Try each step for real, one at a time, with macro_test_step and check the resulting screen.
5) Save the verified steps with macro_save, then run the whole thing with macro_run (time limit).
If the user wants to stop, call macro_stop. A human can always cut it off with Ctrl+Shift+F12.
Never build macros that log in, pay, or change account settings on behalf of the user in a game or program.

Web page macros (by element instead of coordinates/images, using the web automation browser):
1) Open the page with macro_web_view(url=...) and read the list of clickable elements (one element per line + a ready-to-use selector).
   If the list is long, narrow it with filter (saves tokens). Use full_page only when you need the whole page.
2) Build web steps from the selectors in the list and test them one at a time with macro_test_step (the changed page's element list comes back with the result).
3) Save verified steps with macro_save, then macro_run. Do not write new code; combine web steps, conditions, repeats and variables.
For Excel, Word and Hangul documents use the excel / word / hwp steps (cell, bookmark, field names), not screen clicks.
Log in by hand beforehand in that browser. The engine blocks typing into password and card fields.
"""

REFERENCE_EN = """\
# Macro v2 format (summary)

```json
{"version": 2, "name": "name", "window": {"title": "part of the window title"},
 "repeat": {"times": 1} | {"forever": true},
 "on_iteration_fail": {"action": "retry"|"stop", "max_consecutive": 3, "delay": 1.0},
 "settings": {...optional...}, "steps": [ ... ]}
```
- If window is set, all coordinates and regions are relative to the window client area. Otherwise they are absolute screen coordinates.
- window.background: true = run in the background. The window is not brought to the front (it may be covered) and only that window is captured;
  the real mouse and focus are not used, so the person can keep working. If the target window is minimized, it is brought back invisibly when
  images, point clicks or screenshots need it, and minimized again at the end (element steps work while it stays minimized).
  Typing (type_text) into a minimized window without a click first loses the text in some programs (Excel, Calculator) — click the field first.
  Calculator (a Store app) ignores point clicks in background mode — use element targets.
- window.hidden: true (with background) = run hidden. The target window stays invisible while the macro runs
  and comes back as it was at the end (also after errors or a stop). Pass hidden=true to macro_test_step when testing.
  Key input (key/type_text) may not work depending on the program (some games ignore Esc). Pass background=true to the tools when testing too.
- window.wrapper: false = compatibility mode. Use it when background mode does not start for a program or conflicts with security software. Downside: programs that separately check the mouse position or window activation may ignore the clicks.
- If an iteration fails with retry: that iteration restarts from the beginning (a failed iteration does not count toward the repeat count); after max_consecutive failures in a row it stops.

## Target - exactly one
- {"image": "folder/file.png", "region": [x,y,w,h], "confidence": 0.8, "color_check": 0.85, "multiscale": false, "offset": [dx,dy]}
  image is a path relative to the image/ folder (the value returned by macro_capture_template). A region makes it faster and reduces false matches.
- {"color": [r,g,b], "at": [x,y], "tolerance": 10}
- {"color": [r,g,b], "region": [x,y,w,h], "tolerance": 10, "min_pixels": 10}  present if at least min_pixels pixels of that color are in the region (position = mean of those pixels)
- {"color": [r,g,b], "region": [x,y,w,h], "tolerance": 14, "blob_depth": 10}  present if the thickest part of a blob of that color (inner holes filled)
  is at least blob_depth px; position = a point inside it. For speech bubbles/cards whose inner picture changes each time but whose frame color stays the same
- {"vivid": true, "region": [x,y,w,h], "min_pixels": 50, "min_saturation": 110, "min_value": 110, "hues": [[lo,hi],...]}  count of vivid-color pixels (H 0-180)
- {"point": [x,y]}
- {"var": "variable_name"}  (a coordinate stored with remember)
- {"element": {"name": "OK", "type": "button", "match": "exact|contains", "index": 0, "id": "..."}}  a window element by name (the target from macro_elements).
  Needs name or id. Also searches that program's dialogs. Works for waiting, exists and gone. offset allowed, anchor not

## Condition (cond)
{"exists": <image|color target>} | {"gone": <target>, "for": seconds} | {"var": "v", "eq"|"ne"|"gt"|"lt"|"ge"|"le": value} |
{"var": "v", "is_set": true} | {"not": cond} | {"all": [..]} | {"any": [..]} | {"file": {"path": "..", "exists": true}}
Text comparison: {"var": "v", "contains"|"not_contains"|"starts_with"|"ends_with": "text"} · {"var": "v", "matches": "regex"} · {"var": "v", "is_empty": true}.
{variables} inside comparison text are filled too. gt/lt/ge/le compare number-like text such as '1,200' as numbers.

## {variables} inside text
Dots reach inside values: {row.name} (a cell of a table row), {list.1} (first item), {info.size} (file info). Same in condition var and formulas.
{name} inside type_text.text · launch.target · menu.path · key.keys · snapshot.name · stop.reason · text values of set/set_result/return is replaced with the variable's value at run time (office and web fields always did this). Unknown names are left as is with a warning.

## Steps (common to all steps: on_fail "fail"(default)|"skip"|"retry"|{"return": value}, retries, note, foreground, overriding settings keys)
- foreground: true = while running in background (window.background), do just this step in front (remember the active window and cursor → bring the target window to front → real input → restore, even on failure). Consecutive foreground steps run as one block. Use only for actions that do not work in background (e.g. menu bar clicks). For standard menus try the menu step first
| type | fields | behavior |
|---|---|---|
| click | target, button(left/right/middle), count(1/2), timeout, verify{cond,timeout,retries} | Wait for the target to appear and settle, then click. With verify, the condition is checked after the click and the click is repeated if it does not hold |
| move | target, timeout | Move the mouse |
| scroll | amount (notches, + up - down, default -3), target (move there first if given), horizontal | Mouse wheel |
| menu | path ("Format > Font") | Pick a standard menu item by name and send its command; does not bring the window to front, so it works in background. Fails if the program has no standard menu (then use a click with foreground) |
| drag | from, to, duration_ms | Drag |
| mouse_down / mouse_up | target(optional), button | |
| key | keys ("f", "ctrl+c", "alt+tab", "enter", "f5", "num1"), count | Key input |
| type_text | text, target(element, optional) | Type a string (Korean works; done by clipboard paste). Variables can be inserted, e.g. "Dear {name}". With target = an input field (element) the text goes straight into that field — also works for dialogs (e.g. Save As) that pop up during background runs |
| wait | until(cond), timeout | Wait until the condition holds. timeout null = forever |
| delay | seconds | Fixed wait |
| remember | var, what("mouse" or a target) | Store a coordinate in a variable |
| set | var, value or add | Put a value in a variable / add a number (a missing variable starts at 0). Use with conditions like {"var": v, "ge": 3}. value {"now": true} = current time (seconds); condition values may also be {"now": true, "add": -21600} (6 hours ago). Names starting with 'global_' (global) are shared by called/calling macros and loop iterations until the top-level run ends |
| text | var, text, action(set default/replace/extract/split/slice/trim/upper/lower/length/number/join/pad), find·with·regex, pattern·group·all, sep·index(1=first, -1=last), start(from 1)·count, width·char, list | Build text: take text (with {variables} filled), transform it, store in var. E.g. {"type":"text","var":"file","text":"cert_{name}_{today}.hwp"} / extract with pattern "([\\d,]+) won" to get the amount / number turns '12,500' into 12500 / split with sep "," index 2. A missing variable or no match fails the step |
| date | var, action(format default/diff), from(default now; '2026-11-18'·'2026.11.18'·Excel date number·{variable}), add{years,months,days,hours,minutes}, format("yyyy-MM-dd" default; yyyy yy MM M dd d HH mm ss ddd), to·unit(days/hours/minutes) | Make date text / the gap between two dates (diff = to - from) |
| file | action(copy/move/rename/delete/mkdir/list/exists/info/read_text/write_text/zip/unzip/read_csv/write_csv), permanent(delete), data(write_csv: table variable name), header(read_csv, default true), sep, path, to, name, overwrite(fail default/skip/number/replace), var, pattern("*.pdf;*.xlsx"), sub, kind(files/folders), sort(name/modified/newest), text, append, encoding | Files and folders. {variables} in paths are filled; relative paths are from the data folder. If to is a folder (or ends with \\) the file keeps its name inside it; missing folders are created. delete goes to the Recycle Bin by default; permanent=true deletes permanently (cannot be restored; only when the person wants it). When the name exists, overwrite: fail · skip · number ('name (2)') · replace (the old file goes to the Recycle Bin). list puts a list of paths in var (use it in loops). info gives {name, ext, folder, size, modified, is_folder} (Korean keys too). A drive root or a Windows system folder itself cannot be deleted, moved or renamed. Wait for a file with the condition {"file": {"path": "..", "exists": true}} |
| clipboard | action(read/write/clear/copy/files/save_image), var, text, path, timeout | Clipboard. copy = press Ctrl+C and wait (timeout, default 4 s, presses once more halfway) for new text into var (it clears first, so old text is never reused; fails if nothing arrives) · read = current text into var · write = put text ({variables} filled) · clear · files = list of file paths copied in Explorer into var · save_image = save a copied picture to path (PNG). Process the text with the text step and decide with conditions such as contains |
| calc | var, expr | Calculate: "price * qty * 1.1", "round(total / 3, 1)". Use variable names directly (or {name}). Text like '1,200' counts as a number. Only + - * / // % ** parentheses and round int abs min max float |
| read_number | region [x,y,w,h], var, part("first"/"second"), anchor, font, confidence | Read the number in the region as an integer into a variable (commas removed). For fractions like '3,695/9,937' the first number is used, or the second with part "second". With part set, it fails if the text is not a fraction. If it cannot read, or seems to read only part, the step fails (handle with on_fail). Use the value in conditions like {"var": v, "ge": 3000}. font is a folder of digit glyphs (path relative to image/; wide regions get slow, so always set it). Leave about one digit of margin on each side of the number. It cannot read while a bubble is still appearing (size changing); read after it has fully shown |
| if | cond, within(seconds, default 0), then[], else[] | Conditional branch |
| repeat | times N / until cond / while cond / forever true, max_times, max_seconds, steps[] | Loop (until is checked at the end of each iteration, while before the start) |
| each | var, list(variable name or list) / range{from,to,step} / rows{path,sheet,header(1; 0=none),from,to,cols("A:D"),key_col,group_by(column where a new record starts, e.g. "A"),group(every N rows)} / files{path,pattern,sub,sort} / lines(text variable), index_var, max, reverse, steps[] | For each: puts each item in var and repeats steps (break/continue work). rows = rows of an Excel table (open file or path); a row is {header name: value, "A": value, ..., "row": row number} -> {row.name}·{row.B}·condition {"var":"row.dept","contains":"Sales"}·calc "total + row.amount". files = file paths in a folder. lines = each line of a text (empty lines skipped). For pictures on screen use for_each |
| ask | kind(input/confirm/choose/file/folder), var, message, title, options(list or variable name, comma text), default, timeout(s) | Ask a person: when run from the app it shows a window on top and puts the answer in var (confirm gives true/false). Cancel fails the step. After timeout the default is used. When no window can be shown (AI/MCP or command line), the default is used (warning); without a default it fails, so always give a default when testing with an AI |
| notify | message, title, channels(["toast"] default / "sound" / "webhook"), url, level(info/warning/error), must | Notify: Windows notification, sound, messenger webhook (url, or webhook in settings/notify.json). Always also written to logs/notify/notify.jsonl. If sending fails only a warning (fails with must=true) |
| pdf | action(text default/extract/table), path, var, pattern·group·all(extract), index·header(table), via("word" = open with Word, fallback) | Read PDF: with the PDF component built into the program (no Word) -> all text / a value by pattern / a table as a list of rows [{header: value, "1": .., "row": n}]. Scanned (picture) PDFs fail with 'no text' |
| mail | via(outlook default/web/server), service(web: naver/daum/nate/gmail), account(server), action(find/read/save_attachments/mark_read/move/send), var · find: mail_folder, from, subject, unread, has_attachment, days, max -> list of mails [{id, from, subject, date, unread, attachments}] · read/save_attachments/mark_read/move: mail (find result variable or id) · save_attachments: path, pattern, overwrite (default number) -> list of saved paths · move: to_folder · send: to, cc, subject, body, attachments (; separated), send_now | Mail. Sending saves to Drafts by default; only send_now=true sends right away (only when the person wants it). Sent/saved mail is logged. outlook uses the running desktop Outlook (no account needed). web works on webmail the person already signed in to in that browser and stops with a failure on sign-in or verification pages. server uses Settings > Mail accounts (password kept in Windows Credential Manager) |
| list | var, action(add default/sort/unique/clear/count), value(add: text or a row {"col": "{var}"}; a lone '{name}' keeps the original value), unique(add), by(sort: "date, time" or [{key, order(asc/desc), as(auto/number/date/text)}]), order, to_var | List variable: add one by one, sort (numbers/dates/text detected), remove duplicates, count. Pass the list to excel write (from cell, with header row) or file write_csv |
| group | steps[] | Group. With on_fail "skip" it means 'if something fails midway, skip the rest and continue' |
| break / continue | | Nearest enclosing repeat |
| call | macro, result_var | Run another saved macro and store its result |
| set_result / return | value | Set the result / end the macro normally. value may be {"var": "name"} to use that variable's value |
| stop | reason | End the macro as failed |
| comment | text | Note |

## Web element step (use without window. The web automation browser is used; tab p1 is kept)
| web | action, selector, url, text, var, timeout(seconds, default 5), state, page, name | actions below. {variable} inside selector, url, text is replaced by its value (e.g. tr:nth-child({row}) — read many table rows in a repeat) |
- goto url - click selector - fill selector + text (string or {"var": name}) - select selector + text (value or visible text) - close (close the page this macro opened — use at the end)
- press text (key, "Enter", "Tab", "Control+A") + selector (optional) - wait selector (+state visible/attached/hidden/detached)
- table selector (empty = first table; CSS, xpath=) + var -> list of rows [{header: text, "1": first cell, ..., "row": number}] (loop with each, or pass to excel write / file write_csv) - download selector (link) or url + path (folder or file; empty = downloads in the data folder) + overwrite (default number) + var (saved path): fetched inside the logged-in page and saved
- read selector + var (text; the value for input fields; CSS, xpath, text= allowed; for several matches use ">> nth=0" (first), ">> nth=-1" (last)) - url var - screenshot name (saved to the snapshot folder)
- If a selector from macro_web_view is followed by "(position based ...)", it may break when the page changes -> prefer a text= or attribute selector written by hand
- Condition {"web": {"selector": "text=Log out", "state": "visible"}} - usable anywhere: if, wait, until/while of repeat, and mixed with all/any/not
- Selectors: use what macro_web_view gives as-is (#id, input[name="q"], text="exact text", CSS path). When writing by hand:
  text=text (partial match) - text="exact" - loc=role:button[name='Search'] - xpath=... - CSS. It must match exactly one element (for several, add ">> nth=0")
- Example: [{"type":"web","action":"goto","url":"https://example.com"}, {"type":"web","action":"fill","selector":"#q","text":{"var":"query"}},
       {"type":"web","action":"press","selector":"#q","text":"Enter"}, {"type":"web","action":"wait","selector":"#result"},
       {"type":"web","action":"read","selector":"#result","var":"result"}]

## Office steps (use without window. Excel, Word and Hangul are automated through their automation interface; no screen coordinates)
excel new (new blank file, sheet name) -> write -> save_as path + format (xlsx/csv/pdf) + overwrite (new files default fail, opened files replace; number/skip).
For tables where one record spans two rows use rows.group_by: {row.A} (first line), {row.line2.E} (second line).
print for excel·word·hwp: to_file (save the print layout as PDF instead of paper) or printer (empty = default printer)·copies.
If excel write gets a table as value (rows [[..],[..]] or a web table / read_csv result), it writes it all at once from cell (with a header row).
A {variable} inside a string field is replaced by the variable's value at run time (e.g. "cell": "B{row}"). If the variable does not exist the step fails.
| type | action | fields |
|---|---|---|
| excel | open / read / write / last_row / run_macro / save / save_as / close | path, visible (show window) - sheet (name or number; empty = current sheet), cell ("A1", "B{row}", "A1:C10" -> list per row), value, var - last_row: cell holds a column letter ("A"), var gets the last row number - run_macro: name - save_as: path (.pdf saves as PDF) |
| word | open / replace / fill_bookmark / read / save / save_as / close | path - replace: find, text (replace all) - fill_bookmark: name, text - read: name (empty = whole document), var |
| hwp | open / fill_field / read_field / replace / save / save_as / close | path - fill_field: name (field name), text - read_field: name, var - replace: find, text - save_as: path (.pdf saves as PDF) |
- open first; save (or save_as) and close at the end. A program the macro started itself is closed when the macro ends (unsaved changes are discarded).
- Row loop example: last_row -> set row=2 -> repeat while {"var":"row","le":{"var":"end"}} [read B{row} -> ... -> set row add 1]
- Documents opened in step tests (macro_test_step) stay open for the same session. When finished, close them with macro_reset_session.

## Call an AI once when stuck (optional top-level keys ai_rescue, rescues)
- "ai_rescue": {"on": false (default off), "per_hour": 3, "per_day": 10, "forbid_regions": [[x,y,w,h],...] (never click here), "forbid_words": ["text",...] (reject answers containing this text)}
- When on: only right before a run ends because a step failed even after its retries, a screenshot of that moment + the recent run record + the failed step are handed once to the command-line AI on this computer (limited per hour and per day). The answer may only use existing steps (JSON) and is filtered by forbid rules (payment, login, etc.).
- Only if the failed step passes after the fix, it is saved to "rescues" (automatic fix rules: step, screen, steps, added, reason, why, by); next time the same step on a similar screen uses that rule without AI. Do not hand-write rescues (delete the key to clear them).

## Default settings (settings, or override per step)
""" + json.dumps(DEFAULT_SETTINGS, ensure_ascii=False) + """

## Tips
- If clicks are ignored in a game, raise click_hold_ms (60->120) and move_settle_ms (40->100) and test again.
- To wait for a screen change, use wait{exists/gone} instead of delay (faster and more stable).
- If you need to confirm the reaction to a click, use click.verify.
"""


def _pick_lang(argv=None, environ=None) -> str:
    """언어 고르기: --lang en|ko 또는 환경변수 MACRO_LANG. 없으면 윈도우 표시 언어."""
    argv = sys.argv[1:] if argv is None else argv
    environ = os.environ if environ is None else environ
    lang = (environ.get("MACRO_LANG") or "").strip().lower()
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            lang = argv[i + 1].strip().lower()
        elif a.startswith("--lang="):
            lang = a.split("=", 1)[1].strip().lower()
    if not lang:                                       # 11-23: 전 세계용 — 정하지 않았으면 윈도우 표시 언어(한국어면 ko, 아니면 en)
        try:
            import ctypes
            lang = "ko" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x12 else "en"
        except Exception:
            lang = "ko"
    return "en" if lang.startswith("en") else "ko"


LANG = _pick_lang()
if LANG == "en":
    INSTRUCTIONS, REFERENCE = INSTRUCTIONS_EN, REFERENCE_EN
from engine import i18n as _i18n                    # 실패 이유 등 엔진 글도 같은 언어로
from engine import control as _control
if not _control.IN_SERVER:                           # 화면 프로그램 안에서 불릴 땐 화면 언어를 그대로 둠
    _i18n.set_language(LANG)
from engine.i18n import t                              # 도구가 돌려주는 글 번역

mcp = MCPServer(
    name="macro_mcp",
    title=t("원스매크로 — 한 번 만들면 AI 없이 되풀이하는 윈도우 자동화"),
    instructions=INSTRUCTIONS,
)

def _d(s: str) -> str:
    """'English / 한국어' 설명에서 영어 모드면 영어 쪽만. 한국어 모드는 그대로(둘 다 보임)."""
    if LANG != "en":
        return s
    pos = 0
    while True:
        k = s.find(" / ", pos)
        if k < 0:
            return s
        head, tail = s[:k], s[k + 3:]
        if _HANGUL.search(tail) and not _HANGUL.search(head):
            return head.rstrip()
        pos = k + 3


import re as _re
_HANGUL = _re.compile("[가-힣]")

# 영어 모드에서 도구 설명으로 쓸 영어 전체 문장(한국어 모드는 함수 설명문 그대로)
EN_DOCS = {
    "macro_reference": "Macro v2 JSON format. Call with no category first (core format + category list), then open only the categories you need.",
    "macro_list_windows": "List visible windows (including dialogs); find the title for the macro's window.title and other tools' window_title.\n"
                          "client is in absolute screen coordinates. Returns: [{title, process, client:[x,y,w,h], minimized, elevated, dialog?}]",
    "macro_elements": "Named elements (buttons, fields, menu items, tabs...) of a window and its dialogs, each with a ready element target.\n"
                      "rect is window-relative when window_title is given. Returns: {count, elements:[{name, type, id, rect, enabled, target, dialog?}]}. "
                      "Screens drawn directly (like games) return an empty list -> use image targets instead.",
    "macro_screenshot": "Take a screenshot of the screen or a window, with a coordinate grid usable directly as macro coordinates.\n"
                        "The grid numbers on the top and left margins are the 'original coordinates' (window client-relative; menu bar etc. are negative), "
                        "so they can be used as macro coordinates as-is. Zoom into small buttons with region and look again.",
    "macro_find_image": "Check whether a template is found on screen now, where, its score and the runner-up score (ambiguous = confusable with another spot).\n"
                        "If ambiguous is true (the second candidate also passes both shape and color thresholds) it can be confused with another spot, so narrow the region.\n"
                        "If several identical buttons exist and any of them is fine to click, being ambiguous is OK.",
    "macro_capture_template": "Crop part of the screen and save it as image/<folder>/<name>.png, then check self-match, ambiguity and animation. "
                              "Use the returned path in an image target.\n"
                              "It also checks whether the crop is found right away, whether it is confusable with another place, and whether its score wobbles over 1 second (animation). "
                              "If recommended_confidence is returned, use that value.\n"
                              "Crop only the distinctive part (button text, icon) with as little background as possible.",
    "macro_web_view": "Open a page in the web automation browser (optional) and list clickable/typeable elements, one per line with a ready-to-use selector.\n"
                      "Each line: kind \"visible text\" -> selector. Use the selector as-is in web steps and conditions (it is chosen so that it matches exactly one element).",
    "macro_pixel": "Color [r,g,b] of one pixel; use it to build color targets and conditions.",
    "macro_test_step": "Really run one step and return success/failure, the reason (e.g. best image score), and variables. "
                       "Variables from remember persist within the same session.\n"
                       "Only put verified steps into a macro.",
    "macro_reset_session": "Clear variables (remember) accumulated in a macro_test_step session.",
    "macro_run": "Run a whole macro for real and return the result and a summary log; waits until it ends, max_seconds passes, or macro_stop / Ctrl+Shift+F12.\n"
                 "The full log is written to a trace file (JSONL).",
    "macro_stop": "Stop a running macro_run / macro_test_step (takes effect within 0.1 s).",
    "macro_list": "Saved macros. With no arguments: groups with macro names only (short). With query/group (or detail): name, group, step count, repeat, window.",
    "macro_get": "Full JSON of a saved macro.",
    "macro_validate": "Validate macro JSON format only (does not save or run); errors include their location.",
    "macro_save": "Save a macro as <name>.json in the macro store; if the format is invalid, nothing is saved and errors are returned.",
}


def _tool(name: str, title: str, **kw):
    """mcp.tool 을 감싸 영어 모드에선 제목·설명을 영어로."""
    def deco(fn):
        desc = EN_DOCS.get(name) if LANG == "en" else None
        return mcp.tool(name=name, title=t(title), description=desc, **kw)(fn)
    return deco


_env: Optional[RealEnv] = None
_contexts: Dict[str, Context] = {}
_office_sessions: Dict[str, Any] = {}     # 스텝 시험용 오피스 세션(엑셀·한글·워드 문서를 시험 사이에 유지)
_run_lock = _control.INPUT_LOCK       # 실제 입력은 한 번에 하나만(화면 프로그램의 매크로 실행과 같은 잠금)


async def _relay_async(tool: str, args: Dict[str, Any], timeout: float):
    """화면 프로그램(GUI·실행 파일)이 켜져 있으면 그쪽에 넘긴다. 없으면 None → 직접 실행.
    기다리는 동안 다른 요청(macro_stop 등)을 받을 수 있게 따로 스레드에서."""
    if _control.IN_SERVER:
        return None
    return await anyio.to_thread.run_sync(lambda: _control.relay(tool, args, timeout=float(timeout)))
_current_stop: Optional[threading.Event] = None


def env() -> RealEnv:
    global _env
    if _env is None:
        _env = RealEnv()
    return _env


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def _window_cfg(window_title: Optional[str]) -> Optional[dict]:
    return {"title": window_title} if window_title else None


class Area:
    """좌표 기준점과 캡처 범위. 좌표는 항상 '창 클라이언트 기준'(window_title 이 없으면 화면 기준).
    frame 은 창 전체(제목줄·메뉴줄·테두리 포함)를 같은 좌표계로 나타낸 것이라 x, y 가 음수일 수 있다."""

    def __init__(self, ox, oy, cw, ch, frame, desc):
        self.ox, self.oy, self.cw, self.ch = ox, oy, cw, ch
        self.frame = frame          # (x, y, w, h) 클라이언트 기준
        self.desc = desc

    def to_abs(self, r):
        return (self.ox + int(r[0]), self.oy + int(r[1]), int(r[2]), int(r[3]))

    def rel(self, p):
        return [p[0] - self.ox, p[1] - self.oy] if p else None


_capture_hidden: list = []          # [(창, 타이머)] 도구 하나가 찍는 동안만 숨겨서 되살린 창


def _release_capture_hidden():
    while _capture_hidden:
        w, tm = _capture_hidden.pop()
        tm.cancel()
        try:
            w.unhide()
        except Exception:
            pass


def _hide_for_capture(window_title: str):
    """뒤에서 찍기: 최소화된 창을 안 보이게 되살려 둔다(숨겨서 실행이 있는 판만). 3초 뒤 또는 다음 도구 호출 때 되돌림."""
    try:
        from .win_hide import supported
        if not supported():
            return
        w = Win32Window({"title": window_title, "background": True})
        w.hide()
    except Exception:
        return
    tm = threading.Timer(3.0, _release_capture_hidden)
    tm.daemon = True
    _capture_hidden.append((w, tm))
    tm.start()


def _area(window_title: Optional[str], activate: bool, background: bool = False) -> Area:
    _release_capture_hidden()
    env().vision.bind_window(None)
    if not window_title:
        x, y, w, h = env().vision.screen_rect()
        return Area(x, y, w, h, (0, 0, w, h), t("화면 전체"))
    win = Win32Window({"title": window_title})
    desc = win.describe()
    if background:
        # 그 창만 캡처(PrintWindow). 다음 도구 호출의 _area 가 다시 풀거나 묶는다
        hwnd = win.hwnd
        if ctypes.windll.user32.IsIconic(hwnd):
            _hide_for_capture(window_title)          # 최소화 → 안 보이게 되살려서 찍고 곧 다시 최소화
        env().vision.bind_window(lambda: hwnd)
        x, y, w, h = client_rect(hwnd)
        if w <= 0 or h <= 0:
            raise WindowNotFound(t("'{window_title}' 창이 최소화되어 있거나 크기가 0", window_title=window_title))
        return Area(x, y, w, h, (0, 0, w, h), desc + t(" (뒤에서 캡처)"))
    if activate:
        if win.activate() is False:
            desc += t(" ⚠ 맨 앞으로 가져오지 못함 — 다른 창에 가려진 화면일 수 있음")
        time.sleep(0.25)
    x, y, w, h = client_rect(win.hwnd)
    if w <= 0 or h <= 0:
        raise WindowNotFound(t("'{window_title}' 창이 최소화되어 있거나 크기가 0", window_title=window_title))
    r = ctypes.wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(win.hwnd, ctypes.byref(r))
    frame = (r.left - x, r.top - y, r.right - r.left, r.bottom - r.top)
    return Area(x, y, w, h, frame, desc)


def _encode(img: np.ndarray, max_width: int, zoom: bool = False) -> tuple:
    """max_width 에 맞춘다. zoom=True(일부 영역 보기)면 작은 영역을 최대 4배까지 키운다."""
    h, w = img.shape[:2]
    if not w:
        return img, 1.0
    scale = max_width / float(w)
    scale = min(scale, 4.0) if zoom else min(scale, 1.0)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    elif scale > 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
    return img, scale


GRID_MARGIN = (40, 16)   # 왼쪽, 위 여백(px) — 좌표 숫자를 화면 내용 밖에 쓴다


def _grid_image(img: np.ndarray, scale: float, step: int, x0: int, y0: int) -> np.ndarray:
    """여백을 붙이고 격자선·좌표 숫자(원래 좌표, 음수 가능)를 그린 새 이미지."""
    mx, my = GRID_MARGIN
    h, w = img.shape[:2]
    out = np.full((h + my, w + mx, 3), 255, np.uint8)
    out[my:, mx:] = img
    line, text = (0, 170, 255), (40, 40, 40)
    font = cv2.FONT_HERSHEY_SIMPLEX
    gx = -(-x0 // step) * step
    while (gx - x0) * scale < w:
        x = mx + int((gx - x0) * scale)
        cv2.line(out, (x, my), (x, h + my - 1), line, 1)
        cv2.putText(out, str(gx), (x + 2, my - 4), font, 0.36, text, 1, cv2.LINE_AA)
        gx += step
    gy = -(-y0 // step) * step
    while (gy - y0) * scale < h:
        y = my + int((gy - y0) * scale)
        cv2.line(out, (mx, y), (w + mx - 1, y), line, 1)
        cv2.putText(out, str(gy), (1, y + 4), font, 0.36, text, 1, cv2.LINE_AA)
        gy += step
    return out


def _image_of(img: np.ndarray) -> Image:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Image(data=buf.tobytes(), format="jpeg")


def _with_stop(seconds: float):
    """정지 이벤트 + 시간 제한 타이머 + 비상 정지 핫키."""
    global _current_stop
    stop = threading.Event()
    _current_stop = stop
    timer = threading.Timer(seconds, stop.set)
    timer.daemon = True
    return stop, timer


def _clear_stop() -> None:
    global _current_stop
    _current_stop = None


def _summarize(events: List[dict], limit: int = 25) -> List[str]:
    out = []
    for e in events:
        k = e["event"]
        if k == "step_end" and (e["status"] != "ok" or e["type"] in ("click", "wait", "if", "call")):
            s = f"{e['path']} {e['type']} {e['status']} {e['ms']}ms"
            if e.get("reason"):
                s += f" — {e['reason']}"
            out.append(s)
        elif k == "branch":
            out.append(t("{path} 분기 → {taken} ({detail})", path=e['path'], taken=e['taken'], detail=e['detail']))
        elif k in ("warning", "verify_failed", "step_retry", "window_activated"):
            out.append(f"{k}: {e.get('message') or e.get('reason') or e.get('detail') or e.get('target')}")
        elif k == "iteration_end" and e.get("status") == "failed":
            out.append(t("회차 {iteration} 실패: {path} — {reason}", iteration=e['iteration'],
                         path=e['error']['path'], reason=e['error']['reason']))
    return out[-limit:]


# ====================================================================== 도구: 안내

# 11-23: 설명서를 분야로 나눠 필요한 것만 읽게(전부 1.3만 자 → 처음엔 공통 핵심 + 분야 목록)
REF_CATS = [
    ("input", "입력: 누르기·움직이기·끌기·휠·메뉴·키·글자", "Input: click, move, drag, scroll, menu, keys, text",
     ["click", "move", "scroll", "menu", "drag", "mouse_down", "mouse_up", "key", "type_text"]),
    ("flow", "기다림·흐름: 기다리기·조건·반복·묶음·부르기·멈추기", "Flow: wait, if, repeat, group, call, stop",
     ["wait", "delay", "if", "repeat", "each", "for_each", "group", "break", "continue", "call", "set_result", "return",
      "stop", "comment", "launch", "wait_window", "close_window"]),
    ("data", "변수·글·계산·숫자 읽기·목록", "Data: variables, text, dates, math, read numbers, lists",
     ["remember", "set", "text", "date", "calc", "read_number", "list"]),
    ("files", "파일·클립보드·알림·묻기·메일·PDF·사진", "Files, clipboard, notify, ask, mail, PDF, snapshot",
     ["file", "clipboard", "notify", "ask", "mail", "pdf", "snapshot"]),
    ("web", "웹 요소(브라우저)", "Web elements (browser)", ["web"]),
    ("office", "오피스: 엑셀·워드·한글", "Office: Excel, Word, Hangul (HWP)", ["excel", "word", "hwp"]),
    ("advanced", "막히면 AI·설정 기본값·팁", "Stuck → AI, default settings, tips", []),
]


def _ref_parts(text: str):
    parts = text.split("\n## ")
    return [parts[0]] + ["## " + x for x in parts[1:]]


def _row_names(line: str):
    cell = line.split("|")[1].strip() if line.count("|") >= 2 else ""
    return [x.strip() for x in cell.replace("/", ",").split(",") if x.strip()]


def reference_text(category: str = "") -> str:
    """category 비움 = 공통 핵심 + 분야 목록, 'all' = 전부, 분야 이름 = 그 분야만."""
    text = REFERENCE
    parts = _ref_parts(text)
    if category == "all" or len(parts) != 10:            # 머리·대상·조건·변수·스텝·웹·오피스·막히면AI·설정·팁
        return text
    en = LANG == "en"
    head, target, cond, var, steps, web, office, ai, sett, tips = parts
    lines = steps.splitlines()
    table = [l for l in lines if l.startswith("|")]
    pre = [l for l in lines if not l.startswith("|") and l.strip()]
    hdr, rows = table[:2], table[2:]
    if not category:
        out = [head.rstrip(), target.rstrip(), cond.rstrip(), var.rstrip(), pre[0] if pre else ""]
        out.append("## Categories — open one with macro_reference(category=...), 'all' = everything" if en else
                   "## 분야 — macro_reference(category=...) 로 필요한 분야만 펼친다. 'all' 은 전부")
        for cid, ko, eng, names in REF_CATS:
            have = [n for r in rows for n in _row_names(r) if n in names] or list(names)
            out.append(f"- {cid}: {eng if en else ko}" + (f" — {', '.join(dict.fromkeys(have))}" if have else ""))
        return "\n\n".join(x for x in out if x)
    cat = next((c for c in REF_CATS if c[0] == category), None)
    if cat is None:
        return (f"Unknown category '{category}'. Use one of: " if en else f"모르는 분야 '{category}'. 다음 중 하나: ") + \
            ", ".join(c[0] for c in REF_CATS) + ", all"
    cid, ko, eng, names = cat
    out = [f"## {eng if en else ko}", pre[0] if pre else ""]
    mine = [r for r in rows if any(n in names for n in _row_names(r))]
    if mine:
        out.append("\n".join(hdr + mine))
    if cid == "web":
        out.append(web.rstrip())
    elif cid == "office":
        out.append(office.rstrip())
    elif cid == "advanced":
        known = {n for c in REF_CATS for n in c[3]}
        rest = [r for r in rows if not any(n in known for n in _row_names(r))]
        if rest:
            out.append("\n".join(hdr + rest))
        out += [ai.rstrip(), sett.rstrip(), tips.rstrip()]
    return "\n\n".join(x for x in out if x)


@_tool(name="macro_reference", title="매크로 형식 설명",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def macro_reference(
    category: Annotated[Optional[str], Field(description=_d("Empty = core format + category list (read this first). One of input/flow/data/files/web/office/advanced = only that part. 'all' = everything / 비우면 공통 형식 + 분야 목록(먼저 이것). 분야 이름이면 그 부분만, 'all' 은 전부"))] = None,
) -> str:
    """Macro v2 JSON format. Call with no category first (core format + category list), then open only the categories you need. / 매크로 v2 형식. 먼저 비워서 부르고(공통 형식 + 분야 목록), 필요한 분야만 펼친다."""
    return reference_text((category or "").strip().lower())


MEMORY_REFERENCE = """

## 메모리 매크로(부가 기능, 켜져 있음)
화면 숫자 인식 대신 대상 프로그램의 메모리 값을 읽기만 한다(읽기 전용, 쓰기 없음). 값이 정확하고 빠르다.
| 스텝 | 칸 | 설명 |
|---|---|---|
| memory | action("read"), value(저장한 이름 또는 주소), var | 값을 읽어 var 에. 주소 = {"process"?: "x.exe"(생략 시 매크로 대상 창의 프로그램), "module"?: "x.dll", "offset": 0x1234, "pointers"?: [0x10, 0x8], "kind": int32/int64/uint32/float/double/text/text16, "length"?(글자 수)} |
조건 {"memory": {"value": 이름|주소, "ge": 100}} (eq/ne/gt/lt/ge/le). 기다리기 until 에서만 {"memory": {"value": .., "changed": true}} = 처음 읽은 값에서 바뀔 때까지.
저장한 이름은 사람이 '값 찾기'로 찾아 둔 것. 이름을 모르면 화면 인식(read_number)으로 짠다.
"""

MEMORY_REFERENCE_EN = """

## Memory macro (add-on, enabled)
Reads (never writes) values from the target program's memory instead of reading numbers off the screen.
| step | fields | notes |
|---|---|---|
| memory | action("read"), value(saved name or address), var | Reads into var. address = {"process"?: "x.exe"(default: the macro's target window), "module"?: "x.dll", "offset": 0x1234, "pointers"?: [0x10, 0x8], "kind": int32/int64/uint32/float/double/text/text16, "length"?} |
Condition {"memory": {"value": name|address, "ge": 100}} (eq/ne/gt/lt/ge/le). Only in wait.until: {"memory": {"value": .., "changed": true}}.
Saved names come from the person's value finder. If you don't know a name, use screen reading (read_number).
"""


# ====================================================================== 도구: 관찰

@_tool(name="macro_list_windows", title="창 목록",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def macro_list_windows(
    title_contains: Annotated[Optional[str], Field(description=_d("Only windows whose title contains this text (optional) / 제목에 이 글자가 든 창만 (선택)"))] = None,
) -> str:
    """List visible windows (including dialogs); find the title for the macro's window.title and other tools' window_title. / 보이는 창 목록(대화상자 포함). 매크로의 window.title 과 다른 도구의 window_title 에 쓸 제목을 찾는다.
    client 는 화면 절대좌표. 반환: [{title, process, client:[x,y,w,h], minimized, elevated, dialog?}]"""
    env()
    rows = []
    for w in list_windows(include_owned=True):
        if title_contains and title_contains.lower() not in w.title.lower():
            continue
        if w.client[2] <= 0 and not w.minimized:
            continue
        el = is_process_elevated(w.pid)
        row = {"title": w.title, "process": w.process, "client": list(w.client),
               "minimized": w.minimized, "elevated": el}
        if w.owned:
            row["dialog"] = True     # 다른 창에 딸린 창(대화상자 등)
        rows.append(row)
    return _json({"server_elevated": self_elevated(), "windows": rows})


@_tool(name="macro_elements", title="창 요소 목록",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
async def macro_elements(
    window_title: Annotated[Optional[str], Field(description=_d("Part of the target window title (omit = foreground window) / 대상 창 제목 일부 (없으면 맨 앞 창)"))] = None,
    filter: Annotated[Optional[str], Field(description=_d("Only rows whose name or type contains this text (saves tokens) / 이름이나 종류에 이 글자가 든 줄만 (토큰 절약)"))] = None,
    types: Annotated[Optional[List[str]], Field(description=_d("Only these types, e.g. [\"button\", \"edit\"] / 이 종류만"))] = None,
) -> str:
    """Named elements (buttons, fields, menu items, tabs...) of a window and its dialogs, each with a ready element target. / 창(과 그 대화상자)의 이름 있는 요소 목록. 줄마다 바로 쓸 element 대상이 붙는다.
    rect 는 window_title 을 주면 창 기준. 반환: {count, elements:[{name, type, id, rect, enabled, target, dialog?}]}. 게임처럼 직접 그린 화면은 비어 있다 → 그림 대상을 쓴다."""
    def work():
        from . import win_uia
        if not win_uia.available():
            return {"error": t("창 요소 찾기 부품이 없음")}
        hwnd, ox, oy = None, 0, 0
        if window_title:
            info = find_window({"title": window_title})
            hwnd = info.hwnd
            ox, oy = info.client[0], info.client[1]
        rows = win_uia.list_elements(hwnd, filter or "", types)
        for r in rows:
            r["rect"] = [r["rect"][0] - ox, r["rect"][1] - oy, r["rect"][2], r["rect"][3]]
            if not r.get("dialog"):
                r.pop("dialog", None)
            if not r.get("id"):
                r.pop("id", None)
        return {"count": len(rows), "elements": rows}
    try:
        return _json(await anyio.to_thread.run_sync(work))
    except Exception as e:
        return t("오류: {e}", e=e)


@_tool(name="macro_screenshot", title="화면 보기",
          annotations=ToolAnnotations(read_only_hint=True))
async def macro_screenshot(
    window_title: Annotated[Optional[str], Field(description=_d("Part of the target window title; if given, the window is brought to front and coordinates are client-relative / 대상 창 제목 일부. 주면 그 창을 앞으로 가져와 캡처하고 좌표는 창 클라이언트 기준"))] = None,
    region: Annotated[Optional[List[int]], Field(description=_d("[x,y,w,h] view and zoom only this part (window-relative, may be negative) / 일부만 확대해서 보기 (창 기준, 음수 가능)"))] = None,
    include_frame: Annotated[bool, Field(description=_d("Include title bar, menu bar and border (negative y) / 제목줄·메뉴줄·테두리까지 보기 (이 부분은 y 가 음수)"))] = True,
    grid: Annotated[bool, Field(description=_d("Show coordinate grid and numbers / 좌표 격자·숫자 표시"))] = True,
    grid_step: Annotated[int, Field(ge=20, le=1000, description=_d("Grid spacing (original coordinate px) / 격자 간격(원래 좌표 px)"))] = 100,
    max_width: Annotated[int, Field(ge=200, le=1920, description=_d("Maximum width of the returned image / 돌려줄 이미지 최대 너비"))] = 1280,
    background: Annotated[bool, Field(description=_d("Background: capture only that window without bringing it to front (may be covered; a minimized window is brought back invisibly for the capture); same as the macro's window.background / 뒤에서: 창을 앞으로 안 가져오고 그 창만 캡처(가려져 있어도 됨, 최소화돼 있으면 안 보이게 되살려서 찍음). 매크로의 window.background 와 같게"))] = False,
) -> list:
    """Take a screenshot of the screen or a window, with a coordinate grid usable directly as macro coordinates. / 현재 화면을 이미지로 본다. 위·왼쪽 여백의 격자 숫자가 '원래 좌표'(창 클라이언트 기준, 메뉴줄 등은 음수)라
    그대로 매크로 좌표로 쓸 수 있다. 작은 버튼은 region 으로 확대해서 다시 본다."""
    _r = await _relay_async('macro_screenshot', dict(locals()), 120)      # 화면 프로그램이 켜져 있으면 그쪽이 처리(뒤에서 실행이 한 곳에서만)
    if _r is not None:
        return _r
    if region is not None and (len(region) != 4 or region[2] <= 0 or region[3] <= 0):
        return [t("오류: region 은 [x,y,w,h] (너비·높이 > 0)")]

    def work():
        a = _area(window_title, activate=True, background=background)
        if region:
            rx, ry, rw, rh = region
        elif include_frame:
            rx, ry, rw, rh = a.frame
        else:
            rx, ry, rw, rh = 0, 0, a.cw, a.ch
        v = env().vision
        v.new_frame()
        img = v.grab(a.to_abs((rx, ry, rw, rh))).copy()
        if img.size == 0:
            raise ValueError(t("캡처 영역이 화면 밖"))
        img, scale = _encode(img, max_width, zoom=bool(region))
        basis = t("창 클라이언트 기준(제목줄·메뉴줄은 y<0)") if window_title else t("화면 절대좌표")
        if grid:
            img = _grid_image(img, scale, grid_step, rx, ry)
            mx, my = GRID_MARGIN
            how = t("격자 숫자를 그대로 좌표로 읽는다. 계산식: x = (이미지x − {mx}) ÷ {scale:.3f} + {rx}, "
                    "y = (이미지y − {my}) ÷ {scale:.3f} + {ry}", mx=mx, my=my, scale=scale, rx=rx, ry=ry)
        else:
            how = t("x = 이미지x ÷ {scale:.3f} + {rx}, y = 이미지y ÷ {scale:.3f} + {ry}", scale=scale, rx=rx, ry=ry)
        info = t("대상: {desc} | 좌표: {basis} | 클라이언트 크기 {cw}x{ch} | "
                 "보여준 영역 [{rx},{ry},{rw},{rh}] | {how}", desc=a.desc, basis=basis, cw=a.cw, ch=a.ch,
                 rx=rx, ry=ry, rw=rw, rh=rh, how=how)
        return [info, _image_of(img)]
    try:
        return await anyio.to_thread.run_sync(work)
    except (WindowNotFound, ValueError) as e:
        return [t("오류: {e}", e=e)]


@_tool(name="macro_find_image", title="이미지 찾기 시험",
          annotations=ToolAnnotations(read_only_hint=True))
async def macro_find_image(
    image: Annotated[str, Field(description=_d("Path relative to image/ (e.g. 'mcp/ok_button.png') / image/ 기준 상대경로"))],
    window_title: Annotated[Optional[str], Field(description=_d("Part of the target window title / 대상 창 제목 일부"))] = None,
    region: Annotated[Optional[List[int]], Field(description=_d("[x,y,w,h] search range (window-relative); omit for the whole window incl. menu bar / 찾을 범위 (창 기준). 생략하면 창 전체(메뉴줄 포함)"))] = None,
    confidence: Annotated[float, Field(ge=0.3, le=1.0)] = 0.8,
    color_check: Annotated[Optional[float], Field(ge=0.0, le=1.0, description=_d("Color-check threshold; null disables / 색 검사 기준, null 이면 끔"))] = 0.85,
    multiscale: bool = False,
    background: Annotated[bool, Field(description=_d("Background: capture only that window without bringing it to front (may be covered; a minimized window is brought back invisibly for the capture); same as the macro's window.background / 뒤에서: 창을 앞으로 안 가져오고 그 창만 캡처(가려져 있어도 됨, 최소화돼 있으면 안 보이게 되살려서 찍음). 매크로의 window.background 와 같게"))] = False,
) -> str:
    """Check whether a template is found on screen now, where, its score and the runner-up score (ambiguous = confusable with another spot). / 템플릿이 지금 화면에서 찾아지는지, 어디인지, 점수와 '두 번째로 비슷한 곳' 점수를 확인한다.
    ambiguous 가 true(두 번째 후보가 모양·색 모두 기준 이상)면 다른 곳과 헷갈리므로 region 을 좁힌다.
    같은 버튼이 여러 개 있는 경우(아무거나 눌러도 되는 경우)는 헷갈려도 괜찮다."""
    _r = await _relay_async('macro_find_image', dict(locals()), 120)      # 화면 프로그램이 켜져 있으면 그쪽이 처리(뒤에서 실행이 한 곳에서만)
    if _r is not None:
        return _r
    def work():
        a = _area(window_title, activate=True, background=background)
        v = env().vision
        v.new_frame()
        abs_region = a.to_abs(region if region else a.frame)
        m = v.match(image, abs_region, {"confidence": confidence, "color_check": color_check,
                                        "multiscale": multiscale})
        second, spos, second_color = v.runner_up(image, abs_region)
        cc = color_check if color_check is not None else 0.0
        return {"found": m.found, "pos": a.rel(m.pos), "score": round(m.score, 3),
                "second_score": round(second, 3), "second_pos": a.rel(spos),
                "second_color": round(second_color, 3),
                "ambiguous": second >= confidence and second_color >= cc, "window": a.desc,
                "coords": t("창 기준") if window_title else t("화면")}
    try:
        return _json(await anyio.to_thread.run_sync(work))
    except Exception as e:
        return t("오류: {e}", e=e)


@_tool(name="macro_capture_template", title="템플릿 저장",
          annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
async def macro_capture_template(
    name: Annotated[str, Field(min_length=1, max_length=60, description=_d("File name without extension, e.g. 'ok_button' / 파일 이름(확장자 없이)"))],
    region: Annotated[List[int], Field(description=_d("[x,y,w,h] area to crop (window-relative if window_title is given) / 자를 영역 (window_title 을 주면 창 기준)"))],
    window_title: Annotated[Optional[str], Field(description=_d("Part of the target window title / 대상 창 제목 일부"))] = None,
    folder: Annotated[str, Field(description=_d("Folder under image/ / image/ 아래 폴더"))] = "mcp",
    overwrite: bool = False,
    background: Annotated[bool, Field(description=_d("Background: capture only that window without bringing it to front (may be covered; a minimized window is brought back invisibly for the capture); same as the macro's window.background / 뒤에서: 창을 앞으로 안 가져오고 그 창만 캡처(가려져 있어도 됨, 최소화돼 있으면 안 보이게 되살려서 찍음). 매크로의 window.background 와 같게"))] = False,
) -> list:
    """Crop part of the screen and save it as image/<folder>/<name>.png, then check self-match, ambiguity and animation. Use the returned path in an image target. / 화면 일부를 잘라 image/<folder>/<name>.png 로 저장하고, 바로 찾아지는지·다른 곳과 헷갈리는지·
    1초 동안 점수가 흔들리는지(애니메이션) 검사한다. recommended_confidence 가 나오면 그 값을 쓴다.
    반환된 path 를 image 대상에 그대로 쓴다. 버튼 글자·아이콘처럼 특징적인 부분만, 배경은 적게 자른다."""
    _r = await _relay_async('macro_capture_template', dict(locals()), 120)      # 화면 프로그램이 켜져 있으면 그쪽이 처리(뒤에서 실행이 한 곳에서만)
    if _r is not None:
        return _r
    bad = set('\\/:*?"<>|')
    if any(c in bad for c in name + folder.replace("/", "")) or ".." in folder:
        return [t("오류: 이름·폴더에 쓸 수 없는 문자가 있음")]
    if len(region) != 4 or region[2] < 4 or region[3] < 4:
        return [t("오류: region 은 [x,y,w,h], 너비·높이 4px 이상")]
    rel_path = f"{folder.strip('/')}/{name}.png"
    path = os.path.join(IMAGE_ROOT, *rel_path.split("/"))
    if os.path.exists(path) and not overwrite:
        return [t("오류: 이미 있음 ({rel_path}). overwrite=true 로 덮어쓰거나 다른 이름을 쓴다", rel_path=rel_path)]

    def work():
        a = _area(window_title, activate=True, background=background)
        v = env().vision
        v.new_frame()
        abs_region = a.to_abs(region)
        v.save_region(abs_region, path)
        whole = a.to_abs(a.frame)
        chk = check_template(v, rel_path, whole)
        result = {"path": rel_path, "size": [region[2], region[3]], "self_match": chk["self_match"],
                  "self_score": chk["self_score"], "found_at": a.rel(chk["found_at"]),
                  "second_score": chk["second_score"], "second_pos": a.rel(chk["second_pos"]),
                  "second_color": chk["second_color"]}
        for k in ("score_range_1s", "animated", "recommended_confidence", "note", "warning"):
            if k in chk:
                result[k] = chk[k]
        preview = cv2.resize(v.grab(abs_region), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST) \
            if max(region[2], region[3]) < 200 else v.grab(abs_region)
        return [_json(result), _image_of(preview)]
    try:
        return await anyio.to_thread.run_sync(work)
    except Exception as e:
        return [t("오류: {e}", e=e)]


def _web_lines(r: dict) -> str:
    if not r.get("ok"):
        return t("페이지 보기 실패: {error}", error=r.get('error'))
    v = r.get("value") or {}
    head = t("[{title}] {url} — 요소 {count}개", title=v.get('title', ''), url=r.get('url', ''), count=v.get('count', 0))
    return head + "\n" + "\n".join(v.get("items", []))


@_tool(name="macro_web_view", title="웹 페이지 보기",
          annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True))
async def macro_web_view(
    url: Annotated[Optional[str], Field(description=_d("Open this URL first (omit to keep the current page) / 이 주소를 먼저 연다(없으면 지금 페이지 그대로)"))] = None,
    filter: Annotated[Optional[str], Field(description=_d("Only elements whose text/kind contains this (e.g. 'search', 'input', 'login') / 글자·종류에 이 말이 들어간 요소만"))] = None,
    full_page: Annotated[bool, Field(description=_d("Include off-screen (scrolled-out) elements / 화면 밖(스크롤 아래)까지 전부"))] = False,
    limit: Annotated[int, Field(ge=1, le=300, description=_d("Maximum number of lines / 최대 줄 수"))] = 60,
    screenshot: Annotated[bool, Field(description=_d("Also return a page screenshot (token-heavy; only when needed) / 페이지 사진도 같이(토큰 많이 씀, 꼭 필요할 때만)"))] = False,
    page: Annotated[str, Field(description=_d("Tab name (default p1) / 탭 이름(기본 p1)"))] = "p1",
) -> list:
    """Open a page in the web automation browser (optional) and list clickable/typeable elements, one per line with a ready-to-use selector. / 웹 자동화 브라우저의 페이지를 열고(선택) 누르거나 입력할 수 있는 요소를 한 줄씩 돌려준다.
    각 줄: 종류 "보이는 글자" → 선택자. 선택자는 web 스텝·조건에 그대로 쓴다(하나만 맞는 것으로 골라 줌)."""
    from .web import EgoWeb
    w = EgoWeb()

    def work():
        out = []
        if url:
            g = w.run("goto", url=url, page=page, timeout_ms=20000)
            if not g.get("ok"):
                return [t("열기 실패: {error}", error=g.get('error'))], None
        r = w.run("elements", page=page, filter=filter or "", limit=limit, full=full_page)
        out.append(_web_lines(r))
        shot = None
        if screenshot:
            fp = os.path.join(TRACE_ROOT, "..", "snapshots", time.strftime("%Y%m%d_%H%M%S") + "_webview.png")
            fp = os.path.abspath(fp)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            sr = w.run("screenshot", page=page, path=fp)
            if sr.get("ok"):
                shot = fp
        return out, shot

    out, shot = await anyio.to_thread.run_sync(work)
    if shot:
        img = cv2.imdecode(np.fromfile(shot, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            img, _ = _encode(img, 1024)
            out.append(_image_of(img))
    return out


@_tool(name="macro_pixel", title="픽셀 색",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
async def macro_pixel(
    x: int, y: int,
    window_title: Annotated[Optional[str], Field(description=_d("Part of the target window title (coordinates become window-relative) / 대상 창 제목 일부 (주면 창 기준 좌표)"))] = None,
    background: Annotated[bool, Field(description=_d("Background: capture only that window without bringing it to front (may be covered; a minimized window is brought back invisibly for the capture); same as the macro's window.background / 뒤에서: 창을 앞으로 안 가져오고 그 창만 캡처(가려져 있어도 됨, 최소화돼 있으면 안 보이게 되살려서 찍음). 매크로의 window.background 와 같게"))] = False,
) -> str:
    """Color [r,g,b] of one pixel; use it to build color targets and conditions. / 한 점의 색 [r,g,b]. color 대상·조건을 만들 때 쓴다."""
    _r = await _relay_async('macro_pixel', dict(locals()), 120)      # 화면 프로그램이 켜져 있으면 그쪽이 처리(뒤에서 실행이 한 곳에서만)
    if _r is not None:
        return _r
    def work():
        a = _area(window_title, activate=False, background=background)
        v = env().vision
        v.new_frame()
        return {"x": x, "y": y, "rgb": list(v.pixel(a.ox + x, a.oy + y))}
    try:
        return _json(await anyio.to_thread.run_sync(work))
    except Exception as e:
        return t("오류: {e}", e=e)


# ====================================================================== 도구: 시험·실행

@_tool(name="macro_test_step", title="스텝 하나 시험",
          annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True))
async def macro_test_step(
    step: Annotated[Optional[Dict[str, Any]], Field(description=_d("One v2 step (macro_reference format); really moves the mouse/keyboard / v2 스텝 하나. 실제로 마우스·키보드를 움직임"))] = None,
    steps: Annotated[Optional[List[Dict[str, Any]]], Field(description=_d("Several steps run in order in one call (instead of step) / 여러 스텝을 한 번에 차례로(step 대신)"))] = None,
    window_title: Annotated[Optional[str], Field(description=_d("Window used as coordinate basis (same as the macro's window.title) / 좌표 기준 창 (저장할 매크로의 window.title 과 같게)"))] = None,
    settings: Annotated[Optional[Dict[str, Any]], Field(description=_d("Override settings (e.g. {\"click_hold_ms\": 120}) / 설정 덮어쓰기"))] = None,
    session: Annotated[str, Field(description=_d("Session name that keeps variables (remember) between calls / 변수(remember)를 이어 쓸 세션 이름"))] = "default",
    max_seconds: Annotated[float, Field(gt=0, le=300, description=_d("Force stop after this many seconds / 이 시간이 지나면 강제 정지"))] = 30,
    screenshot_after: Annotated[bool, Field(description=_d("Also return the screen after running (with grid) / 실행 뒤 화면을 같이 돌려줌 (격자 포함)"))] = True,
    screenshot_delay: Annotated[float, Field(ge=0, le=10, description=_d("Seconds to wait before the after-screenshot (time for dialogs/transitions to draw) / 실행 뒤 화면을 찍기 전 대기(초)"))] = 0.6,
    background: Annotated[bool, Field(description=_d("Run in background: no bringing the window to front, no real mouse; needs window_title / 뒤에서 실행: 창을 앞으로 안 가져오고 진짜 마우스도 안 씀. window_title 필요"))] = False,
    wrapper: Annotated[bool, Field(description=_d("With background, false = compatibility mode; same as the macro's window.wrapper / background 일 때 false = 호환 모드"))] = True,
    hidden: Annotated[bool, Field(description=_d("With background, true = run hidden (window invisible while running); same as the macro's window.hidden / background 일 때 true = 숨겨서 실행"))] = False,
) -> list:
    """Really run one step and return success/failure, the reason, and variables. Variables from remember persist within the same session. / 스텝 하나를 실제로 실행해 본다. 성공/실패, 실패 이유(이미지 최고 점수 등), 변수를 돌려준다.
    같은 session 이면 remember 한 변수가 다음 호출에도 남는다. 확인된 스텝만 매크로에 넣는다."""
    if step is None and steps:                       # 11-23: 여러 스텝을 한 번에(왕복 줄이기) → 묶음 스텝 하나로
        step = {"type": "group", "steps": list(steps)}
    if step is None:
        return [t("형식 오류:\n- ") + t("step 또는 steps 가 필요함")]
    _args = dict(locals())
    _args.pop("steps", None)
    _r = await _relay_async('macro_test_step', _args, max_seconds + 60)      # 화면 프로그램이 켜져 있으면 그쪽이 처리(뒤에서 실행이 한 곳에서만)
    if _r is not None:
        return _r
    c = _Checker()
    c.step("step", step, 1)
    if c.errors:
        return [t("형식 오류:\n- ") + "\n- ".join(c.errors)]
    fields = {"window": _window_cfg(window_title)} if window_title else {}
    if background and window_title:
        fields["window"]["background"] = True
        if not wrapper:
            fields["window"]["wrapper"] = False
        if hidden:
            fields["window"]["hidden"] = True
    if settings:
        fields["settings"] = settings
    macro = new_macro("step_test", [], **fields)
    errs = validate_macro(macro)
    if errs:
        return [t("형식 오류:\n- ") + "\n- ".join(errs)]
    from .inputs import uses_input                 # 입력(마우스·키보드)을 안 쓰는 스텝은 다른 실행과 같이 돌아도 됨
    locked = uses_input(macro, lambda n: env().library.load(n))
    if locked and not _run_lock.acquire(blocking=False):
        return [t("오류: 다른 실행이 진행 중. macro_stop 으로 멈추거나 끝날 때까지 기다린다")]
    events: List[dict] = []
    try:
        ctx = _contexts.setdefault(session, Context())
        runner = env().runner(macro, on_event=events.append)
        from .office import OfficeSession
        if session not in _office_sessions:                                      # 시험 사이에 열린 문서 유지
            _office_sessions[session] = OfficeSession()
        runner.office = _office_sessions[session]
        runner._office_owner = False
        stop, timer = _with_stop(max_seconds)

        def work():
            timer.start()
            with EmergencyStop(stop, DEFAULT_EMERGENCY_HOTKEY):
                return runner.run_step(step, ctx, stop)

        t0 = time.time()
        out = await anyio.to_thread.run_sync(work)
        timer.cancel()
        out["seconds"] = round(time.time() - t0, 2)
        if stop.is_set() and out["status"] == "stopped":
            out["note"] = t("시간 제한 또는 정지 요청으로 멈춤")
        out["log"] = _summarize(events)
        result: list = [_json(out)]
        if step.get("type") == "web" or "\"web\"" in json.dumps(step, ensure_ascii=False):
            if screenshot_after:
                from .web import EgoWeb
                n = 40 if out.get("status") != "ok" else 12
                r = await anyio.to_thread.run_sync(lambda: EgoWeb().run("elements", page=step.get("page", "p1"), limit=n))
                more = "" if n == 40 else t("\n(성공이라 12줄만. 더 보려면 macro_web_view, 좁히려면 filter)")
                result.append(t("시험 뒤 페이지 요소:\n") + _web_lines(r) + more)
            return result
        if screenshot_after:
            await anyio.sleep(screenshot_delay)
            shot = await macro_screenshot(window_title=window_title, grid=True, max_width=1024,
                                          background=background)
            result.append(shot[0])
            result.extend(shot[1:])
        return result
    finally:
        _clear_stop()
        if locked:
            _run_lock.release()


@_tool(name="macro_reset_session", title="시험 변수 초기화",
          annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
def macro_reset_session(session: str = "default") -> str:
    """Clear variables (remember) accumulated in a macro_test_step session. / macro_test_step 세션에 쌓인 변수(remember)를 지운다."""
    _r = _control.relay('macro_reset_session', dict(locals()))      # 화면 프로그램이 켜져 있으면 그쪽이 처리
    if _r is not None:
        return _r
    _contexts.pop(session, None)
    sess = _office_sessions.pop(session, None)
    if sess is not None:
        sess.shutdown()                   # 시험하며 켠 엑셀·한글·워드를 닫음(저장 안 함)
    return t("세션 '{session}' 초기화(시험하며 켠 오피스 프로그램도 닫음)", session=session)


@_tool(name="macro_run", title="매크로 실행",
          annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True))
async def macro_run(
    name: Annotated[Optional[str], Field(description=_d("Saved macro name (either this or macro) / 저장된 매크로 이름 (macro 와 둘 중 하나)"))] = None,
    macro: Annotated[Optional[Dict[str, Any]], Field(description=_d("Run an unsaved macro JSON directly / 저장하지 않은 매크로 JSON 을 바로 실행"))] = None,
    max_seconds: Annotated[float, Field(gt=0, le=3600, description=_d("Stop after this many seconds (also ends forever-loop macros) / 이 시간이 지나면 정지 (무한 반복 매크로도 여기서 끊김)"))] = 60,
    times: Annotated[Optional[int], Field(ge=1, le=1000, description=_d("Run with the repeat setting replaced by this count (for testing) / 반복 설정을 이 횟수로 바꿔서 실행 (시험용)"))] = None,
) -> str:
    """Run a whole macro for real and return the result and a summary log; waits until it ends, max_seconds passes, or macro_stop / Ctrl+Shift+F12. / 매크로 전체를 실제로 실행하고 결과·요약 기록을 돌려준다. 끝나거나 max_seconds 가 지나거나
    macro_stop / Ctrl+Shift+F12 로 멈출 때까지 기다린다. 전체 기록은 trace 파일(JSONL)에 남는다."""
    _r = await _relay_async('macro_run', dict(locals()), max_seconds + 60)      # 화면 프로그램이 켜져 있으면 그쪽이 처리(뒤에서 실행이 한 곳에서만)
    if _r is not None:
        return _r
    try:
        if macro is not None:
            data = ensure_valid(macro)
        elif name:
            data = env().library.load(name)
        else:
            return t("오류: name 또는 macro 중 하나가 필요")
    except MacroNotFound:
        return t("오류: 매크로 '{name}' 없음. macro_list 로 이름 확인", name=name)
    except MacroError as e:
        return t("형식 오류:\n- ") + "\n- ".join(e.errors)
    if times:
        data = dict(data, repeat={"times": times})
    from .inputs import uses_input
    locked = uses_input(data, lambda n: env().library.load(n))
    if locked and not _run_lock.acquire(blocking=False):
        return t("오류: 다른 실행이 진행 중(마우스·키보드를 쓰는 매크로는 한 번에 하나). macro_stop 으로 멈추거나 끝날 때까지 기다린다")
    events: List[dict] = []
    try:
        jt = JsonlTrace(trace_path(TRACE_ROOT, data["name"]))
        runner = env().runner(data, on_event=fanout(jt, events.append))
        stop, timer = _with_stop(max_seconds)

        def work():
            timer.start()
            with EmergencyStop(stop, DEFAULT_EMERGENCY_HOTKEY):
                return runner.run(stop)

        res = await anyio.to_thread.run_sync(work)
        timer.cancel()
        jt.close()
        out = res.to_dict()
        if res.status == "stopped":
            out["note"] = t("정지됨 (시간 제한 {seconds}초, macro_stop 또는 비상 정지 핫키)", seconds=max_seconds)
        out["log"] = _summarize(events)
        vars_seen: Dict[str, Any] = {}
        for e in events:
            if e.get("event") in ("set", "read") and e.get("var"):
                v = e.get("value")
                vars_seen[e["var"]] = (v[:300] + "…") if isinstance(v, str) and len(v) > 300 else v
        if vars_seen:
            out["vars"] = vars_seen          # 실행 중 넣은 변수의 마지막 값(긴 글자는 300자까지)
        out["trace"] = jt.path
        return _json(out)
    finally:
        _clear_stop()
        if locked:
            _run_lock.release()


@_tool(name="macro_stop", title="실행 정지",
          annotations=ToolAnnotations(read_only_hint=False, idempotent_hint=True))
def macro_stop() -> str:
    """Stop a running macro_run / macro_test_step (takes effect within 0.1 s). / 진행 중인 macro_run / macro_test_step 을 멈춘다(0.1초 안에 반영)."""
    _r = _control.relay('macro_stop', dict(locals()))      # 화면 프로그램이 켜져 있으면 그쪽 실행도 멈춤
    if _current_stop is None or _current_stop.is_set():
        return _r if _r is not None else t("진행 중인 실행 없음")
    _current_stop.set()
    return t("정지 요청함")


# ====================================================================== 도구: 저장소

def _groups_path() -> str:
    return os.path.join(MACRO_ROOT, "_groups.json")


def _load_groups() -> Dict[str, List[str]]:
    try:
        with open(_groups_path(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@_tool(name="macro_list", title="매크로 목록",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def macro_list(
    query: Annotated[Optional[str], Field(description=_d("Only macros whose name contains this / 이름에 이 글자가 든 것만"))] = None,
    group: Annotated[Optional[str], Field(description=_d("Only this group / 이 그룹만"))] = None,
    detail: Annotated[bool, Field(description=_d("true = details for every macro (long) / true = 모든 매크로 자세히(길어짐)"))] = False,
) -> str:
    """Saved macros. With no arguments: groups with macro names only (short). With query/group (or detail): name, group, step count, repeat, window. / 저장된 매크로. 인자 없이: 그룹별 이름만(짧게). query·group 을 주면 자세히."""
    lib = env().library
    groups = _load_groups()
    where = {m: g for g, ms in groups.items() for m in ms}
    names = list(lib.names())
    if not (query or group or detail):                 # 11-23: 매크로가 많아도 짧게 — 그룹별 이름만
        by: Dict[str, list] = {}
        for n in names:
            by.setdefault(where.get(n) or "", []).append(n)
        return _json({"count": len(names), "groups": [{"group": g, "count": len(v), "names": v} for g, v in by.items()],
                      "hint": t("자세히: macro_list(query=이름 일부) 또는 macro_list(group=그룹), 한 개 전체: macro_get(name)")})
    q = (query or "").lower()
    names = [n for n in names if (not q or q in n.lower()) and (not group or where.get(n) == group)]
    rows = []
    for n in names:
        try:
            d = lib.load(n)
            rows.append({"name": n, "group": where.get(n), "steps": len(d["steps"]),
                         "repeat": d.get("repeat"), "window": d.get("window")})
        except MacroError as e:
            rows.append({"name": n, "error": e.errors[:3]})
    return _json(rows)


@_tool(name="macro_get", title="매크로 보기",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def macro_get(name: str) -> str:
    """Full JSON of a saved macro. / 저장된 매크로의 전체 JSON."""
    try:
        return _json(env().library.load(name))
    except MacroNotFound:
        return t("오류: 매크로 '{name}' 없음", name=name)
    except MacroError as e:
        return t("형식 오류:\n- ") + "\n- ".join(e.errors)


@_tool(name="macro_validate", title="매크로 검사",
          annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def macro_validate(macro: Dict[str, Any]) -> str:
    """Validate macro JSON format only (does not save or run); errors include their location. / 매크로 JSON 형식 검사만 (저장·실행 안 함). 오류는 위치와 함께 돌려준다."""
    errs = validate_macro(macro)
    return t("정상") if not errs else t("형식 오류:\n- ") + "\n- ".join(errs)


@_tool(name="macro_save", title="매크로 저장",
          annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
def macro_save(
    macro: Annotated[Dict[str, Any], Field(description=_d("v2 macro JSON (version 2, name, steps required) / v2 매크로 JSON (version 2, name, steps 필수)"))],
    group: Annotated[Optional[str], Field(description=_d("Group name (optional) / 그룹 이름 (선택)"))] = None,
    overwrite: Annotated[bool, Field(description=_d("Overwrite if the same name exists / 같은 이름이 있으면 덮어쓰기"))] = False,
) -> str:
    """Save a macro as <name>.json in the macro store; if the format is invalid, nothing is saved and errors are returned. / 매크로를 매크로 저장 폴더에 <이름>.json 으로 저장한다. 형식 오류가 있으면 저장하지 않고 오류를 돌려준다."""
    errs = validate_macro(macro)
    if errs:
        return t("형식 오류 (저장 안 함):\n- ") + "\n- ".join(errs)
    lib = env().library
    try:
        path = lib.path_for(macro["name"])
    except ValueError as e:
        return t("오류: {e}", e=e)
    if os.path.exists(path) and not overwrite:
        return t("오류: '{name}' 이미 있음. overwrite=true 로 덮어쓰기", name=macro['name'])
    lib.save(macro)
    if group:
        groups = _load_groups()
        for ms in groups.values():
            if macro["name"] in ms:
                ms.remove(macro["name"])
        groups.setdefault(group, []).append(macro["name"])
        os.makedirs(MACRO_ROOT, exist_ok=True)
        with open(_groups_path(), "w", encoding="utf-8") as f:
            json.dump({g: ms for g, ms in groups.items() if ms}, f, ensure_ascii=False, indent=2)
    return _json({"saved": path, "group": group, "steps": len(macro["steps"])})


def main():
    env()            # DPI 설정을 먼저
    mcp.run()


if __name__ == "__main__":
    main()
