"""Audited stackless calls and explicit native exception-return patches."""
import difflib
import hashlib
import json
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parents[1] / "native/micropython"
VERSION = json.loads((HERE.parent / "toolchain.json").read_text())["micropython"]["version"]


def replace(source, old, new, count=1):
    actual = source.count(old)
    if actual != count:
        raise ValueError(f"Pinned source mismatch: expected {count} occurrences, got {actual}: {old[:80]}")
    return source.replace(old, new)


def calls_patch(files):
    files["py/obj.h"] = replace(files["py/obj.h"],
        "mp_obj_t mp_obj_new_bound_meth(mp_obj_t meth, mp_obj_t self);",
        """mp_obj_t mp_obj_new_bound_meth(mp_obj_t meth, mp_obj_t self);
#if MICROPY_STACKLESS
bool mp_obj_bound_meth_unpack(mp_obj_t object, mp_obj_t *function, mp_obj_t *self);
bool mp_obj_closure_unpack(mp_obj_t object, mp_obj_t *function, size_t *count, const mp_obj_t **closed);
#endif""")
    files["py/bc.h"] = replace(files["py/bc.h"],
        "mp_code_state_t *mp_obj_fun_bc_prepare_codestate(mp_obj_t func, size_t n_args, size_t n_kw, const mp_obj_t *args);",
        """mp_code_state_t *mp_obj_fun_bc_prepare_codestate(mp_obj_t func, size_t n_args, size_t n_kw, const mp_obj_t *args);
bool mp_obj_fun_is_stackless(mp_obj_t function);
mp_code_state_t *mp_obj_fun_prepare_stackless(mp_obj_t function, size_t n_args, size_t n_kw, const mp_obj_t *args);""")
    files["py/bc.h"] = replace(files["py/bc.h"],
        "    struct _mp_code_state_t *prev;",
        """    struct _mp_code_state_t *prev;
    #if MICROPY_ENABLE_PYSTACK
    // Free flattened call arguments together with the callee frame.
    void *stackless_alloc_start;
    #endif""")
    files["py/objboundmeth.c"] += """
#if MICROPY_STACKLESS
bool mp_obj_bound_meth_unpack(mp_obj_t object, mp_obj_t *function, mp_obj_t *self) {
    if (!mp_obj_is_type(object, &mp_type_bound_meth)) {
        return false;
    }
    const mp_obj_bound_meth_t *method = MP_OBJ_TO_PTR(object);
    *function = method->meth;
    *self = method->self;
    return true;
}
#endif
"""
    files["py/objclosure.c"] += """
#if MICROPY_STACKLESS
bool mp_obj_closure_unpack(mp_obj_t object, mp_obj_t *function, size_t *count, const mp_obj_t **closed) {
    if (!mp_obj_is_type(object, &mp_type_closure)) {
        return false;
    }
    const mp_obj_closure_t *closure = MP_OBJ_TO_PTR(object);
    *function = closure->fun;
    *count = closure->n_closed;
    *closed = closure->closed;
    return true;
}
#endif
"""
    files["py/objfun.c"] += """
#if MICROPY_STACKLESS
// Follow wrappers without invoking their recursive C -> VM call paths.
bool mp_obj_fun_is_stackless(mp_obj_t function) {
    for (;;) {
        if (mp_obj_is_type(function, &mp_type_fun_bc)) {
            return true;
        }
        mp_obj_t self;
        size_t count;
        const mp_obj_t *closed;
        if (mp_obj_bound_meth_unpack(function, &function, &self)
            || mp_obj_closure_unpack(function, &function, &count, &closed)) {
            continue;
        }
        return false;
    }
}

mp_code_state_t *mp_obj_fun_prepare_stackless(mp_obj_t function, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    if (mp_obj_is_type(function, &mp_type_fun_bc)) {
        return mp_obj_fun_bc_prepare_codestate(function, n_args, n_kw, args);
    }
    mp_obj_t target = function;
    size_t prefix = 0;
    for (;;) {
        mp_obj_t self;
        size_t count;
        const mp_obj_t *closed;
        if (mp_obj_bound_meth_unpack(target, &target, &self)) {
            ++prefix;
        } else if (mp_obj_closure_unpack(target, &target, &count, &closed)) {
            prefix += count;
        } else {
            break;
        }
    }
    assert(mp_obj_is_type(target, &mp_type_fun_bc));
    size_t total = prefix + n_args + 2 * n_kw;
    mp_obj_t small_args[8];
    mp_obj_t *expanded = total <= MP_ARRAY_SIZE(small_args) ? small_args : m_new(mp_obj_t, total);
    memcpy(expanded + prefix, args, (n_args + 2 * n_kw) * sizeof(mp_obj_t));
    // Inner wrappers prepend their arguments before outer wrappers' arguments.
    size_t offset = prefix;
    while (function != target) {
        mp_obj_t self;
        size_t count;
        const mp_obj_t *closed;
        if (mp_obj_bound_meth_unpack(function, &function, &self)) {
            expanded[--offset] = self;
        } else if (mp_obj_closure_unpack(function, &function, &count, &closed)) {
            offset -= count;
            memcpy(expanded + offset, closed, count * sizeof(mp_obj_t));
        }
    }
    mp_code_state_t *state = mp_obj_fun_bc_prepare_codestate(target, n_args + prefix, n_kw, expanded);
    if (expanded != small_args) {
        m_del(mp_obj_t, expanded, total);
    }
    return state;
}
#endif
"""
    files["py/vm.c"] = replace(files["py/vm.c"],
        "if (mp_obj_get_type(*sp) == &mp_type_fun_bc)", "if (mp_obj_fun_is_stackless(*sp))", 4)
    files["py/vm.c"] = replace(files["py/vm.c"],
        "mp_obj_fun_bc_prepare_codestate(", "mp_obj_fun_prepare_stackless(", 4)
    files["py/vm.c"] = replace(files["py/vm.c"],
        "                    if (mp_obj_fun_is_stackless(*sp)) {",
        """                    if (mp_obj_fun_is_stackless(*sp)) {
                        #if MICROPY_ENABLE_PYSTACK
                        void *allocation_start = MP_STATE_THREAD(pystack_cur);
                        #endif""", 4)
    files["py/vm.c"] = replace(files["py/vm.c"],
        "                            new_state->prev = code_state;",
        """                            new_state->prev = code_state;
                            #if MICROPY_ENABLE_PYSTACK
                            new_state->stackless_alloc_start = allocation_start;
                            #endif""", 4)
    files["py/vm.c"] = replace(files["py/vm.c"],
        "mp_nonlocal_free(code_state, sizeof(mp_code_state_t));",
        "mp_nonlocal_free(code_state->stackless_alloc_start, sizeof(mp_code_state_t));", 2)


def errors_patch(files):
    files["py/runtime.c"] = replace(files["py/runtime.c"],
        '#include "py/objtuple.h"', '#include "py/objtuple.h"\n#include "py/objint.h"')
    files["py/runtime.h"] = replace(files["py/runtime.h"],
        "mp_obj_t mp_binary_op(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs);",
        """mp_obj_t mp_binary_op(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs);
// Experimental checked entry: only integer zero-division uses error returns.
mp_obj_t mp_binary_op_checked(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs, mp_obj_t *error);""")
    files["py/objint.h"] = replace(files["py/objint.h"],
        "mp_obj_t mp_obj_int_binary_op(mp_binary_op_t op, mp_obj_t lhs_in, mp_obj_t rhs_in);",
        """mp_obj_t mp_obj_int_binary_op(mp_binary_op_t op, mp_obj_t lhs_in, mp_obj_t rhs_in);
mp_obj_t mp_obj_int_binary_op_checked(mp_binary_op_t op, mp_obj_t lhs_in, mp_obj_t rhs_in, mp_obj_t *error);""")
    files["py/runtime.c"] = replace(files["py/runtime.c"],
        "mp_obj_t MICROPY_WRAP_MP_BINARY_OP(mp_binary_op)(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs) {",
        "static mp_obj_t binary_op_impl(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs, mp_obj_t *error) {")
    marker = """generic_binary_op:
    type = mp_obj_get_type(lhs);
    if (MP_OBJ_TYPE_HAS_SLOT(type, binary_op)) {"""
    files["py/runtime.c"] = replace(files["py/runtime.c"], marker, """generic_binary_op:
    type = mp_obj_get_type(lhs);
    #if MICROPY_LONGINT_IMPL == MICROPY_LONGINT_IMPL_MPZ
    if (error != NULL && type == &mp_type_int) {
        mp_obj_t result = mp_obj_int_binary_op_checked(op, lhs, rhs, error);
        if (*error != MP_OBJ_NULL || result != MP_OBJ_NULL) {
            return result;
        }
    } else
    #endif
    if (MP_OBJ_TYPE_HAS_SLOT(type, binary_op)) {""")
    marker = """zero_division:
    mp_raise_msg(&mp_type_ZeroDivisionError, MP_ERROR_TEXT("divide by zero"));
}

mp_obj_t mp_call_function_0"""
    files["py/runtime.c"] = replace(files["py/runtime.c"], marker, """zero_division:
    if (error != NULL) {
        *error = mp_obj_new_exception_msg(&mp_type_ZeroDivisionError, MP_ERROR_TEXT("divide by zero"));
        return MP_OBJ_NULL;
    }
    mp_raise_msg(&mp_type_ZeroDivisionError, MP_ERROR_TEXT("divide by zero"));
}

mp_obj_t MICROPY_WRAP_MP_BINARY_OP(mp_binary_op)(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs) {
    // Unconverted native callers keep their existing non-returning error ABI.
    return binary_op_impl(op, lhs, rhs, NULL);
}

mp_obj_t mp_binary_op_checked(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs, mp_obj_t *error) {
    *error = MP_OBJ_NULL;
    // Keep integer-like booleans on this checked path, without changing identity.
    if (op == MP_BINARY_OP_FLOOR_DIVIDE || op == MP_BINARY_OP_INPLACE_FLOOR_DIVIDE
        || op == MP_BINARY_OP_MODULO || op == MP_BINARY_OP_INPLACE_MODULO
        || op == MP_BINARY_OP_DIVMOD) {
        if (lhs == mp_const_false || lhs == mp_const_true) {
            lhs = MP_OBJ_NEW_SMALL_INT(lhs == mp_const_true);
        }
        if (rhs == mp_const_false || rhs == mp_const_true) {
            rhs = MP_OBJ_NEW_SMALL_INT(rhs == mp_const_true);
        }
    }
    return binary_op_impl(op, lhs, rhs, error);
}

mp_obj_t mp_call_function_0""")
    files["py/objint_mpz.c"] = replace(files["py/objint_mpz.c"],
        "mp_obj_t mp_obj_int_binary_op(mp_binary_op_t op, mp_obj_t lhs_in, mp_obj_t rhs_in) {",
        "static mp_obj_t int_binary_op_impl(mp_binary_op_t op, mp_obj_t lhs_in, mp_obj_t rhs_in, mp_obj_t *error) {")
    # Return before allocating the tentative MPZ result; no discarded partial result.
    marker = """    #if MICROPY_PY_BUILTINS_FLOAT
    if (op == MP_BINARY_OP_TRUE_DIVIDE || op == MP_BINARY_OP_INPLACE_TRUE_DIVIDE) {"""
    files["py/objint_mpz.c"] = replace(files["py/objint_mpz.c"], marker, """    if (error != NULL && mpz_is_zero(zrhs)
        && (op == MP_BINARY_OP_FLOOR_DIVIDE || op == MP_BINARY_OP_INPLACE_FLOOR_DIVIDE
            || op == MP_BINARY_OP_MODULO || op == MP_BINARY_OP_INPLACE_MODULO
            || op == MP_BINARY_OP_DIVMOD)) {
        *error = mp_obj_new_exception_msg(&mp_type_ZeroDivisionError, MP_ERROR_TEXT("divide by zero"));
        return MP_OBJ_NULL;
    }

""" + marker)
    # Insert wrappers outside the optional pow3 feature guard.
    marker = "#if MICROPY_PY_BUILTINS_POW3"
    files["py/objint_mpz.c"] = replace(files["py/objint_mpz.c"], marker, """mp_obj_t mp_obj_int_binary_op(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs) {
    return int_binary_op_impl(op, lhs, rhs, NULL);
}

mp_obj_t mp_obj_int_binary_op_checked(mp_binary_op_t op, mp_obj_t lhs, mp_obj_t rhs, mp_obj_t *error) {
    return int_binary_op_impl(op, lhs, rhs, error);
}

""" + marker)
    marker = "SET_TOP(mp_binary_op(ip[-1] - MP_BC_BINARY_OP_MULTI, lhs, rhs));"
    if files["py/vm.c"].count(marker) != 2:
        raise ValueError("Pinned binary opcode source mismatch")
    replacement = """mp_obj_t error;
mp_obj_t result = mp_binary_op_checked(ip[-1] - MP_BC_BINARY_OP_MULTI, lhs, rhs, &error);
if (error != MP_OBJ_NULL) {
    RAISE(error);
}
SET_TOP(result);"""
    files["py/vm.c"] = re.sub(r"(?m)^([ \t]*)" + re.escape(marker) + r"$",
        lambda match: "\n".join(match[1] + line for line in replacement.splitlines()), files["py/vm.c"])


def native_errors_patch(files):
    """Apply reviewed call-site checks; production builds do not run Clang AST analysis."""
    recipe = json.loads((HERE / "native-error-edits.json").read_text())
    port = HERE / "port/mpconfigport.h"
    if hashlib.sha256(port.read_bytes()).hexdigest() != recipe["portConfigSha256"]:
        raise ValueError("Native exception recipe needs regeneration for this port configuration")
    if hashlib.sha256((HERE / "port/Makefile").read_bytes()).hexdigest() != recipe["portMakefileSha256"]:
        raise ValueError("Native exception recipe needs regeneration for these compiler flags")
    for name, plan in recipe["files"].items():
        source = files[name].encode()
        if hashlib.sha256(source).hexdigest() != plan["sha256"]:
            raise ValueError("Native exception recipe source mismatch: " + name)
        for offset, text in sorted(plan["insertions"].items(), key=lambda item: int(item[0]), reverse=True):
            index = int(offset)
            source = source[:index] + text.encode("latin1") + source[index:]
        files[name] = '#include "py/nativeerror.h"\n' + source.decode()
    for name in ("nativeerror.c", "nativeerror.h"):
        files["py/" + name] = (HERE / name).read_text()
    files["py/mpstate.h"] = replace(files["py/mpstate.h"],
        "    volatile mp_obj_t mp_pending_exception;",
        "    volatile mp_obj_t mp_pending_exception;\n    void *native_exception;")
    files["py/nlrsetjmp.c"] = replace(files["py/nlrsetjmp.c"],
        "    MP_NLR_JUMP_HEAD(val, top);\n    longjmp(top->jmpbuf, 1);",
        "    MP_STATE_THREAD(native_exception) = val;")
    files["py/py.mk"] = replace(files["py/py.mk"], "\tmpstate.o \\\n", "\tmpstate.o \\\n\tnativeerror.o \\\n")


def expected_sources(archive, profile):
    original = {}
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if member.isfile():
                name = str(Path(member.name).relative_to(f"micropython-{VERSION}"))
                original[name] = tar.extractfile(member).read()
    edits = {name: data.decode() for name, data in original.items() if name.startswith("py/") and name.endswith((".c", ".h", ".mk"))}
    diffs = []
    for name, transform in (("stackless-calls.patch", calls_patch), ("integer-errors.patch", errors_patch),
                            ("native-errors.patch", native_errors_patch)):
        profiles = {"stackless-calls.patch": ("calls", "errors", "native-errors"),
                    "integer-errors.patch": ("errors", "native-errors"),
                    "native-errors.patch": ("native-errors",)}
        if profile not in profiles[name]:
            continue
        before = dict(edits)
        transform(edits)
        diff = "".join("".join(difflib.unified_diff(before.get(path, "").splitlines(True), edits[path].splitlines(True),
            fromfile="a/" + path if path in before else "/dev/null", tofile="b/" + path))
            for path in sorted(edits) if edits[path] != before.get(path))
        patch = HERE / name
        # The checked-in review artifact must match the executable patch recipe.
        if patch.exists() and patch.read_text() != diff:
            raise ValueError("Review patch differs from recipe: " + name)
        patch.write_text(diff)
        diffs.append({"file": name, "sha256": hashlib.sha256(diff.encode()).hexdigest()})
    expected = {**original, **{name: text.encode() for name, text in edits.items()}}
    changed = [name for name in sorted(expected) if expected[name] != original.get(name)]
    return original, expected, changed, diffs


def prepare_and_verify(archive, source, profile):
    original, expected, changed, diffs = expected_sources(archive, profile)
    for name in expected:
        path = source / name
        actual = path.read_bytes() if path.exists() else None
        if actual == original.get(name) and actual != expected[name]:
            path.write_bytes(expected[name])
        elif actual != expected[name]:
            raise ValueError("Unexpected source change: " + name)
    return expected, changed, diffs


def verify(source, expected):
    for name, data in expected.items():
        if (source / name).read_bytes() != data:
            raise ValueError("Source drift after patch/compile: " + name)
    return len(expected)
