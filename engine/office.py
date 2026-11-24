"""오피스 스텝 실행부(2026-11-17): 엑셀·한글·워드를 화면 좌표가 아니라 자동화 통로(COM)로 다룬다.

- 셀·누름틀·책갈피를 이름으로 읽고 쓴다 → 창이 가려져도 되고, 위치가 바뀌어도 안 틀어짐
- 스텝에서 글자 안의 `{변수}` 는 실행할 때 변수 값으로 바뀐다(예: cell "B{행}")
- 매크로가 직접 켠 프로그램은 매크로가 끝날 때 닫는다(사용자가 이미 켜 둔 프로그램·문서는 건드리지 않음)
- 파일을 지우지 않는다. 저장은 save / save_as 스텝으로만
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, List
from .i18n import K, t

EXCEL_ACTIONS = ("open", "new", "read", "write", "last_row", "run_macro", "save", "save_as", "close", "print")
SAVE_FORMATS = {"xlsx": 51, "xlsm": 52, "xls": 56, "csv": 62}   # csv = CSV UTF-8(한글 안 깨짐)
WORD_ACTIONS = ("open", "replace", "fill_bookmark", "read", "save", "save_as", "close", "print")
HWP_ACTIONS = ("open", "fill_field", "read_field", "replace", "save", "save_as", "close", "print")
PDF_PRINTER = "Microsoft Print to PDF"

_VAR = re.compile(r"\{([^{}]+)\}")


class OfficeError(Exception):
    pass


def fill_vars(s: Any, vars_: Dict[str, Any]) -> Any:
    """문자열 안의 {변수} 를 변수 값으로. 없는 변수면 실패(엉뚱한 칸에 쓰지 않게)."""
    if not isinstance(s, str):
        return s

    from .textops import lookup
    gone = object()

    def rep(m):
        k = m.group(1)
        v = lookup(vars_, k, gone)                  # '행.이름' 처럼 표 한 줄의 칸도
        if v is gone:
            raise OfficeError(t("변수 '{name}' 가 없음", name=k))
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v)
    return _VAR.sub(rep, s)


def table_grid(v: Any):
    """엑셀에 한 번에 쓸 2차원 표. [[..],[..]] / [..](한 줄) / [{제목: 값}, ...](제목 줄 + 값). 표가 아니면 None."""
    if not isinstance(v, (list, tuple)) or not v:
        return None
    if all(isinstance(r, dict) for r in v):
        keys: List[str] = []
        for r in v:
            for k in r:
                if k not in keys and k not in ("행", "row") and not str(k).isdigit():
                    keys.append(k)
        if not keys:                              # 제목 없는 표(웹 표 1·2·3 칸)
            keys = sorted({k for r in v for k in r if str(k).isdigit()}, key=int)
            return [[r.get(k) for k in keys] for r in v]
        return [keys] + [[r.get(k) for k in keys] for r in v]
    if all(isinstance(r, (list, tuple)) for r in v):
        return [list(r) for r in v]
    if any(isinstance(r, (list, tuple, dict)) for r in v):
        return None
    return [list(v)]


def _com():
    try:
        import pythoncom
        import win32com.client
    except ImportError as e:
        raise OfficeError(t("오피스 스텝에는 pywin32 가 필요함({error})", error=e))
    pythoncom.CoInitialize()
    return win32com.client


def _abs(path: str) -> str:
    if not path:
        raise OfficeError(t("파일 경로가 필요함"))
    return os.path.abspath(os.path.expandvars(os.path.expanduser(path)))


class _App:
    PROGID = ""
    NAME = ""

    def __init__(self):
        self.app = None
        self.started = False       # 매크로가 직접 켰는지
        self.doc = None
        self.pid = None            # 매크로가 켠 프로그램 번호(남은 것 점검용, office_guard)

    def _ensure(self, visible: bool = False):
        if self.app is not None:
            return self.app
        client = _com()
        # 늘 매크로 전용(숨은) 프로그램을 새로 켠다. 이미 켜진 엑셀·워드에는 붙지 않는다:
        #  - 사람이 쓰는 엑셀이면 그 창에 매크로 파일이 열려 사람 일을 방해함(11-18 실제로 생김)
        #  - 다른 자동화가 남긴 숨은 엑셀이면 종료 중이라 파일을 열어도 문서가 안 잡히는 일이 있었음
        before = self._procs_before()
        try:
            self.app = client.DispatchEx(self.PROGID)
        except Exception as e:
            raise OfficeError(t("{app}을(를) 켜지 못함(설치돼 있는지 확인): {error}", app=self._label(), error=e))
        self.started = True
        self._note_started(before)
        self._after_start(visible)
        return self.app

    def _procs_before(self):
        try:
            from . import office_guard
            return office_guard.processes([office_guard.EXE[self.NAME]])
        except Exception:
            return None

    def _note_started(self, before):
        """켠 프로그램 번호를 적어 둠(다음 실행에서 남은 것을 찾아 닫기 요청하려고). 실패해도 일은 계속."""
        try:
            from . import office_guard
            pid = None
            try:
                pid = office_guard.pid_of_hwnd(int(self.app.Hwnd))
            except Exception:
                pid = None
            if not pid and before is not None:
                pid = office_guard.new_pid(self.NAME, before)
            self.pid = pid
            office_guard.started(self.NAME, pid)
        except Exception:
            pass

    def _after_start(self, visible: bool):
        try:
            if self.started:
                self.app.Visible = bool(visible)
        except Exception:
            pass

    def shutdown(self):
        """매크로가 켠 것만 닫는다(저장 안 된 변경은 버림 — 저장은 save 스텝으로)."""
        try:
            if self.started and self.app is not None:
                self._quit()
        except Exception:
            pass
        if self.started and self.pid:
            try:
                from . import office_guard
                office_guard.quit_sent(self.pid)
            except Exception:
                pass
        self.app = self.doc = None
        self.started = False
        self.pid = None

    def _quit(self):
        self.app.Quit()

    def _label(self) -> str:
        return {"엑셀": t("엑셀"), "워드": t("워드"), "한글": t("한글")}.get(self.NAME, self.NAME)

    def _need_doc(self):
        if self.doc is None:
            raise OfficeError(t("열린 {app} 문서가 없음 — 먼저 open", app=self._label()))
        return self.doc


class ExcelApp(_App):
    PROGID = "Excel.Application"
    NAME = "엑셀"

    def _autofit(self):
        try:
            for ws in self.doc.Worksheets:
                ws.UsedRange.Columns.AutoFit()
        except Exception:
            pass

    def _after_start(self, visible):
        super()._after_start(visible)
        try:
            if self.started:
                self.app.DisplayAlerts = False
                self.app.AskToUpdateLinks = False     # '연결된 파일 업데이트?' 창이 숨은 채 떠서 멈추는 일 방지
        except Exception:
            pass

    def _sheet(self, sheet):
        wb = self._need_doc()
        if sheet in (None, ""):
            return wb.ActiveSheet
        try:
            return wb.Worksheets(int(sheet) if str(sheet).isdigit() else sheet)
        except Exception:
            raise OfficeError(t("시트 '{name}' 가 없음", name=sheet))

    def run(self, action: str, p: dict) -> Any:
        if action == "open":
            app = self._ensure(p.get("visible", False))
            path = _abs(p.get("path", ""))
            if not os.path.exists(path):
                raise OfficeError(t("파일이 없음: {path}", path=path))
            for wb in app.Workbooks:            # 이미 열려 있으면 그것
                if os.path.normcase(wb.FullName) == os.path.normcase(path):
                    self.doc = wb
                    return path
            self.doc = app.Workbooks.Open(path, 0)        # 0 = 연결 업데이트 안 물음
            self.is_new = False
            return path
        if action == "new":
            # 빈 새 통합 문서(아직 파일 아님 — save_as 로 저장). sheet 를 주면 첫 시트 이름
            app = self._ensure(p.get("visible", False))
            self.doc = app.Workbooks.Add()
            self.is_new = True
            if p.get("sheet"):
                self.doc.Worksheets(1).Name = str(p["sheet"])
            return None
        if action == "close":
            if self.doc is not None:
                self.doc.Close(SaveChanges=False)
                self.doc = None
            return None
        if action in ("save", "save_as") and getattr(self, "is_new", False):
            self._autofit()                  # 새로 만든 파일은 칸 너비를 내용에 맞춤(날짜가 '#####' 로 안 보이게)
        if action == "save":
            self._need_doc().Save()
            return None
        if action == "save_as":
            path = _abs(p.get("path", ""))
            # 같은 이름: 새로 만든 문서는 기본 '멈춤'(파일 단계와 같음), 연 문서는 예전처럼 덮어씀. overwrite 로 바꿈
            from . import fileops
            mode = p.get("overwrite") or ("fail" if getattr(self, "is_new", False) else "replace")
            if os.path.exists(path) and mode != "replace":
                try:
                    path = fileops._resolve_clash(path, mode, fileops.to_recycle_bin)
                except fileops.FileOpError as e:
                    raise OfficeError(str(e))
                if path is None:
                    return ""
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            fmt = str(p.get("format") or os.path.splitext(path)[1].lstrip(".") or "xlsx").lower()
            if fmt == "pdf" or p.get("pdf"):
                self._need_doc().ExportAsFixedFormat(0, path)         # 0 = PDF
            elif fmt in SAVE_FORMATS:
                self._need_doc().SaveAs(path, SAVE_FORMATS[fmt])
            else:
                self._need_doc().SaveAs(path)
            self.is_new = False
            return path
        if action == "run_macro":
            return self._ensure().Run(p["name"])
        if action == "print":
            # printer 를 안 주면 기본 프린터. to_file 을 주면 종이 대신 인쇄 모양 그대로 PDF 파일로
            # (프린터를 거치지 않음 — PDF 프린터는 저장 위치를 묻는 창을 띄울 수 있어서)
            wb = self._need_doc()
            target = self._sheet(p["sheet"]) if p.get("sheet") else wb
            to = p.get("to_file")
            if to:
                path = _abs(to)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                target.ExportAsFixedFormat(0, path)                     # xlTypePDF, 인쇄 영역·페이지 설정 그대로
                return path
            kw = {"Copies": int(p.get("copies", 1) or 1)}
            if p.get("printer"):
                kw["ActivePrinter"] = p["printer"]
            target.PrintOut(**kw)
            return None
        ws = self._sheet(p.get("sheet"))
        if action == "read":
            rng = ws.Range(p["cell"])
            v = rng.Value
            if isinstance(v, tuple):              # 범위 → 줄마다 목록
                return [[int(c) if isinstance(c, float) and c.is_integer() else c for c in r] for r in v]
            if isinstance(v, float) and v.is_integer():
                return int(v)
            return v
        if action == "write":
            v = p.get("value")
            grid = table_grid(v)
            if grid is not None:                  # 표(줄 목록)면 cell 부터 그 크기만큼 한 번에
                top = ws.Range(p["cell"])
                r0, c0 = int(top.Row), int(top.Column)
                ncol = max(len(r) for r in grid)
                rng = ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + len(grid) - 1, c0 + ncol - 1))
                rng.Value = tuple(tuple(r) + (None,) * (ncol - len(r)) for r in grid)
                return None
            ws.Range(p["cell"]).Value = v
            return None
        if action == "last_row":
            if str(p.get("cell") or "") == "*":             # 어느 칸이든 값이 있는 마지막 줄
                ur = ws.UsedRange
                return int(ur.Row + ur.Rows.Count - 1)
            col = str(p.get("cell") or "A")
            col = re.sub(r"\d", "", col) or "A"
            return int(ws.Cells(ws.Rows.Count, col).End(-4162).Row)    # xlUp
        raise OfficeError(t("모르는 엑셀 동작 '{action}'", action=action))


class WordApp(_App):
    _read_pdf = None  # 아래에서 붙임
    PROGID = "Word.Application"
    NAME = "워드"

    def _after_start(self, visible):
        super()._after_start(visible)
        try:
            if self.started:
                self.app.DisplayAlerts = 0
        except Exception:
            pass

    def run(self, action: str, p: dict) -> Any:
        if action == "open":
            app = self._ensure(p.get("visible", False))
            path = _abs(p.get("path", ""))
            if not os.path.exists(path):
                raise OfficeError(t("파일이 없음: {path}", path=path))
            for d in app.Documents:
                if os.path.normcase(d.FullName) == os.path.normcase(path):
                    self.doc = d
                    return path
            self.doc = app.Documents.Open(path, False)    # False = 형식 변환 확인 창 안 띄움
            return path
        if action == "close":
            if self.doc is not None:
                self.doc.Close(SaveChanges=0)
                self.doc = None
            return None
        if action in ("pdf_text", "pdf_tables"):
            return self._read_pdf(action, _abs(p.get("path", "")))
        doc = self._need_doc()
        if action == "print":
            # to_file 이면 종이 대신 인쇄 모양 그대로 PDF 로. 프린터를 고르면 워드의 프린터만 잠깐 바꾼다
            # (윈도우 기본 프린터는 안 바꿈: FilePrintSetup DoNotSetAsSysDefault)
            to = p.get("to_file")
            if to:
                path = _abs(to)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                doc.ExportAsFixedFormat(path, 17)
                return path
            printer = p.get("printer") or ""
            app = self._ensure()
            old = app.ActivePrinter
            try:
                if printer:
                    app.WordBasic.FilePrintSetup(Printer=printer, DoNotSetAsSysDefault=1)
                doc.PrintOut(Background=False, Copies=int(p.get("copies", 1) or 1))
            finally:
                if printer and old:
                    try:
                        app.WordBasic.FilePrintSetup(Printer=old.split(" on ")[0], DoNotSetAsSysDefault=1)
                    except Exception:
                        pass
            return _abs(to) if to else None
        if action == "save":
            doc.Save()
            return None
        if action == "save_as":
            path = _abs(p.get("path", ""))
            if path.lower().endswith(".pdf") or p.get("pdf"):
                doc.ExportAsFixedFormat(path, 17)                       # wdExportFormatPDF
            else:
                doc.SaveAs2(path)
            return path
        if action == "replace":
            f = doc.Content.Find
            f.ClearFormatting()
            f.Replacement.ClearFormatting()
            # 이름 붙인 인자는 늦은 연결에서 안 먹을 때가 있어 순서대로 넘김:
            # FindText, MatchCase, MatchWholeWord, MatchWildcards, MatchSoundsLike, MatchAllWordForms,
            # Forward, Wrap(1=계속), Format, ReplaceWith, Replace(2=모두)
            ok = f.Execute(p["find"], False, False, False, False, False, True, 1, False, p.get("text", ""), 2)
            return bool(ok)
        if action == "fill_bookmark":
            name = p["name"]
            if not doc.Bookmarks.Exists(name):
                raise OfficeError(t("책갈피 '{name}' 가 없음", name=name))
            rng = doc.Bookmarks(name).Range
            rng.Text = p.get("text", "")
            doc.Bookmarks.Add(name, rng)                                # 다시 채울 수 있게 책갈피 유지
            return None
        if action == "read":
            name = p.get("name")
            if name:
                if not doc.Bookmarks.Exists(name):
                    raise OfficeError(t("책갈피 '{name}' 가 없음", name=name))
                return doc.Bookmarks(name).Range.Text
            return doc.Content.Text
        raise OfficeError(t("모르는 워드 동작 '{action}'", action=action))


def _clean_pdf_text(s: str) -> str:
    """워드가 읽은 PDF 글: 칸 끝(\r\x07)은 탭, 줄 끝은 줄바꿈."""
    s = s.replace("\r\x07\r\x07", "\n").replace("\r\x07", "\t").replace("\x07", "\t").replace("\r", "\n")
    s = s.replace("\x0b", "\n").replace("\x0c", "\n")
    lines = [ln.rstrip("\t ") for ln in s.split("\n")]
    out = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def _wd_read_pdf(self, action: str, path: str):
    """PDF 를 워드로 열어(창 없이, 읽기 전용) 글 또는 표를 읽고 바로 닫는다. 지금 열린 문서(doc)는 그대로."""
    if not os.path.exists(path):
        raise OfficeError(t("파일이 없음: {path}", path=path))
    app = self._ensure(False)
    d = app.Documents.Open(path, False, True, False, "", "", False, "", "", 0, 0, False)
    #  인자: FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, ..., Visible(12번째)=False
    try:
        if action == "pdf_text":
            return _clean_pdf_text(d.Content.Text)
        tables = []
        for ti in range(1, d.Tables.Count + 1):
            tb = d.Tables(ti)
            rows = []
            for r in range(1, tb.Rows.Count + 1):
                row = []
                for c in range(1, tb.Columns.Count + 1):
                    try:
                        v = tb.Cell(r, c).Range.Text
                    except Exception:            # 합친 칸
                        v = ""
                    row.append(v.replace("\r\x07", "").replace("\x07", "").replace("\r", " ").strip())
                rows.append(row)
            tables.append(rows)
        return tables
    finally:
        d.Close(0)


def _hwp_module_names() -> list:
    """한글 보안 승인 모듈로 등록된 이름들(파일이 실제로 있는 것만). 흔한 이름을 앞에."""
    names = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\HNC\HwpAutomation\Modules") as k:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if isinstance(val, str) and os.path.exists(val):
                    names.append(name)
    except OSError:
        pass
    names.sort(key=lambda n: (n != "FilePathCheckerModule", n))
    return names


# 한글 보안 승인 모듈이 없을 때: 기본은 바로 '설정 필요'로 실패(숨은 확인 창에 2분 막히지 않게).
# 사람이 '확인 창을 보이게 해서 계속'을 고르면 화면 프로그램이 True 로 바꿈(그 실행 동안 한글 창을 보이고 사람이 답함).
HWP_ALLOW_PROMPT = False
HWP_SETUP_NEEDED = K("한글 자동화를 쓰려면 한 번 설정이 필요해요(보안 승인 모듈 없음) — 도움말 → '한글 자동화 설정'")


def hwp_security_ready() -> bool:
    """한글 보안 승인 모듈이 등록돼 있고 파일도 있는지(없으면 파일을 열 때마다 확인 창이 뜸)."""
    return bool(_hwp_module_names())


class HwpApp(_App):
    PROGID = "HWPFrame.HwpObject"
    NAME = "한글"

    def _ensure(self, visible: bool = False):
        if self.app is not None:
            return self.app
        if not hwp_security_ready() and not HWP_ALLOW_PROMPT:
            raise OfficeError(t(HWP_SETUP_NEEDED))
        client = _com()
        before = self._procs_before()
        try:
            self.app = client.gencache.EnsureDispatch(self.PROGID)
        except Exception:
            try:
                self.app = client.Dispatch(self.PROGID)
            except Exception as e:
                raise OfficeError(t("한글을 켜지 못함(설치돼 있는지 확인): {error}", error=e))
        self.started = True
        self._note_started(before)
        # 파일 열 때마다 묻는 보안 창을 줄임(보안 승인 모듈이 등록돼 있을 때만 효과).
        # 11-19: 이름이 PC마다 다름(이 PC는 'FilePathCheckerModuleExample') → 레지스트리에 실제로 등록된 이름으로.
        # 하나도 안 되면 숨은 확인 창에 막혀 120초 멈추므로, 창을 보이게 해서 사람이 답할 수 있게 한다.
        self.secured = False
        for name in _hwp_module_names():
            try:
                if self.app.RegisterModule("FilePathCheckDLL", name):
                    self.secured = True
                    break
            except Exception:
                pass
        if not self.secured:
            visible = True
        try:
            self.app.XHwpWindows.Item(0).Visible = bool(visible)
        except Exception:
            pass
        return self.app

    def _quit(self):
        self.app.Quit()

    def run(self, action: str, p: dict) -> Any:
        if action == "open":
            app = self._ensure(p.get("visible", False))
            path = _abs(p.get("path", ""))
            if not os.path.exists(path):
                raise OfficeError(t("파일이 없음: {path}", path=path))
            if not app.Open(path, "", "forceopen:true"):
                raise OfficeError(t("한글 파일을 못 엶: {path}", path=path))
            self.doc = path
            return path
        if action == "close":
            if self.app is not None and self.doc is not None:
                try:
                    self.app.Clear(1)            # 1 = 저장 안 하고 비움
                except Exception:
                    pass
            self.doc = None
            return None
        self._need_doc()
        app = self.app
        if action == "print":
            # 한글 인쇄. to_file 이면 종이 대신 PDF 로 저장(프린터를 거치지 않음)
            to = p.get("to_file")
            if to:
                path = _abs(to)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if not app.SaveAs(path, "PDF", ""):
                    raise OfficeError(t("저장 실패: {path}", path=path))
                return path
            printer = p.get("printer") or ""
            act = app.CreateAction("Print")
            ps = act.CreateSet()
            act.GetDefault(ps)
            if printer:
                ps.SetItem("PrinterName", printer)
            ps.SetItem("NumCopy", int(p.get("copies", 1) or 1))
            if not act.Execute(ps):
                raise OfficeError(t("한글 인쇄 실패"))
            return _abs(to) if to else None
        if action == "save":
            app.Save()
            return None
        if action == "save_as":
            path = _abs(p.get("path", ""))
            fmt = "PDF" if (path.lower().endswith(".pdf") or p.get("pdf")) else "HWP"
            if not app.SaveAs(path, fmt, ""):
                raise OfficeError(t("저장 실패: {path}", path=path))
            return path
        if action == "fill_field":
            name = p["name"]
            if not app.FieldExist(name):
                raise OfficeError(t("누름틀 '{name}' 가 없음", name=name))
            app.PutFieldText(name, p.get("text", ""))
            return None
        if action == "read_field":
            name = p["name"]
            if not app.FieldExist(name):
                raise OfficeError(t("누름틀 '{name}' 가 없음", name=name))
            return app.GetFieldText(name)
        if action == "replace":
            act = app.CreateAction("AllReplace")
            ps = act.CreateSet()
            act.GetDefault(ps)
            ps.SetItem("FindString", p["find"])
            ps.SetItem("ReplaceString", p.get("text", ""))
            ps.SetItem("IgnoreMessage", 1)
            return bool(act.Execute(ps))
        raise OfficeError(t("모르는 한글 동작 '{action}'", action=action))


APPS = {"excel": ExcelApp, "word": WordApp, "hwp": HwpApp}
ACTIONS = {"excel": EXCEL_ACTIONS, "word": WORD_ACTIONS, "hwp": HWP_ACTIONS}
# 동작마다 꼭 있어야 하는 칸
REQUIRED = {
    ("excel", "open"): ["path"], ("excel", "new"): [], ("excel", "read"): ["cell", "var"], ("excel", "write"): ["cell", "value"],
    ("excel", "last_row"): ["var"], ("excel", "run_macro"): ["name"], ("excel", "save_as"): ["path"],
    ("word", "open"): ["path"], ("word", "replace"): ["find", "text"], ("word", "fill_bookmark"): ["name", "text"],
    ("word", "read"): ["var"], ("word", "save_as"): ["path"],
    ("hwp", "open"): ["path"], ("hwp", "fill_field"): ["name", "text"], ("hwp", "read_field"): ["name", "var"],
    ("hwp", "replace"): ["find", "text"], ("hwp", "save_as"): ["path"],
    ("word", "pdf_text"): ["path"], ("word", "pdf_tables"): ["path"],
}


class OfficeSession:
    """한 번의 매크로 실행 동안 프로그램별로 하나씩 켜 두고 같이 씀.

    COM 개체는 만든 스레드에서만 써야 해서(다른 스레드에서 쓰면 '개체가 서버에 연결되지 않았습니다'),
    엑셀·한글·워드와의 모든 대화는 이 세션 전용 스레드 하나에서 한다. 스텝 시험처럼 부르는 스레드가 매번
    달라도(화면 프로그램이 AI 요청을 대신 처리할 때 등) 같은 문서를 이어 쓸 수 있다. 2026-11-17."""

    CALL_TIMEOUT = 120.0        # 오피스가 한 번 대답하는 데 이보다 오래 걸리면 멈춘 것으로 봄(초)

    def __init__(self, call_timeout: Optional[float] = None, guard: bool = True):
        import queue
        import threading
        self.apps: Dict[str, _App] = {}
        self.call_timeout = self.CALL_TIMEOUT if call_timeout is None else call_timeout
        self.broken = False         # 한 번 응답이 없으면 이번 실행에서는 더 쓰지 않음
        self._guard = guard
        self._q: "queue.Queue" = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="office-com", daemon=True)
        self._thread.start()

    def _loop(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        if self._guard:              # 지난 실행이 남긴 숨은 엑셀·워드에 닫기 요청(강제 종료 아님)
            try:
                from . import office_guard
                office_guard.cleanup(notify=office_guard.default_notify)
            except Exception:
                pass
        while True:
            item = self._q.get()
            if item is None:
                break
            fn, box, done = item
            try:
                box["value"] = fn()
            except BaseException as e:        # 부른 쪽에서 다시 올림
                box["error"] = e
            done.set()

    def _call(self, fn, timeout: Optional[float] = None):
        import threading
        if threading.current_thread() is self._thread:
            return fn()
        if self.broken:
            raise OfficeError(t("오피스가 응답하지 않아 이번 실행에서는 더 쓰지 않음"))
        box: dict = {}
        done = threading.Event()
        self._q.put((fn, box, done))
        limit = self.call_timeout if timeout is None else timeout
        if not done.wait(limit if limit and limit > 0 else None):
            self.broken = True
            try:
                from . import notify as nt
                from .office_guard import _root
                nt.send(t("오피스 응답 없음"), t("엑셀·워드·한글이 {n}초 넘게 대답하지 않아 그 단계를 실패로 처리함. "
                                             "숨은 대화상자가 떠 있을 수 있음.", n=int(limit)),
                        channels=("log",), level="warn", source=t("오피스 지킴이"), root=_root())
            except Exception:
                pass
            raise OfficeError(t("오피스 응답 없음({n}초) — 숨은 확인 창이 떠 있을 수 있음", n=int(limit)))
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def run(self, kind: str, action: str, params: dict) -> Any:
        def work():
            app = self.apps.get(kind)
            if app is None:
                app = self.apps[kind] = APPS[kind]()
            return app.run(action, params)
        return self._call(work)

    def shutdown(self):
        def work():
            for a in self.apps.values():
                a.shutdown()
            self.apps.clear()
        try:
            if not self.broken:
                self._call(work, timeout=30)
        except OfficeError:
            pass
        finally:
            self._q.put(None)


WordApp._read_pdf = _wd_read_pdf
