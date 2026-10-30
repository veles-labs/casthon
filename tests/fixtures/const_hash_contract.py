"""Literal hashes must survive as bytes objects in frozen MicroPython bytecode."""
from casthon import const_blake2b, export

MINTER_ROLE = const_blake2b("MINTER_ROLE")


@export
def call() -> bytes:
    return MINTER_ROLE


@export
def inline() -> bytes:
    return const_blake2b(b"MINTER_ROLE")
