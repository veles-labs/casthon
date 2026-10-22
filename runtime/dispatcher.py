"""Invoke ordinary Python through frozen signatures; error policy lives in C."""

from _cspr_exports import SIGNATURES
from casthon._dispatch import invoke
from casthon.return_value import validate_return_payload
import _cspr_exports

# Load the class SDK before importing nested application mixins. This keeps
# interpreter bootstrap below Casper's stock 500-slot native stack limit.
if getattr(_cspr_exports, "CLASS_SCHEMAS", None):
    import casthon.contracts


def dispatch(entry, contract):
    binding = getattr(_cspr_exports, "BINDINGS", {}).get(entry)
    if binding is None:
        function = getattr(contract, entry)
    else:
        class_name, attribute = binding
        function = getattr(getattr(contract, class_name).bind(), attribute)
    return invoke(function, SIGNATURES[entry])
