"""Check the inherited NFT ABI's return values from an ordinary Python session."""

from cspr import ContractHash, Key, U64, UserError, export
from contracts.cep78 import Cep78


@export
def call(token: ContractHash, token_owner: Key, token_id: U64,
         expected_balance: U64, expected_metadata: str) -> None:
    if token.call(Cep78.balance_of, token_owner) != expected_balance:
        raise UserError(800)
    if token.call(Cep78.owner_of, token_id=token_id) != token_owner:
        raise UserError(801)
    if token.call(Cep78.metadata, token_id=token_id) != expected_metadata:
        raise UserError(802)
    _, package_reference = token.call(Cep78.register_owner, token_owner)
    if not package_reference.read().startswith("contract-package-"):
        raise UserError(803)
    if not token.call(Cep78.updated_receipts):
        raise UserError(804)
