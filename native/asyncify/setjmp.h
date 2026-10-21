// Casper-local C continuations. Upstream MicroPython remains unchanged.
#ifndef CSPR_ASYNCIFY_SETJMP_H
#define CSPR_ASYNCIFY_SETJMP_H
#include <stdint.h>
#ifndef CSPR_JUMP_BYTES
#define CSPR_JUMP_BYTES 4096
#endif
typedef struct {
    uint32_t top, end;
    uint8_t bytes[CSPR_JUMP_BYTES];
    uint32_t saved_top;
    int state, value;
} jmp_buf;
__attribute__((noinline)) int cspr_setjmp(jmp_buf *env);
__attribute__((noinline)) void cspr_longjmp(jmp_buf *env, int value);
#define setjmp(env) ((env).state = 0, cspr_setjmp(&(env)))
#define longjmp(env, value) (cspr_longjmp(&(env), (value)), __builtin_unreachable())
void cspr_run(void (*body)(void));
#endif
