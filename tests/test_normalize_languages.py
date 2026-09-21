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


def test_tonnes_are_read_in_chinese_and_malay():
    # approx: 13.1 * 1000 is 13100.000000000002 in floating point
    assert N.weight_kg("131.322 公吨") == pytest.approx(131322)
    assert N.weight_kg("13.1 吨") == pytest.approx(13100)
    assert N.weight_kg("131.322 tan metrik") == pytest.approx(131322)
    assert N.weight_kg("131,322 KG") == 131322      # unchanged
