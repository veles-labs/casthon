"""Only call is exported: imported CEP-18 class methods supply typed call ABIs."""

from cspr import ContractHash, Key, U256, UserError, export
from contracts.cep18 import Cep18


@export
def call(token: ContractHash, owner: Key, spender: Key, balance: U256, supply: U256,
         allowance: U256, name: str = "My Token", symbol: str = "MYT") -> None:
    if (token.call(Cep18.balance_of, owner) != balance
            or token.call(Cep18.total_supply) != supply
            or token.call(Cep18.allowance, owner, spender) != allowance
            or token.call(Cep18.name) != name
            or token.call(Cep18.symbol) != symbol
            or token.call(Cep18.decimals) != 18):
        raise UserError(77)
