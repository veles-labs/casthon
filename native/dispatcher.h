// Invocation orchestration; lifecycle, backend mechanics and policy are separate.
#include "interpreter.h"
#include "unwind.h"
#include "outcome.h"

static const char *dispatch_entry;
static enum dispatch_phase invocation_phase;

// Keep the continuation boundary below cspr_run, even with LTO enabled.
__attribute__((noinline)) static void dispatch_body(void) {
    nlr_buf_t boundary;
    if (nlr_push(&boundary) == 0) {
        // Preload the SDK outside another Python import frame (500 stack slots).
        mp_obj_t sdk = mp_import_name(MP_QSTR_cspr, mp_const_none, MP_OBJ_NEW_SMALL_INT(0));
        check_bootstrap();
        bind_sdk_outcomes(sdk);
        mp_obj_t module = mp_import_name(MP_QSTR__cspr_dispatcher, mp_const_none, MP_OBJ_NEW_SMALL_INT(0));
        check_bootstrap();
        bind_return_validator(module);
        mp_obj_t function = mp_load_attr(module, MP_QSTR_dispatch);
        check_bootstrap();
        mp_obj_t argument = mp_obj_new_str(dispatch_entry, strlen(dispatch_entry));
        check_bootstrap();

        // Contract import, user code and return serialization belong to this stage.
        invocation_phase = DISPATCH_CONTRACT;
        // Import directly at the outer boundary, preserving Python import order
        // without retaining a dispatcher VM frame beneath nested mixin imports.
        mp_obj_t contract = mp_import_name(MP_QSTR_contract, mp_const_none, MP_OBJ_NEW_SMALL_INT(0));
        if (unwind_pending()) complete_exception(unwind_take_exception(), DISPATCH_CONTRACT);
        mp_obj_t result = mp_call_function_2(function, argument, contract);
        if (unwind_pending()) complete_exception(unwind_take_exception(), DISPATCH_CONTRACT);
        nlr_pop();
        if (result != mp_const_none) complete_return(result, false);
    } else {
        complete_exception(boundary.ret_val, invocation_phase);
    }
}

void cspr_dispatch(const char *entry) {
    interpreter_start();
    reset_outcomes();
    dispatch_entry = entry;
    invocation_phase = DISPATCH_BOOTSTRAP;
    unwind_run(dispatch_body);
    interpreter_stop();
}
