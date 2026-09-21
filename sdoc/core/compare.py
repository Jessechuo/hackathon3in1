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
    si_en: str | None = None    # the English form, when the AI gave one
    bl_en: str | None = None


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


def _same(name: str, a: str | None, b: str | None) -> bool:
    ka, kb = _key(name, a), _key(name, b)
    return ka is not None and kb is not None and _equal(name, a, b, ka, kb)


def compare(si: ShipmentFields, bl: ShipmentFields,
            si_en: ShipmentFields | None = None,
            bl_en: ShipmentFields | None = None) -> Comparison:
    """A field matches if the values match as written, or - when the
    documents are in different languages - if their English forms match.
    It is a defect only when both fail. Blank is decided on the original:
    an English form cannot invent a value the document does not have."""
    rows, missing, defects = [], [], []
    for name in FIELDS:
        a, b = getattr(si, name), getattr(bl, name)
        a_en = getattr(si_en, name) if si_en else None
        b_en = getattr(bl_en, name) if bl_en else None
        if _key(name, a) is None or _key(name, b) is None:
            missing.append(name)
            rows.append(Row(name, a, b, None, a_en, b_en))
            continue
        ok = _same(name, a, b) or _same(name, a_en, b_en)
        rows.append(Row(name, a, b, ok, a_en, b_en))
        if not ok:
            defects.append(name)
    return Comparison(rows, missing, defects)
