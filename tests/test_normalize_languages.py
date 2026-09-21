import pytest

from sdoc.core import normalize as N


def test_a_chinese_company_name_is_not_a_blank():
    """canon kept only A-Z and 0-9, so a Chinese name became "" - and the
    comparison reported the field as missing."""
    assert N.canon("马来西亚纸业有限公司") == "马来西亚纸业有限公司"
    assert N.canon("巴生港, 马来西亚 (MYPKG)") == "巴生港 马来西亚 MYPKG"


def test_english_values_normalise_exactly_as_before():
    assert N.canon("Asia Pacific Paperboard Trading Pte. Ltd.") == "ASIA PACIFIC PAPERBOARD TRADING PTE LTD"
    assert N.port_key("CALLAO, PERU (PECLL)") == "CALLAO PERU"


@pytest.mark.parametrize("value,expected", [
    ("三个40尺高柜", 3),          # the 40 is the container size, not the count
    ("五个40尺高柜", 5),
    ("两个20尺普柜", 2),
    ("十二个40尺高柜", 12),
    ("dua kontena 40 kaki HC", 2),
    ("dua (2) kontena 40 kaki HC", 2),
    ("40'HC x 6", 6),             # size first: the count is the other number
    ("3 x 40'HC", 3),             # English, as before
])
def test_container_counts_are_not_confused_with_container_sizes(value, expected):
    assert N.count_value(value) == expected


def test_tonnes_are_read_in_chinese_and_malay():
    # approx: 13.1 * 1000 is 13100.000000000002 in floating point
    assert N.weight_kg("131.322 公吨") == pytest.approx(131322)
    assert N.weight_kg("13.1 吨") == pytest.approx(13100)
    assert N.weight_kg("131.322 tan metrik") == pytest.approx(131322)
    assert N.weight_kg("131,322 KG") == 131322      # unchanged
