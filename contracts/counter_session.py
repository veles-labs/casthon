"""Call a deployed counter using its Python functions as the typed ABI."""

from cspr import ContractHash, U32, UserError, export
from contracts.counter import Counter


@export
def call(contract: ContractHash, amount: U32, expected: U32) -> U32:
    contract.call(Counter.increment_by, amount)
    value = contract.call(Counter.get)
    if value != expected:
        raise UserError(1)
    return value
