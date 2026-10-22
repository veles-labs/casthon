"""Resolve build-checked class metadata against already imported modules."""


def prepare_class(cls):
    from _cspr_exports import CLASS_SCHEMAS
    from casthon.contracts import Schema, Method
    import sys

    for module_name, class_name, field_names, methods, events in CLASS_SCHEMAS:
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, class_name, None) is cls:
            return Schema(cls, [getattr(cls, name) for name in field_names],
                          [Method(*method) for method in methods],
                          tuple(getattr(sys.modules[owner], name) for owner, name in events))
    raise ValueError("Class has no frozen contract schema")
