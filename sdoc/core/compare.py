"""SI vs BL, field by field. Deterministic: the LLM reads the values,
this code decides whether they match."""
from dataclasses import dataclass

from sdoc.core import normalize as N
from sdoc.core.fields import FIELDS, ShipmentFields

PARTIES = {"shipper", "consignee", "notify_party"}
PORTS = {"port_of_loading", "port_of_discharge"}


@dataclass
class Row:
    name: str
    si: str | None
    bl: str | None
    match: bool | None          # None = one side blank, could not compare


@dataclass
class Comparison:
    rows: list[Row]
    missing: list[str]
    defects: list[str]


def _key(name: str, value: str | None):
    if N.is_blank(value):
        return None
    if name in PARTIES:
        return N.canon(value) or None
    if name in PORTS:
        return N.port_key(value) or None
    if name == "container_count":
        return N.count_value(value)
    return N.weight_kg(value)


def _equal(name: str, si: str, bl: str, ksi, kbl) -> bool:
    if name in PARTIES:
        return N.same_party(si, bl)
    if name == "gross_weight_kg":
        return abs(ksi - kbl) < 0.5
    return ksi == kbl


def compare(si: ShipmentFields, bl: ShipmentFields) -> Comparison:
    rows, missing, defects = [], [], []
    for name in FIELDS:
        a, b = getattr(si, name), getattr(bl, name)
        ka, kb = _key(name, a), _key(name, b)
        if ka is None or kb is None:
            missing.append(name)
            rows.append(Row(name, a, b, None))
            continue
        ok = _equal(name, a, b, ka, kb)
        rows.append(Row(name, a, b, ok))
        if not ok:
            defects.append(name)
    return Comparison(rows, missing, defects)
