"""Content-addressed disk cache for LLM responses.

Keyed on model + prompt + output schema, so any change to any of the three
produces a different key and the stale entry is simply never read.
"""
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from sdoc.config import CACHE_DIR


def cache_key(model: str, prompt: str, schema: type[BaseModel]) -> str:
    # sort_keys matters: dict ordering must not change the key.
    schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
    payload = f"{model}\x00{prompt}\x00{schema_json}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return Path(CACHE_DIR) / f"{key}.json"


def cache_get(key: str) -> dict | None:
    path = _path(key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def cache_put(key: str, value: dict) -> None:
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    _path(key).write_text(json.dumps(value), encoding="utf-8")
