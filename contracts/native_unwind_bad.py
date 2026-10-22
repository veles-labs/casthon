"""A frozen import that fails after entering its own cleanup block."""

from casthon import User

SCOPE_MARKER = 99

try:
    raise User(72)
finally:
    print("FINALLY:failed_import")
