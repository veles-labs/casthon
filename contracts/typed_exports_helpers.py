"""Reusable functions stay normal Python when selected as typed Wasm exports."""

from cspr import U32


def calculate(amount: U32, label: str) -> U32:
    assert type(amount) is int
    return amount + len(label)
