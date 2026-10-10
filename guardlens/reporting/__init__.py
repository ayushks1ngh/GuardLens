"""Pluggable daily report generators with automatic discovery."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path


class ReportGenerator:
    key = ""
    def generate(self, date, activity, events) -> dict: raise NotImplementedError


_REGISTRY = {}


def register_generator(cls):
    if not cls.key: raise ValueError("report generator must define key")
    _REGISTRY[cls.key] = cls; return cls


def get_generator(key):
    cls = _REGISTRY.get(key)
    if not cls: raise KeyError(f"unknown report generator {key}; available={sorted(_REGISTRY)}")
    return cls()


def generator_types(): return sorted(_REGISTRY)


class ReportingRuntime:
    generator = "structured"


reporting_runtime = ReportingRuntime()


def _discover():
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if not module.name.startswith("_") and module.name not in {"base"}:
            importlib.import_module(f"{__name__}.{module.name}")


_discover()
