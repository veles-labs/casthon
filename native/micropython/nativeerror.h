// Explicit exception returns for the frozen Casper interpreter profile.
#ifndef MICROPY_INCLUDED_PY_NATIVEERROR_H
#define MICROPY_INCLUDED_PY_NATIVEERROR_H
#include <stdbool.h>
struct _nlr_buf_t;
struct _nlr_jump_callback_node_t;
bool mp_native_error_pending(void);
void *mp_native_take_exception(void);
void mp_native_catch(struct _nlr_buf_t *frame);
void mp_native_unwind_callbacks(struct _nlr_jump_callback_node_t *stop);
#define MP_NATIVE_CALL(expression, failure) ({ \
    __auto_type native_result_ = (expression); \
    if (mp_native_error_pending()) { failure } \
    native_result_; })
#define MP_NATIVE_CALL_VOID(expression, failure) ({ \
    expression; if (mp_native_error_pending()) { failure } })
#define MP_NATIVE_RAISE(expression, failure) ({ expression; failure })
#endif
