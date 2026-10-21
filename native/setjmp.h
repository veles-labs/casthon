// Port-local terminal NLR shim; this is not a C continuation implementation.
#ifndef CSPR_TERMINAL_SETJMP_H
#define CSPR_TERMINAL_SETJMP_H
#include <stdint.h>
typedef uint32_t jmp_buf;
__attribute__((noreturn)) void cspr_terminal_jump(void *buffer);
#define setjmp(env) ((env) = 0)
#define longjmp(env, value) cspr_terminal_jump(&(env))
#endif
