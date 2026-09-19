from sdoc.core.compare import compare
from sdoc.core.fields import ShipmentFields


def sf(**over):
    base = dict(
        shipper="APRIL FAR EAST (M) SDN BHD",
        consignee="MOORIM SP CO., LTD",
        notify_party="UAB NOVAKOPA",
        port_of_loading="PORT KLANG (WESTPORT), MALAYSIA (MYPKG)",
        port_of_discharge="CALLAO, PERU (PECLL)",
        container_count="1 x 40'HC",
        gross_weight_kg="21,577 KG",
    )
    base.update(over)
    return ShipmentFields(**base)


def test_identical_documents_have_no_defects():
    c = compare(sf(), sf())
    assert c.defects == [] and c.missing == []
    assert len(c.rows) == 7 and all(r.match for r in c.rows)


def test_formatting_differences_are_not_defects():
    c = compare(sf(), sf(consignee="Moorim SP Co Ltd", gross_weight_kg="21577",
                        port_of_discharge="CALLAO, PERU", container_count="1"))
    assert c.defects == []


def test_email_013_same_port_code_different_port_is_a_defect():
    c = compare(sf(port_of_discharge="MOMBASA, KENYA (KEMBA)"),
                sf(port_of_discharge="TUTICORIN, INDIA (KEMBA)"))
    assert c.defects == ["port_of_discharge"]


def test_email_043_container_count_keeps_raw_values_for_the_report():
    c = compare(sf(container_count="3 x 20'GP"), sf(container_count="5 x 20'GP"))
    assert c.defects == ["container_count"]
    row = next(r for r in c.rows if r.name == "container_count")
    assert (row.si, row.bl, row.match) == ("3 x 20'GP", "5 x 20'GP", False)


def test_defects_are_reported_in_field_order():
    c = compare(sf(), sf(gross_weight_kg="99,999 KG", shipper="SOMEONE ELSE LTD"))
    assert c.defects == ["shipper", "gross_weight_kg"]


def test_blank_value_is_missing_not_a_defect():
    c = compare(sf(gross_weight_kg="N/A", container_count=""), sf())
    assert c.missing == ["container_count", "gross_weight_kg"]
    assert c.defects == []
    assert next(r for r in c.rows if r.name == "container_count").match is None
