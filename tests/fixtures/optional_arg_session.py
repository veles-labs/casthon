"""A session calls presence-aware exports without importing their Wasm exports."""

from cspr import ContractHash, MISSING, UserError, export
from contracts.typed_exports import presence, presence_default, presence_number


@export
def call(contract: ContractHash) -> None:
    if (contract.call(presence) != "missing"
            or contract.call(presence, MISSING) != "missing"
            or contract.call(presence, None) != "none"
            or contract.call(presence, 0) != "0"
            or contract.call(presence, 7) != "7"
            or contract.call(presence_default) != "none"
            or contract.call(presence_default, None) != "none"
            or contract.call(presence_number) != "7"
            or contract.call(presence_number, 0) != "0"):
        raise UserError(77)
