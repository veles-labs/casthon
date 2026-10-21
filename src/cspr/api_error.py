"""Numeric ApiError codes from casper-node/types/src/api_error.rs."""

MISSING_ARGUMENT = 2
INVALID_ARGUMENT = 3
READ = 5
VALUE_NOT_FOUND = 6
INVALID_PURSE = 12
MISSING_KEY = 24
DICTIONARY_ITEM_KEY_EXCEEDS_LENGTH = 36


def user(code: int) -> int:
    if type(code) is not int or not 0 <= code <= 65535:
        raise ValueError("User error must fit u16")
    return 65536 + code
