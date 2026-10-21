#include <stdint.h>

#if CSPR_SPLIT_HEAP
// Standalone Wasm has no JavaScript memory views to refresh after growth.
void emscripten_notify_memory_growth(int memory_index) {
    (void)memory_index;
}
#endif

// The chain has no process environment. Resolve these libc hooks locally;
// the final validator rejects any remaining WASI or non-Casper imports.
uint16_t __wasi_environ_sizes_get(uint32_t *count, uint32_t *size) {
    *count = 0;
    *size = 0;
    return 0;
}
uint16_t __wasi_environ_get(uint8_t **environment, uint8_t *buffer) {
    (void)environment; (void)buffer;
    return 0;
}
