# Restore the linear-memory C stack pointer after Asyncify rewinds.
    .functype cspr_setjmp_internal (i32) -> (i32)
    .globaltype __stack_pointer, i32
    .section .text.cspr_setjmp,"",@
    .globl cspr_setjmp
    .type cspr_setjmp,@function
cspr_setjmp:
    .functype cspr_setjmp (i32) -> (i32)
    .local i32
    global.get __stack_pointer
    local.set 1
    local.get 0
    call cspr_setjmp_internal
    local.get 1
    global.set __stack_pointer
    end_function
