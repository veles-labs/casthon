"""Live print-FD capture, including output before a revert."""

from cspr import U32, UserError, export


def nested_failure():
    raise ValueError("uncaught live failure 🐍")


@export
def call(marker: str, mode: U32 = 0) -> None:
    print(marker + ": before | Zażółć 🐍")
    try:
        if mode == 1:
            raise UserError(77)
        if mode == 2:
            nested_failure()
    finally:
        print(marker + ": finally")
