"""예시 자료(엑셀) 영어판 만들기: gui/v3/example_data/자료/*.xlsx → gui/v3/example_data/data/*.xlsx (11-24).

엑셀 프로그램·라이브러리 없이 xlsx 안의 글(XML)만 바꾼다. 작성자 이름 같은 문서 속성은 양쪽 다 지운다.
다시 돌려도 같은 결과. 한국어 자료가 바뀌면 이걸 다시 돌린다.
"""
import os
import re
import zipfile

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "v3", "example_data")
SRC = os.path.join(HERE, "자료")
DST = os.path.join(HERE, "data")

FILES = {"정리표_양식": "summary_template", "지점_강남": "branch_boston", "지점_부산": "branch_chicago",
         "지점_대구": "branch_denver", "지점_광주": "branch_seattle", "지점_대전": "branch_austin"}                 # 명단은 한글(HWP) 예시에만 씀
WORDS = {
    "금액 합계": "Total amount", "강남": "Boston", "부산": "Chicago", "대구": "Denver", "광주": "Seattle", "대전": "Austin",
    "건수": "Count", "금액": "Amount", "날짜": "Date", "품목": "Item", "수량": "Qty", "지점": "Branch", "전체": "All",
    "매출": "Sales", "모음": "Collected", "합계": "Summary", "명단": "Staff",
    "볼펜": "Pens", "포스트잇": "Sticky notes", "파일철": "Binders", "용지": "Paper", "토너": "Toner",
    "이름": "Name", "부서": "Department", "직위": "Title", "입사일": "Start date",
    "회계팀": "Accounting", "총무팀": "Admin", "생산팀": "Production", "기획팀": "Planning", "영업팀": "Sales team",
    "사원": "Associate", "주임": "Specialist", "대리": "Senior associate", "과장": "Manager", "차장": "Senior manager",
    "김민준": "Alex Kim", "이서연": "Sara Lee", "박도윤": "Dan Park", "최하은": "Hannah Choi", "정시우": "Sean Jung",
    "강지우": "Jamie Kang", "조예준": "Eli Cho", "윤수아": "Sue Yoon", "장주원": "Joe Jang", "임지아": "Mia Lim",
    "맑은 고딕": "Calibri", "표준": "Normal", "워크시트": "Worksheets", "테마": "Theme",
}
KO = re.compile(r"[가-힣]")


def _clean_props(name: str, text: str) -> str:
    if name == "docProps/core.xml":                     # 작성자·마지막 수정한 사람 지움(개인 정보)
        text = re.sub(r"<dc:creator>[^<]*</dc:creator>", "<dc:creator></dc:creator>", text)
        text = re.sub(r"<cp:lastModifiedBy>[^<]*</cp:lastModifiedBy>", "<cp:lastModifiedBy></cp:lastModifiedBy>", text)
        text = re.sub(r"<dc:(title|subject|description)>[^<]*</dc:\1>", "", text)
        text = re.sub(r"<cp:keywords>[^<]*</cp:keywords>", "", text)
    if name == "xl/workbook.xml":                       # 만든 컴퓨터의 폴더 경로가 남는 칸 지움
        text = re.sub(r"<mc:AlternateContent[^>]*>(?:(?!</mc:AlternateContent>).)*absPath(?:(?!</mc:AlternateContent>).)*</mc:AlternateContent>",
                      "", text, flags=re.S)
        text = re.sub(r"<x15ac:absPath[^>]*/>", "", text)
    if name == "docProps/app.xml":
        text = re.sub(r"<Company>[^<]*</Company>", "<Company></Company>", text)
        text = re.sub(r"<Manager>[^<]*</Manager>", "", text)
    return text


def _rewrite(src: str, dst: str, translate: bool) -> None:
    tmp = dst + ".tmp"
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            data = zi.read(info.filename)
            if info.filename.endswith((".xml", ".rels")):
                text = _clean_props(info.filename, data.decode("utf-8"))
                if translate:
                    for k in sorted(WORDS, key=len, reverse=True):
                        text = text.replace(k, WORDS[k])
                    left = KO.findall(text)
                    if left:
                        raise SystemExit(f"번역 안 된 글이 남음: {os.path.basename(src)} {info.filename}")
                data = text.encode("utf-8")
            zo.writestr(info, data)
    os.replace(tmp, dst)


def main() -> None:
    os.makedirs(DST, exist_ok=True)
    for ko, en in FILES.items():
        src = os.path.join(SRC, ko + ".xlsx")
        _rewrite(src, src, translate=False)                     # 한국어 자료도 작성자 이름 지움
        _rewrite(src, os.path.join(DST, en + ".xlsx"), translate=True)
        print(ko, "→", en)


if __name__ == "__main__":
    main()
