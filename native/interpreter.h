// Frozen interpreter lifecycle and MicroPython port hooks.
#ifndef CSPR_INTERPRETER_H
#define CSPR_INTERPRETER_H
#include "py/builtin.h"
#include "py/gc.h"
#include "py/pystack.h"
#include "py/cstack.h"
#include "casper.h"

extern void __wasm_call_ctors(void);
enum { INIT_ERROR = 65536 + 1 };
#if CSPR_SPLIT_HEAP || CSPR_MALLOC_GC_HEAP
#include <stdlib.h>
#include <emscripten/heap.h>

static size_t heap_available(void) {
    // Bound the unclaimed allocator tail, including future Wasm pages. The
    // standalone emscripten_get_heap_max() only reports the current size.
    // Leave room for emmalloc's region headers and alignment. This deliberately
    // ignores reusable malloc blocks: this port retains all GC regions until
    // the invocation's Wasm instance is discarded (tracing GC stays disabled).
    const size_t reserve = 256;
    uintptr_t end = *emscripten_get_sbrk_ptr();
    if (end >= CSPR_MAXIMUM_MEMORY - reserve) return 0;
    return CSPR_MAXIMUM_MEMORY - reserve - end;
}
#if CSPR_SPLIT_HEAP
size_t gc_get_max_new_split(void) {
    return heap_available();
}
#endif
#elif MICROPY_ENABLE_GC
static uint8_t heap[2 * 1024 * 1024] __attribute__((aligned(16)));
#endif
static mp_obj_t pystack[32768];

// Inline so MicroPython records the outer invocation's C stack origin.
__attribute__((always_inline)) static inline void interpreter_start(void) {
    __wasm_call_ctors();
    mp_cstack_init_with_sp_here(128 * 1024);
#if MICROPY_ENABLE_GC
#if CSPR_SPLIT_HEAP || CSPR_MALLOC_GC_HEAP
#if CSPR_MALLOC_GC_HEAP
    size_t heap_size = heap_available();
#else
    size_t heap_size = CSPR_INITIAL_HEAP_BYTES;
#endif
    uint8_t *heap = malloc(heap_size);
    if (heap == NULL) casper_revert(INIT_ERROR);
    gc_init(heap, heap + heap_size);
#else
    gc_init(heap, heap + sizeof heap);
#endif
    MP_STATE_MEM(gc_auto_collect_enabled) = 0;
#endif
    mp_pystack_init(pystack, pystack + sizeof pystack / sizeof pystack[0]);
    mp_init();
}

static inline void interpreter_stop(void) {
    mp_deinit();
}

// A missing NLR boundary is an interpreter fault, not a contract exception.
void nlr_jump_fail(void *value) {
    (void)value;
    casper_revert(INIT_ERROR);
}

// Collection is disabled: C locals cannot be scanned safely on this port.
#if MICROPY_ENABLE_GC
void gc_collect(void) {
    casper_revert(INIT_ERROR);
}
#endif

mp_import_stat_t mp_import_stat(const char *path) {
    (void)path;
    return MP_IMPORT_STAT_NO_EXIST;
}
#endif
