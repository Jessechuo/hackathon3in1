"""The seven compared fields. Pure data: no I/O, no AI."""
from pydantic import BaseModel

FIELDS = [
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
]


class ShipmentFields(BaseModel):
    """Raw values exactly as written in one document. None = absent/blank."""
    shipper: str | None
    consignee: str | None
    notify_party: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    container_count: str | None
    gross_weight_kg: str | None
