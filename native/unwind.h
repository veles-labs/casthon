// Backend mechanics; no Casper completion or exception-mapping policy.
#ifndef CSPR_UNWIND_H
#define CSPR_UNWIND_H
#include "py/runtime.h"
#include "setjmp.h"

#if MICROPY_NLR_ERROR_RETURNS
#include "py/nativeerror.h"
#else
#define mp_native_error_pending() false
#define MP_NATIVE_CALL(expression, failure) (expression)
#define MP_NATIVE_CALL_VOID(expression, failure) (expression)
#define MP_NATIVE_RAISE(expression, failure) (expression)
#endif

static inline bool unwind_pending(void) {
    return mp_native_error_pending();
}

static inline void *unwind_take_exception(void) {
    #if MICROPY_NLR_ERROR_RETURNS
    return mp_native_take_exception();
    #else
    return NULL;
    #endif
}

static inline void unwind_run(void (*body)(void)) {
    #if CSPR_ASYNCIFY
    cspr_run(body);
    #else
    body();
    #endif
}
#endif
