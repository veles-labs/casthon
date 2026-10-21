// Native helpers return normally; their callers propagate an exception object.
#include "py/runtime.h"
#include "py/nativeerror.h"

bool mp_native_error_pending(void) {
    return MP_STATE_THREAD(native_exception) != NULL;
}

void *mp_native_take_exception(void) {
    void *exception = MP_STATE_THREAD(native_exception);
    MP_STATE_THREAD(native_exception) = NULL;
    return exception;
}

void mp_native_unwind_callbacks(nlr_jump_callback_node_t *stop) {
    // Run stack-owned callbacks before their registering C function returns.
    void *exception = mp_native_take_exception();
    while (MP_STATE_THREAD(nlr_jump_callback_top) != stop) {
        nlr_pop_jump_callback(true);
        if (mp_native_error_pending()) exception = mp_native_take_exception();
    }
    MP_STATE_THREAD(native_exception) = exception;
}

void mp_native_catch(nlr_buf_t *frame) {
    void *exception = mp_native_take_exception();
    nlr_call_jump_callbacks(frame);
    if (mp_native_error_pending()) exception = mp_native_take_exception();
    frame->ret_val = exception;
    MP_NLR_RESTORE_PYSTACK(frame);
    nlr_pop();
}
