"""Read frozen module ABIs without adding imported functions to Wasm exports."""


def _descriptions(function):
    import _cspr_exports
    import sys

    classes = sys.modules.get("cspr.contracts")
    if classes is not None and isinstance(function, (classes.BoundEntryPoint, classes.EntryPointReference)):
        return [function.describe()]

    descriptions = []
    for module_name, (signatures, positional) in _cspr_exports.MODULE_SIGNATURES.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        names = [name for name in signatures if getattr(module, name, None) is function]
        if names:
            parameters, typed_return, returns = signatures[names[0]]
            descriptions.append((names, parameters, typed_return, returns, positional[names[0]]))
    for module_name, class_name, fields, methods, events in getattr(_cspr_exports, "CLASS_SCHEMAS", ()):
        module = sys.modules.get(module_name)
        cls = getattr(module, class_name, None) if module is not None else None
        if cls is None:
            continue
        for method in methods:
            name, attribute, signature, positional = method[:4]
            if getattr(cls, attribute, None) is function:
                parameters, typed_return, returns = signature
                description = ([name], parameters, typed_return, returns, positional)
                if description not in descriptions:
                    descriptions.append(description)
    if not descriptions:
        raise ValueError("Function has not been selected as a Wasm export")
    return descriptions


def describe_call(function):
    descriptions = _descriptions(function)
    names = []
    for description in descriptions:
        for name in description[0]:
            if name not in names:
                names.append(name)
    first_names, parameters, typed_return, returns, positional = descriptions[0]
    return names, parameters, typed_return, returns, positional


def describe_function(function):
    names, parameters, typed_return, returns, positional = _descriptions(function)[0]
    return names, parameters, typed_return, returns
