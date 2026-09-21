"""The Malay and Chinese demo emails are consistent - no API calls here.
tools/multilang_check.py runs them through the real pipeline."""
import json
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "demo" / "multilang"
CASES = json.loads((DEMO / "cases.json").read_text(encoding="utf-8"))


def test_every_demo_case_points_at_real_files_the_pipeline_can_assign():
    assert len(CASES) == 6
    for c in CASES:
        assert (DEMO / c["body"]).exists(), c["id"]
        for name in c["attachments"]:
            assert (DEMO / name).exists(), name
        if c["attachments"]:      # the pipeline tells SI from BL by _SI. / _BL. in the name
            assert any("_SI." in n.upper() for n in c["attachments"]), c["id"]
            assert any("_BL." in n.upper() for n in c["attachments"]), c["id"]


def test_the_mismatch_pair_differs_only_in_the_container_count():
    ok = (DEMO / "en_BL.txt").read_text(encoding="utf-8").splitlines()
    wrong = (DEMO / "wrong_BL.txt").read_text(encoding="utf-8").splitlines()
    diff = [(a, b) for a, b in zip(ok, wrong) if a != b]
    assert len(ok) == len(wrong) and len(diff) == 1 and "5 x 40'HC" in diff[0][1]


def test_the_emails_are_really_in_malay_and_chinese():
    """Nothing translated for the test's sake: the bodies are as a sender writes them."""
    han = lambda s: sum("一" <= ch <= "鿿" for ch in s)
    for c in CASES:
        body = (DEMO / c["body"]).read_text(encoding="utf-8")
        if c["id"].startswith("zh_"):
            assert han(body) > 20, c["id"]
        else:
            assert han(body) == 0 and any(w in body for w in ("Sila", "Terima kasih", "Salam")), c["id"]
