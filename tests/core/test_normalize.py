import pytest

from sdoc.core import normalize as N


@pytest.mark.parametrize("value", [None, "", "   ", "???", "_______", "TBA", "tbc", "N/A", "-", "____"])
def test_placeholders_are_blank(value):
    assert N.is_blank(value)


@pytest.mark.parametrize("value", ["UAB NOVAKOPA", "1 x 40'HC", "21,577 KG", "____MT"])
def test_real_looking_values_are_not_blank(value):
    # "____MT" is not blank text, but weight_kg() finds no number in it,
    # so the comparison still treats it as missing.
    assert not N.is_blank(value)


def test_canon_ignores_case_and_punctuation():
    assert N.canon("Moorim SP Co., Ltd") == N.canon("MOORIM SP CO LTD") == "MOORIM SP CO LTD"


def test_port_key_ignores_codes_but_not_names():
    assert N.port_key("SINGAPORE (SGSIN)") == N.port_key("SINGAPORE")
    # email_013: same UN/LOCODE, different port — a real defect
    assert N.port_key("MOMBASA, KENYA (KEMBA)") != N.port_key("TUTICORIN, INDIA (KEMBA)")


@pytest.mark.parametrize("value,expected", [
    ("1 x 40'HC", 1), ("15 x 20'GP", 15), ("6X40'HC", 6), ("6", 6), ("???", None),
])
def test_count_value(value, expected):
    assert N.count_value(value) == expected


@pytest.mark.parametrize("value,expected", [
    ("21,577 KG", 21577), ("341715", 341715), ("131,322 KG", 131322),
    ("21.5 MT", 21500), ("____MT", None), ("N/A", None),
])
def test_weight_kg(value, expected):
    assert N.weight_kg(value) == expected


def test_same_party_allows_a_name_continued_on_the_next_line():
    assert N.same_party("APRIL FINE PAPER TRADING",
                        "APRIL FINE PAPER TRADING ON BEHALF OF VITAL SOLUTIONS PTE LTD")


def test_same_party_rejects_different_companies():
    assert not N.same_party("EAST BRIGHT FZ-LLC", "UAB NOVAKOPA")
    assert not N.same_party("APRIL", "APRIL FAR EAST (M) SDN BHD")   # prefix too short to trust
