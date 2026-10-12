"""Field-schema vocabulary shared by every configurable plugin (rules, notifiers, agents).

Plugins declare settings as a plain dict (``param_schema`` / ``config_schema``). Existing
plugins use several dialects (``"float"``/``"number"``, ``"list[str]"``/``"array"``, ...);
``normalize_schema`` maps all of them onto one canonical field description that the UI
renders as a friendly form, and ``validate_values`` checks submitted values against it.
New plugins may add ``label``, ``help``, ``unit``, ``min``/``max``/``step``, ``enum``
choices and a ``widget`` hint; nothing is required, so old schemas keep working.
"""
from __future__ import annotations

import re
from typing import Any

_TYPE_ALIASES = {
    "float": "number", "number": "number", "double": "number",
    "int": "integer", "integer": "integer",
    "bool": "boolean", "boolean": "boolean",
    "str": "string", "string": "string", "text": "string",
    "url": "url",
    "hh:mm": "time", "time": "time",
    "list[str]": "string_list", "array": "string_list", "list": "string_list",
    "list[point]": "points", "points": "points", "point": "point",
    "object": "object", "dict": "object",
    "enum": "enum",
}
_UNIT_SUFFIXES = {"seconds": "seconds", "minutes": "minutes", "mb": "MB", "fps": "fps", "days": "days"}
_CLASS_FIELDS = {"classes", "trigger_classes"}
_SECRET = re.compile(r"(token|secret|password|api_key)", re.I)
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _choices(raw: Any) -> list[dict]:
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            out.append({"value": item["value"], "label": str(item.get("label", item["value"]))})
        else:
            out.append({"value": item, "label": _humanize(str(item))})
    return out


def _canonical_type(spec: dict) -> str:
    raw = spec.get("type")
    if raw is None:
        raw = "enum" if ("enum" in spec or "values" in spec) else "any"
    return _TYPE_ALIASES.get(str(raw).lower(), "any" if "(" not in str(raw) else "string")


def normalize_schema(raw: dict | None) -> list[dict]:
    """Return a list of canonical field descriptions for a plugin's raw schema."""
    fields = []
    for name, spec in (raw or {}).items():
        if not isinstance(spec, dict):
            spec = {"type": spec if isinstance(spec, str) else "any"}
        kind = _canonical_type(spec)
        field: dict[str, Any] = {
            "name": name,
            "type": kind,
            "label": spec.get("label") or _humanize(name),
            "help": spec.get("help", ""),
            "required": bool(spec.get("required", False)),
        }
        for key in ("default", "min", "max", "step", "unit", "placeholder"):
            if key in spec:
                field[key] = spec[key]
        if "unit" not in field:
            for suffix, unit in _UNIT_SUFFIXES.items():
                if name == suffix or name.endswith("_" + suffix):
                    field["unit"] = unit
                    break
        if kind == "enum":
            field["enum"] = _choices(spec.get("enum", spec.get("values")))
        widget = spec.get("widget")
        if not widget:
            if kind == "string_list" and name in _CLASS_FIELDS:
                widget = "class_picker"
            elif kind == "points":
                widget = "line_draw" if name == "line" else "polygon_draw"
            elif kind == "point":
                widget = "point_pick"
            elif kind == "time":
                widget = "time_of_day"
            elif kind == "number" and "min" in spec and "max" in spec:
                widget = "slider"
            elif kind in ("string", "url") and _SECRET.search(name):
                widget = "secret"
            elif kind == "object":
                widget = "key_value"
        if widget:
            field["widget"] = widget
        fields.append(field)
    return fields


def _check(field: dict, value: Any) -> str | None:
    kind, label = field["type"], field["label"]
    if kind == "boolean":
        return None if isinstance(value, bool) else f"{label} must be on or off"
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{label} must be a number"
        if kind == "integer" and isinstance(value, float) and not value.is_integer():
            return f"{label} must be a whole number"
        if "min" in field and value < field["min"]:
            return f"{label} must be at least {field['min']}"
        if "max" in field and value > field["max"]:
            return f"{label} must be at most {field['max']}"
        return None
    if kind == "string":
        return None if isinstance(value, str) else f"{label} must be text"
    if kind == "url":
        ok = isinstance(value, str) and value.startswith(("http://", "https://"))
        return None if ok else f"{label} must start with http:// or https://"
    if kind == "time":
        ok = isinstance(value, str) and _TIME.match(value)
        return None if ok else f"{label} must be a time like 22:00"
    if kind == "enum":
        allowed = [c["value"] for c in field.get("enum", [])]
        return None if value in allowed else f"{label} must be one of: {', '.join(map(str, allowed))}"
    if kind == "string_list":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        return None if ok else f"{label} must be a list of text items"
    if kind == "point":
        ok = isinstance(value, (list, tuple)) and len(value) == 2 and all(
            isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)
        return None if ok else f"{label} must be an [x, y] point"
    if kind == "points":
        ok = isinstance(value, list) and all(
            isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in p)
            for p in value
        )
        return None if ok else f"{label} must be a list of [x, y] points"
    if kind == "object":
        return None if isinstance(value, dict) else f"{label} must be a set of key/value pairs"
    return None


def validate_values(raw_schema: dict | None, values: Any) -> list[dict]:
    """Validate submitted values; unknown keys are allowed (plugins read with defaults)."""
    if not isinstance(values, dict):
        return [{"field": "", "message": "settings must be an object"}]
    errors = []
    for field in normalize_schema(raw_schema):
        name = field["name"]
        if values.get(name) is None:
            if field["required"] and "default" not in field:
                errors.append({"field": name, "message": f"{field['label']} is required"})
            continue
        message = _check(field, values[name])
        if message:
            errors.append({"field": name, "message": message})
    return errors


def error_detail(errors: list[dict]) -> dict:
    """HTTP error body: a readable summary plus per-field messages the UI can attach."""
    return {"message": "; ".join(e["message"] for e in errors), "errors": errors}
