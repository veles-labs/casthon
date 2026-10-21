// Outer export outcome policy, shared by both unwinding backends.
#ifndef CSPR_OUTCOME_H
#define CSPR_OUTCOME_H
#include "unwind.h"

#if CSPR_DEBUG
#define DISPATCH_DIAGNOSTIC(...) mp_printf(&mp_plat_print, __VA_ARGS__)

typedef struct {
    size_t used;
    uint8_t data[4 + 256];
} diagnostic_buffer;

static void flush_diagnostic(diagnostic_buffer *buffer) {
    if (!buffer->used) return;
    put_u32(buffer->data, buffer->used);
    casper_print(buffer->data, 4 + buffer->used);
    buffer->used = 0;
}

static void diagnostic_strn(void *context, const char *text, size_t length) {
    diagnostic_buffer *buffer = context;
    for (size_t i = 0; i < length; i++) {
        uint8_t byte = (uint8_t)text[i];
        // Reserve a full UTF-8 code point when a long line needs splitting.
        if (buffer->used >= 252 && (byte & 0xc0) != 0x80) flush_diagnostic(buffer);
        buffer->data[4 + buffer->used++] = byte;
        if (byte == '\n') flush_diagnostic(buffer);
    }
}

static void print_exception_guarded(const mp_print_t *printer, const char *stage, mp_obj_t error) {
    // Exception arguments can run Python __str__ code while being printed.
    // Diagnostics must not replace the original outcome if formatting raises.
    nlr_buf_t guard;
    if (nlr_push(&guard) == 0) {
        mp_printf(printer, "C_DISPATCH_%s:%s\n", stage,
            qstr_str(mp_obj_get_type(error)->name));
        if (!unwind_pending()) mp_obj_print_exception(printer, error);
        nlr_pop();
    }
    (void)unwind_take_exception();
}

static void report_exception(const char *stage, mp_obj_t error) {
    // Keep the buffer outside the setjmp frame so it survives a formatting
    // exception. The node adds a newline per host call: send complete lines.
    diagnostic_buffer buffer = {0};
    mp_print_t printer = {&buffer, diagnostic_strn};
    print_exception_guarded(&printer, stage, error);
    flush_diagnostic(&buffer);
}
#else
#define DISPATCH_DIAGNOSTIC(...) ((void)0)
#define report_exception(stage, error) ((void)0)
#endif

enum { BOOTSTRAP_ERROR = 65536 + 2, UNEXPECTED_ERROR = 65536 + 610 };
enum dispatch_phase { DISPATCH_BOOTSTRAP, DISPATCH_CONTRACT };
static mp_obj_t api_exception_type;
static mp_obj_t abi_error_type;
static mp_obj_t revert_exception_type;
static mp_obj_t ret_exception_type;
static mp_obj_t validate_return_payload;

static void invalid_api_code(void) {
#if CSPR_DEBUG
    const char text[] = "C_DISPATCH_INVALID_API_CODE\n";
    uint8_t buffer[4 + sizeof(text) - 1];
    put_u32(buffer, sizeof(text) - 1);
    memcpy(buffer + 4, text, sizeof(text) - 1);
    casper_print(buffer, sizeof(buffer));
#endif
    casper_revert(ABI_ERROR);
}

static uint32_t exception_code(mp_obj_t error) {
    // Attribute access and uint32 conversion can themselves raise.
    nlr_buf_t guard;
    if (nlr_push(&guard) == 0) {
        mp_obj_t code = mp_load_attr(error, MP_QSTR_code);
        if (unwind_pending()) invalid_api_code();
        if (!mp_obj_is_int(code)) invalid_api_code();
        mp_uint_t number = mp_obj_get_uint(code);
        if (unwind_pending()) invalid_api_code();
        nlr_pop();
        return (uint32_t)number;
    }
    invalid_api_code();
    __builtin_unreachable();
}

static bool is_revert(mp_obj_t type) {
    return revert_exception_type && mp_obj_is_subclass_fast(type, revert_exception_type);
}

static void invalid_ret_payload(void) {
#if CSPR_DEBUG
    const char text[] = "C_DISPATCH_INVALID_RET_PAYLOAD\n";
    uint8_t buffer[4 + sizeof(text) - 1];
    put_u32(buffer, sizeof(text) - 1);
    memcpy(buffer + 4, text, sizeof(text) - 1);
    casper_print(buffer, sizeof(buffer));
#endif
    casper_revert(ABI_ERROR);
}

static void complete_return(mp_obj_t result, bool signal) {
    nlr_buf_t guard;
    if (nlr_push(&guard) == 0) {
        mp_obj_t data = signal ? mp_load_attr(result, MP_QSTR_payload) : result;
        if (unwind_pending()) invalid_ret_payload();
        if (!mp_obj_is_type(data, &mp_type_bytes)) invalid_ret_payload();
        // Ordinary results were validated in Python; raw Ret signals need checking.
        if (signal) mp_call_function_1(validate_return_payload, data);
        if (unwind_pending()) invalid_ret_payload();
        mp_buffer_info_t bytes;
        mp_get_buffer_raise(data, &bytes, MP_BUFFER_READ);
        nlr_pop();
        casper_ret(bytes.buf, bytes.len);
    }
    invalid_ret_payload();
}

static void complete_exception(void *value, enum dispatch_phase phase) {
    mp_obj_t error = MP_OBJ_FROM_PTR(value);
    mp_obj_t type = MP_OBJ_FROM_PTR(mp_obj_get_type(error));
#if CSPR_DEBUG
    const char *name = qstr_str(mp_obj_get_type(error)->name);
#endif
    if (phase == DISPATCH_BOOTSTRAP) {
        // Preserve the bootstrap policy: ordinary errors (including ApiError
        // and Ret) are fatal User(2); known ABIError/Revert keep their mapping.
        uint32_t code = BOOTSTRAP_ERROR;
        if (abi_error_type && type == abi_error_type) code = ABI_ERROR;
        if (is_revert(type)) code = exception_code(error);
        report_exception("BOOTSTRAP", error);
        casper_revert(code);
    }
    if (ret_exception_type && mp_obj_is_subclass_fast(type, ret_exception_type)) {
        DISPATCH_DIAGNOSTIC("C_DISPATCH_RET:%s\n", name);
        complete_return(error, true);
    }
    if (abi_error_type && mp_obj_is_subclass_fast(type, abi_error_type)) {
        report_exception("ABI", error);
        casper_revert(ABI_ERROR);
    }
    if (is_revert(type)) {
        uint32_t code = exception_code(error);
        report_exception("REVERT", error);
        casper_revert(code);
    }
    if (api_exception_type && mp_obj_is_subclass_fast(type, api_exception_type)) {
        uint32_t code = exception_code(error);
        report_exception("API", error);
        casper_revert(code);
    }
    report_exception("UNEXPECTED", error);
    casper_revert(UNEXPECTED_ERROR);
}

static void check_bootstrap(void) {
    if (unwind_pending()) complete_exception(unwind_take_exception(), DISPATCH_BOOTSTRAP);
}

static void bind_sdk_outcomes(mp_obj_t sdk) {
    api_exception_type = mp_load_attr(sdk, MP_QSTR_ApiError);
    check_bootstrap();
    abi_error_type = mp_load_attr(sdk, MP_QSTR_ABIError);
    check_bootstrap();
    revert_exception_type = mp_load_attr(sdk, MP_QSTR_Revert);
    check_bootstrap();
    ret_exception_type = mp_load_attr(sdk, MP_QSTR_Ret);
    check_bootstrap();
}

static void bind_return_validator(mp_obj_t dispatcher) {
    validate_return_payload = mp_load_attr(dispatcher, MP_QSTR_validate_return_payload);
    check_bootstrap();
}

static void reset_outcomes(void) {
    api_exception_type = MP_OBJ_NULL;
    abi_error_type = MP_OBJ_NULL;
    revert_exception_type = MP_OBJ_NULL;
    ret_exception_type = MP_OBJ_NULL;
    validate_return_payload = MP_OBJ_NULL;
}
#endif
