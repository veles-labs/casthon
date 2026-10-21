// Wasm-only setjmp protocol, following Ruby's wasm/setjmp.c design.
// https://github.com/ruby/ruby/blob/master/wasm/setjmp.c
#include "setjmp.h"
#define CONTROL(name) __attribute__((import_module("asyncify"), import_name(#name)))
CONTROL(start_unwind) void start_unwind(void *data);
CONTROL(stop_unwind) void stop_unwind(void);
CONTROL(start_rewind) void start_rewind(void *data);
CONTROL(stop_rewind) void stop_rewind(void);
static jmp_buf *active;
static jmp_buf discarded;

__attribute__((noinline)) int cspr_setjmp_internal(jmp_buf *env) {
    if (env->state == 0) {
        env->state = 1;
        env->top = (uint32_t)env->bytes;
        env->end = (uint32_t)(env->bytes + sizeof env->bytes);
        active = env;
        start_unwind(env);
        return -1;
    }
    stop_rewind();
    int value = env->state == 3 ? env->value : 0;
    env->state = 2;
    active = 0;
    return value;
}

void cspr_longjmp(jmp_buf *env, int value) {
    env->state = 3;
    env->value = value ? value : 1;
    active = env;
    discarded.top = (uint32_t)discarded.bytes;
    discarded.end = (uint32_t)(discarded.bytes + sizeof discarded.bytes);
    start_unwind(&discarded);
}

__attribute__((noinline)) void cspr_run(void (*body)(void)) {
    for (;;) {
        body();
        if (!active) return;
        stop_unwind();
        if (active->state == 1) active->saved_top = active->top;
        else active->top = active->saved_top;
        start_rewind(active);
    }
}
