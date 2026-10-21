#ifndef CSPR_HOST_H
#define CSPR_HOST_H
#include <stdint.h>
#include <stddef.h>
#ifndef CSPR_DEBUG
#define CSPR_DEBUG (1)
#endif
#define HOST(name) __attribute__((import_module("env"), import_name(#name)))
HOST(casper_get_key) int32_t casper_get_key(const void *, size_t, void *, size_t, uint32_t *);
HOST(casper_put_key) void casper_put_key(const void *, size_t, const void *, size_t);
HOST(casper_has_key) int32_t casper_has_key(const void *, size_t);
HOST(casper_remove_key) void casper_remove_key(const void *, size_t);
HOST(casper_load_named_keys) int32_t casper_load_named_keys(uint32_t *, uint32_t *);
HOST(casper_new_uref) void casper_new_uref(void *, const void *, size_t);
HOST(casper_get_caller) int32_t casper_get_caller(uint32_t *);
HOST(casper_add) void casper_add(const void *, size_t, const void *, size_t);
HOST(casper_read_value) int32_t casper_read_value(const void *, size_t, uint32_t *);
HOST(casper_read_host_buffer) int32_t casper_read_host_buffer(void *, size_t, uint32_t *);
HOST(casper_write) void casper_write(const void *, size_t, const void *, size_t);
HOST(casper_get_named_arg_size) int32_t casper_get_named_arg_size(const void *, size_t, uint32_t *);
HOST(casper_get_named_arg) int32_t casper_get_named_arg(const void *, size_t, void *, size_t);
HOST(casper_create_contract_package_at_hash) void casper_create_contract_package_at_hash(void *, void *, int32_t);
HOST(casper_add_contract_version_with_message_topics) int32_t casper_add_contract_version_with_message_topics(
    const void *, size_t, uint32_t *, const void *, size_t, const void *, size_t,
    const void *, size_t, void *, size_t);
HOST(casper_ret) _Noreturn void casper_ret(const void *, size_t);
HOST(casper_revert) _Noreturn void casper_revert(uint32_t);
#if CSPR_DEBUG
HOST(casper_print) void casper_print(const void *, size_t);
#endif
HOST(casper_new_dictionary) int32_t casper_new_dictionary(uint32_t *);
HOST(casper_dictionary_get) int32_t casper_dictionary_get(const void *, size_t, const void *, size_t, uint32_t *);
HOST(casper_dictionary_put) int32_t casper_dictionary_put(const void *, size_t, const void *, size_t, const void *, size_t);
HOST(casper_blake2b) int32_t casper_blake2b(const void *, size_t, void *, size_t);
HOST(casper_load_caller_information) int32_t casper_load_caller_information(uint32_t, uint32_t *, uint32_t *);
HOST(casper_get_block_info) void casper_get_block_info(uint32_t, void *);
HOST(casper_call_contract) int32_t casper_call_contract(const void *, size_t, const void *, size_t, const void *, size_t, uint32_t *);
HOST(casper_disable_contract_version) int32_t casper_disable_contract_version(const void *, size_t, const void *, size_t);
HOST(casper_emit_message) int32_t casper_emit_message(const void *, size_t, const void *, size_t);
HOST(casper_load_authorization_keys) int32_t casper_load_authorization_keys(uint32_t *, uint32_t *);
HOST(casper_is_valid_uref) int32_t casper_is_valid_uref(const void *, size_t);
HOST(casper_add_associated_key) int32_t casper_add_associated_key(const void *, size_t, int32_t);
HOST(casper_remove_associated_key) int32_t casper_remove_associated_key(const void *, size_t);
HOST(casper_update_associated_key) int32_t casper_update_associated_key(const void *, size_t, int32_t);
HOST(casper_set_action_threshold) int32_t casper_set_action_threshold(uint32_t, uint32_t);
HOST(casper_get_blocktime) void casper_get_blocktime(void *);
HOST(casper_get_phase) void casper_get_phase(void *);
HOST(casper_get_system_contract) int32_t casper_get_system_contract(uint32_t, void *, size_t);
HOST(casper_get_main_purse) void casper_get_main_purse(void *);
HOST(casper_create_purse) int32_t casper_create_purse(void *, size_t);
HOST(casper_get_balance) int32_t casper_get_balance(const void *, size_t, uint32_t *);
HOST(casper_transfer_to_account) int32_t casper_transfer_to_account(const void *, size_t,
    const void *, size_t, const void *, size_t, int32_t *);
HOST(casper_transfer_from_purse_to_account) int32_t casper_transfer_from_purse_to_account(
    const void *, size_t, const void *, size_t, const void *, size_t, const void *, size_t, int32_t *);
HOST(casper_transfer_from_purse_to_purse) int32_t casper_transfer_from_purse_to_purse(
    const void *, size_t, const void *, size_t, const void *, size_t, const void *, size_t);
HOST(casper_create_contract_user_group) int32_t casper_create_contract_user_group(
    const void *, size_t, const void *, size_t, uint32_t, const void *, size_t, uint32_t *);
HOST(casper_remove_contract_user_group) int32_t casper_remove_contract_user_group(
    const void *, size_t, const void *, size_t);
HOST(casper_provision_contract_user_group_uref) int32_t casper_provision_contract_user_group_uref(
    const void *, size_t, const void *, size_t, uint32_t *);
HOST(casper_remove_contract_user_group_urefs) int32_t casper_remove_contract_user_group_urefs(
    const void *, size_t, const void *, size_t, const void *, size_t);
HOST(casper_add_contract_version) int32_t casper_add_contract_version(const void *, size_t,
    uint32_t *, const void *, size_t, const void *, size_t, void *, size_t, uint32_t *);
HOST(casper_add_package_version_with_message_topics) int32_t casper_add_package_version_with_message_topics(
    const void *, size_t, uint32_t *, const void *, size_t, const void *, size_t,
    const void *, size_t, void *, size_t);
HOST(casper_enable_contract_version) int32_t casper_enable_contract_version(const void *, size_t, const void *, size_t);
HOST(casper_call_versioned_contract) int32_t casper_call_versioned_contract(const void *, size_t,
    const void *, size_t, const void *, size_t, const void *, size_t, uint32_t *);
HOST(casper_call_package_version) int32_t casper_call_package_version(const void *, size_t,
    const void *, size_t, const void *, size_t, const void *, size_t, const void *, size_t, uint32_t *);
HOST(casper_load_call_stack) int32_t casper_load_call_stack(uint32_t *, uint32_t *);
HOST(casper_dictionary_read) int32_t casper_dictionary_read(const void *, size_t, uint32_t *);
HOST(casper_random_bytes) int32_t casper_random_bytes(void *, size_t);
HOST(casper_manage_message_topic) int32_t casper_manage_message_topic(const void *, size_t, const void *, size_t);
HOST(casper_generic_hash) int32_t casper_generic_hash(const void *, size_t, uint32_t, void *, size_t);
HOST(casper_recover_secp256k1) int32_t casper_recover_secp256k1(const void *, size_t,
    const void *, size_t, void *, uint32_t);
HOST(casper_verify_signature) int32_t casper_verify_signature(const void *, size_t,
    const void *, size_t, const void *, size_t);
#endif
