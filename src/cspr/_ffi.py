"""Interpret transport results in Python, where errors can unwind normally."""

from typing import Any
from ._context import _host
from .errors import from_status


def call(name: str, *args: Any) -> Any:
    status, value = getattr(_host(), name)(*args)
    if status:
        raise from_status(status)
    return value
