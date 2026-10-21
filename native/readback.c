#include <stdint.h>
#include "casper.h"

HOST(casper_call_contract) int32_t casper_call_contract(const void *, size_t,
    const void *, size_t, const void *, size_t, uint32_t *);

// A conventional Wasm caller verifies the Python get entrypoint's typed return ABI.
void call(void) {
    uint8_t hash[32], expected[4], actual[4];
    uint32_t size = 0, written = 0;
    if (casper_get_named_arg("contract_hash", 13, hash, 32) ||
        casper_get_named_arg("expected", 8, expected, 4)) casper_revert(65540);
    const uint8_t entry[] = {3, 0, 0, 0, 'g', 'e', 't'};
    const uint8_t args[4] = {0};
    int32_t status = casper_call_contract(hash, 32, entry, sizeof entry, args, sizeof args, &size);
    if (status) casper_revert(status);
    if (size != 4 || casper_read_host_buffer(actual, 4, &written) || written != 4) casper_revert(65541);
    for (unsigned i = 0; i < 4; i++) if (actual[i] != expected[i]) casper_revert(65542);
}
