"""A stored NFT caller and transfer filter, importing the base ABI only."""

from cspr import ContractHash, Key, MISSING, OptionalArg, U8, U64, URef, export
from cspr.contract_api import storage
from cspr.contract_api.runtime import named_keys
from cspr.contracts import Contract, entry_point, export_contract
from contracts.cep78 import Cep78


@export_contract
class NftClient(Contract):
    token: ContractHash
    allowed: URef[bool]
    last_source: URef[Key]
    last_target: URef[Key]

    @entry_point
    def mint(self, token_owner: Key, token_meta_data: str) -> tuple[str, Key, str]:
        return self.token.call(Cep78.mint, token_owner, token_meta_data)

    @entry_point
    def approve(self, spender: Key, token_id: U64) -> None:
        self.token.call(Cep78.approve, spender, token_id=token_id)

    @entry_point
    def transfer(self, source_key: Key, target_key: Key, token_id: U64) -> tuple[str, Key]:
        return self.token.call(Cep78.transfer, source_key, target_key, token_id=token_id)

    @entry_point
    def burn(self, token_id: U64) -> None:
        self.token.call(Cep78.burn, token_id=token_id)

    @entry_point
    def can_transfer(self, source_key: Key, target_key: Key,
                     token_id: OptionalArg[U64] = MISSING) -> U8:
        self.last_source.write(source_key)
        self.last_target.write(target_key)
        return int(self.allowed.read())


@export
def call(token: ContractHash) -> None:
    client = NftClient(token=token, allowed=True, last_source=token, last_target=token)
    package, access = storage.create_contract_package_at_hash()
    contract, _ = package.add_contract_version(client)
    named_keys["nft_client"] = contract
    named_keys["nft_client_package"] = package
    named_keys["nft_client_access"] = access
