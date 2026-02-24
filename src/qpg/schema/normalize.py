from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class NormalizedObject:
    object_id: str
    source_name: str
    schema_name: str | None
    object_name: str
    object_type: str
    fqname: str
    definition: str
    comment: str
    signature: str | None
    owner: str | None
    is_system: bool


def make_fqname(schema_name: str | None, object_name: str) -> str:
    if schema_name:
        return f"{schema_name}.{object_name}"
    return object_name


def make_object_id(source_name: str, object_type: str, fqname: str) -> str:
    raw = f"{source_name}:{object_type}:{fqname}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    return digest[:12]


def normalize_object(
    *,
    source_name: str,
    schema_name: str | None,
    object_name: str,
    object_type: str,
    definition: str | None,
    comment: str | None,
    signature: str | None = None,
    owner: str | None = None,
    is_system: bool = False,
) -> NormalizedObject:
    fqname = make_fqname(schema_name, object_name)
    object_id = make_object_id(source_name, object_type, fqname)
    return NormalizedObject(
        object_id=object_id,
        source_name=source_name,
        schema_name=schema_name,
        object_name=object_name,
        object_type=object_type,
        fqname=fqname,
        definition=(definition or "").strip(),
        comment=(comment or "").strip(),
        signature=signature,
        owner=owner,
        is_system=is_system,
    )
