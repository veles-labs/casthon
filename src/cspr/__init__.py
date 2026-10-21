"""Casper data types; host functions live in cspr.contract_api."""

from typing import Any, Callable, TypeVar

from . import api_error as api_error

from .errors import (
    Ret as Ret, Revert as Revert, ApiError as ApiError, User as User, UserError as UserError,
    MissingKey as MissingKey, MissingArgument as MissingArgument,
    InvalidArgument as InvalidArgument, InvalidPurse as InvalidPurse,
    Read as Read, ValueNotFound as ValueNotFound,
    DictionaryItemKeyExceedsLength as DictionaryItemKeyExceedsLength,
)
from .key import (
    Key as Key,
    AccountHash as AccountHash,
    Hash as Hash,
    ContractHash as ContractHash,
    ContractPackageHash as ContractPackageHash,
    URef as URef,
    TransferHash as TransferHash,
    DeployInfo as DeployInfo,
    EraInfo as EraInfo,
    Balance as Balance,
    Bid as Bid,
    Withdraw as Withdraw,
    DictionaryAddress as DictionaryAddress,
    SystemEntityRegistry as SystemEntityRegistry,
    EraSummary as EraSummary,
    Unbond as Unbond,
    ChainspecRegistry as ChainspecRegistry,
    ChecksumRegistry as ChecksumRegistry,
    BidAddress as BidAddress,
    PackageHash as PackageHash,
    AddressableEntity as AddressableEntity,
    SystemEntity as SystemEntity,
    AccountEntity as AccountEntity,
    ContractEntity as ContractEntity,
    ByteCode as ByteCode,
    Message as Message,
    NamedKeyAddress as NamedKeyAddress,
    BlockGlobal as BlockGlobal,
    BalanceHold as BalanceHold,
    EntryPointAddress as EntryPointAddress,
    State as State,
    base64 as base64,
)
from .enums import (
    WireEnum as WireEnum,
    Phase as Phase, ActionType as ActionType, AddKeyFailure as AddKeyFailure,
    RemoveKeyFailure as RemoveKeyFailure, UpdateKeyFailure as UpdateKeyFailure,
    SetThresholdFailure as SetThresholdFailure, SystemEntityType as SystemEntityType,
    TransferredTo as TransferredTo, HashAlgorithm as HashAlgorithm,
    MessageTopicOperation as MessageTopicOperation, EntryPointAccess as EntryPointAccess,
    EntryPointType as EntryPointType, EntryPointPayment as EntryPointPayment,
)
from .types import (
    Map as Map,
    CLType as CLType,
    cl_type_of as cl_type_of,
    U8 as U8,
    U32 as U32,
    U64 as U64,
    U256 as U256,
    U512 as U512,
    wire_type as wire_type,
)
from .codec import ABIError as ABIError

from .entry_points import EntryPoint as EntryPoint

from .values import (
    CLValue as CLValue,
    CLU8 as CLU8,
    CLU32 as CLU32,
    CLU64 as CLU64,
    CLU256 as CLU256,
    CLU512 as CLU512,
    CLString as CLString,
    CLBool as CLBool,
    CLKey as CLKey,
    CLKeyList as CLKeyList,
    CLSecurityMap as CLSecurityMap,
    CLBytes as CLBytes,
    CLUnit as CLUnit,
    SerializedCLValue as SerializedCLValue,
)

from .arguments import OptionalArg as OptionalArg, MISSING as MISSING, MissingType as MissingType
from .references import Dictionary as Dictionary
from .crypto import (
    PublicKey as PublicKey, SystemPublicKey as SystemPublicKey,
    Ed25519PublicKey as Ed25519PublicKey, Secp256k1PublicKey as Secp256k1PublicKey,
    Signature as Signature, Ed25519Signature as Ed25519Signature,
    Secp256k1Signature as Secp256k1Signature,
)

from .messages import MessagePayload as MessagePayload, MessageString as MessageString, MessageBytes as MessageBytes
from .caller import (
    CallerInfo as CallerInfo, AccountCaller as AccountCaller, EntityCaller as EntityCaller,
    ContractCaller as ContractCaller, CallStackElement as CallStackElement, Session as Session,
    StoredSession as StoredSession, StoredContract as StoredContract,
)


_ExportFunction = TypeVar("_ExportFunction", bound=Callable[..., Any])


def export(function: _ExportFunction) -> _ExportFunction:
    """Select a Wasm export; annotations apply only at its invocation boundary."""
    return function

from .events import (
    Event as Event, MessageEncoder as MessageEncoder, Bytesrepr as Bytesrepr,
    Json as Json, JsonBytes as JsonBytes, emit as emit,
)
