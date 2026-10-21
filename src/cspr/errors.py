"""Python exceptions mapped to Casper errors at the outer Wasm dispatcher."""

from . import api_error


class Ret(BaseException):
    """Complete the invocation with serialized CLValue bytes after unwinding."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload


class Revert(BaseException):
    """Request a Casper revert after Python exception handlers have run."""

    def __init__(self, code: int) -> None:
        self.code = code

    def __str__(self) -> str:
        return str(self.code)


class ApiError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code

    def __str__(self) -> str:
        return str(self.code)


class User(ApiError):
    def __init__(self, code: int) -> None:
        ApiError.__init__(self, api_error.user(code))


UserError = User


class MissingKey(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.MISSING_KEY)


class MissingArgument(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.MISSING_ARGUMENT)


class InvalidPurse(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.INVALID_PURSE)


class InvalidArgument(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.INVALID_ARGUMENT)


class Read(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.READ)


class ValueNotFound(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.VALUE_NOT_FOUND)


class DictionaryItemKeyExceedsLength(ApiError):
    def __init__(self) -> None:
        ApiError.__init__(self, api_error.DICTIONARY_ITEM_KEY_EXCEEDS_LENGTH)


class ABIError(ValueError):
    pass


def from_status(code: int) -> ApiError:
    """Preserve every host error code, using known subclasses where available."""
    if code == api_error.MISSING_ARGUMENT:
        return MissingArgument()
    if code == api_error.INVALID_ARGUMENT:
        return InvalidArgument()
    if code == api_error.READ:
        return Read()
    if code == api_error.VALUE_NOT_FOUND:
        return ValueNotFound()
    if code == api_error.INVALID_PURSE:
        return InvalidPurse()
    if code == api_error.MISSING_KEY:
        return MissingKey()
    if code == api_error.DICTIONARY_ITEM_KEY_EXCEEDS_LENGTH:
        return DictionaryItemKeyExceedsLength()
    if 65536 <= code <= 131071:
        return User(code - 65536)
    return ApiError(code)
