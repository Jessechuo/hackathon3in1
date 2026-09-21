from sdoc.core.compare import compare
from sdoc.core.fields import ShipmentFields


def fields(**kw):
    base = dict(shipper="MALAYSIA PAPER SDN BHD", consignee="HANOI TRADING CO", notify_party="SAME AS CONSIGNEE",
                port_of_loading="PORT KLANG, MALAYSIA", port_of_discharge="HAIPHONG, VIETNAM",
                container_count="3 x 40'HC", gross_weight_kg="61,250 KG")
    base.update(kw)
    return ShipmentFields(**base)


def test_a_chinese_si_and_an_english_bl_match_through_the_english_forms():
    si = fields(port_of_loading="巴生港, 马来西亚", container_count="三个40尺高柜", gross_weight_kg="61.25 公吨")
    bl = fields()
    result = compare(si, bl, si_en=fields(), bl_en=fields())
    assert result.defects == [] and result.missing == []
    row = next(r for r in result.rows if r.name == "port_of_loading")
    assert row.si == "巴生港, 马来西亚" and row.si_en == "PORT KLANG, MALAYSIA" and row.match is True


def test_a_real_difference_is_still_a_defect_in_both_forms():
    si = fields(container_count="三个40尺高柜")
    bl = fields(container_count="5 x 40'HC")
    result = compare(si, bl, si_en=fields(container_count="3 x 40'HC"), bl_en=fields(container_count="5 x 40'HC"))
    assert result.defects == ["container_count"]


def test_without_english_forms_the_comparison_is_exactly_as_before():
    """Results saved before this change have no English forms."""
    result = compare(fields(container_count="3 x 40'HC"), fields(container_count="5 x 40'HC"))
    assert result.defects == ["container_count"]
    assert all(r.si_en is None and r.bl_en is None for r in result.rows)


def test_blank_is_decided_on_the_original():
    """An English form cannot invent a value the document does not have."""
    si = fields(gross_weight_kg="____ KG")
    result = compare(si, fields(), si_en=fields(), bl_en=fields())
    assert result.missing == ["gross_weight_kg"]


def test_a_chinese_count_difference_is_caught_even_when_both_documents_are_chinese():
    """Both read "40" - the container size - before counts were parsed, so
    a match of the originals hid the defect the English forms showed."""
    si = fields(container_count="三个40尺高柜")
    bl = fields(container_count="五个40尺高柜")
    result = compare(si, bl, si_en=fields(container_count="3 x 40'HC"),
                     bl_en=fields(container_count="5 x 40'HC"))
    assert result.defects == ["container_count"]
    assert compare(si, bl).defects == ["container_count"]          # and without them


def test_two_chinese_documents_compare_as_written():
    si = fields(shipper="马来西亚纸业有限公司")
    bl = fields(shipper="马来西亚纸业有限公司")
    assert compare(si, bl).defects == []
    assert compare(si, fields(shipper="越南纸业有限公司")).defects == ["shipper"]
