"""폴더·파일 이름(11-24): 새로 쓰면 영어, 예전 한국어 이름이 있으면 그대로(오래 쓴 컴퓨터가 안 깨짐)."""
import os

from engine import proposals
from engine.fsnames import glob_both, pick


def test_new_install_uses_english_names(tmp_path):
    assert pick(str(tmp_path), "_고침").endswith("_fixes")
    proposals.save(str(tmp_path), "m", [{"id": 1, "status": "pending", "created": "1"}])
    assert os.path.exists(tmp_path / "_fixes" / "m_proposals.json")
    assert proposals.pending_count(str(tmp_path)) == 1


def test_existing_korean_folder_is_kept(tmp_path):
    (tmp_path / "_고침").mkdir()
    (tmp_path / "_고침" / "m_제안.json").write_text('[{"id": 1, "status": "pending", "created": "1"}]', encoding="utf-8")
    assert pick(str(tmp_path), "_고침").endswith("_고침")
    assert proposals.load(str(tmp_path), "m")[0]["id"] == 1
    proposals.save(str(tmp_path), "n", [{"id": 2, "status": "pending", "created": "2"}])
    assert proposals.pending_count(str(tmp_path)) == 2
    assert len(glob_both(str(tmp_path), "_고침", ["*_제안.json", "*_proposals.json"])) == 2
