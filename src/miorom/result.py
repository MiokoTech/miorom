"""
miorom.result
~~~~~~~~~~~~~
Serialization contract for public MioROM result objects.
"""

import json

from miorom.errors import ParseError
from dataclasses import is_dataclass
from dataclasses import fields
from enum import Enum
from typing import Any, Dict, Type, TypeVar, Union, get_args, get_origin, get_type_hints


T = TypeVar("T", bound="MioRomResult")


class MioRomResult:
    """Mixin for public result objects with a stable JSON-ready contract."""

    def to_dict(self) -> Dict[str, Any]:
        if not is_dataclass(self):
            raise TypeError(f"{type(self).__name__} must be a dataclass to use MioRomResult")
        return {
            item.name: _normalize(getattr(self, item.name))
            for item in fields(self)
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        field_names = {item.name for item in fields(cls)}
        unknown = set(data) - field_names
        if unknown:
            raise ParseError(f"Unknown fields for {cls.__name__}: {', '.join(sorted(unknown))}")
        try:
            field_types = get_type_hints(cls)
        except Exception:
            field_types = {field.name: field.type for field in fields(cls)}
        kwargs = {
            name: _deserialize(value, field_types.get(name, Any))
            for name, value in data.items()
        }
        return cls(**kwargs)

    @classmethod
    def from_json(cls: Type[T], json_text: str) -> T:
        return cls.from_dict(json.loads(json_text))


def _normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize(item) for item in value]
    return value


def _deserialize(value: Any, annotation: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if isinstance(annotation, type) and is_dataclass(annotation) and isinstance(value, dict):
        return annotation.from_dict(value)
    if annotation is bytes:
        return bytes.fromhex(value) if isinstance(value, str) else bytes(value)

    if origin in (list, set, tuple):
        item_type = args[0] if args else Any
        if origin is tuple and args and args[-1] is Ellipsis:
            return tuple(_deserialize(item, args[0]) for item in value)
        if origin is tuple and args:
            return tuple(_deserialize(item, arg) for item, arg in zip(value, args))
        items = [_deserialize(item, item_type) for item in value]
        return set(items) if origin is set else items
    if origin is dict:
        key_type = args[0] if args else Any
        value_type = args[1] if len(args) > 1 else Any
        return {
            _deserialize(key, key_type): _deserialize(item, value_type)
            for key, item in value.items()
        }
    if origin is Union:
        non_none_args = [arg for arg in args if arg is not type(None)]
        for arg in non_none_args:
            try:
                return _deserialize(value, arg)
            except (TypeError, ValueError):
                continue

    return value
