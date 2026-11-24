"""Small deterministic I/O helpers shared by Aster data jobs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def write_json_atomic(path: Path, payload: Any) -> None:
    content = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    write_bytes_atomic(path, content)


def instrument_from_code(code: str) -> str:
    value = str(code).strip().upper()
    if value.startswith(("SH", "SZ", "BJ")) and len(value) == 8:
        return value
    value = value.replace(".", "")
    if value.endswith(("SS", "SH")):
        return "SH" + value[:6]
    if value.endswith("SZ"):
        return "SZ" + value[:6]
    if value.endswith("BJ"):
        return "BJ" + value[:6]
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 6:
        raise ValueError(f"unsupported A-share code: {code!r}")
    if digits.startswith(("4", "8")):
        return "BJ" + digits
    if digits.startswith(("5", "6", "9")):
        return "SH" + digits
    return "SZ" + digits


def numeric_code(instrument: str) -> str:
    normalized = instrument_from_code(instrument)
    return normalized[2:]
