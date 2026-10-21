#if MICROPY_NLR_ERROR_RETURNS
#include "py/nativeerror.h"
#else
#define MP_NATIVE_CALL(expression, failure) (expression)
#define MP_NATIVE_CALL_VOID(expression, failure) (expression)
#define MP_NATIVE_RAISE(expression, failure) (expression)
#endif
// ext_ffi coverage beyond the initial runtime/storage subset.
static int32_t account_bytes(mp_obj_t value, const uint8_t **data) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (int32_t){0};);
    if (b.len != 33 || ((uint8_t *)b.buf)[0] != 0) return ABI_ERROR;
    *data = (uint8_t *)b.buf + 1;
    return 0;
}
static mp_obj_t host_list_authorization_keys(void) {
    uint32_t count = 0, size = 0;
    CHECK(casper_load_authorization_keys(&count, &size));
    const uint8_t empty[4] = {0};
    return count ? MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(empty, 4), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_list_authorization_keys_obj, host_list_authorization_keys);

static mp_obj_t host_is_valid_uref(mp_obj_t value) {
    mp_buffer_info_t b; CHECK(MP_NATIVE_CALL(uref_bytes(value, &b), return (mp_obj_t){0};));
    return MP_NATIVE_CALL(host_ok(mp_obj_new_bool(casper_is_valid_uref((uint8_t *)b.buf + 1, 33) != 0)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_is_valid_uref_obj, host_is_valid_uref);

static mp_obj_t host_add_associated_key(mp_obj_t key, mp_obj_t weight) {
    const uint8_t *account_0; CHECK(MP_NATIVE_CALL(account_bytes(key, &account_0), return (mp_obj_t){0};));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(casper_add_associated_key(account_0, 32, MP_NATIVE_CALL(mp_obj_get_int(weight), return (mp_obj_t){0};))), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_add_associated_key_obj, host_add_associated_key);
static mp_obj_t host_update_associated_key(mp_obj_t key, mp_obj_t weight) {
    const uint8_t *account_0; CHECK(MP_NATIVE_CALL(account_bytes(key, &account_0), return (mp_obj_t){0};));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(casper_update_associated_key(account_0, 32, MP_NATIVE_CALL(mp_obj_get_int(weight), return (mp_obj_t){0};))), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_update_associated_key_obj, host_update_associated_key);
static mp_obj_t host_remove_associated_key(mp_obj_t key) {
    const uint8_t *account_0; CHECK(MP_NATIVE_CALL(account_bytes(key, &account_0), return (mp_obj_t){0};));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(casper_remove_associated_key(account_0, 32)), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_remove_associated_key_obj, host_remove_associated_key);
static mp_obj_t host_set_action_threshold(mp_obj_t action, mp_obj_t weight) {
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(casper_set_action_threshold(MP_NATIVE_CALL(mp_obj_get_int(action), return (mp_obj_t){0};), MP_NATIVE_CALL(mp_obj_get_int(weight), return (mp_obj_t){0};))), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_set_action_threshold_obj, host_set_action_threshold);

static mp_obj_t host_get_main_purse(void) {
    uint8_t key[34] = {2}; casper_get_main_purse(key + 1);
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(key, 34), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_get_main_purse_obj, host_get_main_purse);
static mp_obj_t host_create_purse(void) {
    uint8_t key[34] = {2}; CHECK(casper_create_purse(key + 1, 33));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(key, 34), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_create_purse_obj, host_create_purse);
static mp_obj_t host_get_purse_balance(mp_obj_t purse) {
    mp_buffer_info_t b; CHECK(MP_NATIVE_CALL(uref_bytes(purse, &b), return (mp_obj_t){0};)); uint32_t size;
    int32_t status = casper_get_balance((uint8_t *)b.buf + 1, 33, &size);
    CHECK(status); return MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_get_purse_balance_obj, host_get_purse_balance);
static mp_obj_t host_transfer_to_account(size_t n_args, const mp_obj_t *args) {
    const uint8_t *account_0; CHECK(MP_NATIVE_CALL(account_bytes(args[0], &account_0), return (mp_obj_t){0};));
    (void)n_args; mp_buffer_info_t amount, id; int32_t destination;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &amount, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &id, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_transfer_to_account(account_0, 32, amount.buf, amount.len, id.buf, id.len, &destination));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(destination), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_transfer_to_account_obj, 3, 3, host_transfer_to_account);
static mp_obj_t host_transfer_from_purse_to_account(size_t n_args, const mp_obj_t *args) {
    const uint8_t *account_0; CHECK(MP_NATIVE_CALL(account_bytes(args[1], &account_0), return (mp_obj_t){0};));
    (void)n_args; mp_buffer_info_t purse, amount, id; int32_t destination;
    CHECK(MP_NATIVE_CALL(uref_bytes(args[0], &purse), return (mp_obj_t){0};)); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &amount, MP_BUFFER_READ), return (mp_obj_t){0};);
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[3], &id, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_transfer_from_purse_to_account((uint8_t *)purse.buf + 1, 33, account_0, 32,
        amount.buf, amount.len, id.buf, id.len, &destination));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(destination), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_transfer_from_purse_to_account_obj, 4, 4, host_transfer_from_purse_to_account);
static mp_obj_t host_transfer_from_purse_to_purse(size_t n_args, const mp_obj_t *args) {
    (void)n_args; mp_buffer_info_t source, target, amount, id;
    CHECK(MP_NATIVE_CALL(uref_bytes(args[0], &source), return (mp_obj_t){0};)); CHECK(MP_NATIVE_CALL(uref_bytes(args[1], &target), return (mp_obj_t){0};));
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &amount, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[3], &id, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_transfer_from_purse_to_purse((uint8_t *)source.buf + 1, 33, (uint8_t *)target.buf + 1, 33,
        amount.buf, amount.len, id.buf, id.len)); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_transfer_from_purse_to_purse_obj, 4, 4, host_transfer_from_purse_to_purse);

static mp_obj_t host_get_blocktime(void) {
    uint8_t data[8]; casper_get_blocktime(data); return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, 8), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_get_blocktime_obj, host_get_blocktime);
static mp_obj_t host_get_phase(void) {
    uint8_t phase; casper_get_phase(&phase); return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_int(phase), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_get_phase_obj, host_get_phase);
static mp_obj_t host_get_block_info(mp_obj_t field) {
    int value = MP_NATIVE_CALL(mp_obj_get_int(field), return (mp_obj_t){0};); const uint8_t sizes[] = {8, 8, 32, 32, 12, 1}; uint8_t data[32];
    if (value < 0 || value > 5) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    casper_get_block_info(value, data); return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, sizes[value]), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_get_block_info_obj, host_get_block_info);
static mp_obj_t host_get_system_contract(mp_obj_t index) {
    uint8_t data[32]; CHECK(casper_get_system_contract(MP_NATIVE_CALL(mp_obj_get_int(index), return (mp_obj_t){0};), data, 32));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, 32), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_get_system_contract_obj, host_get_system_contract);
static mp_obj_t host_load_caller_information(mp_obj_t action) {
    uint32_t count = 0, size = 0; CHECK(casper_load_caller_information(MP_NATIVE_CALL(mp_obj_get_int(action), return (mp_obj_t){0};), &count, &size));
    const uint8_t empty[4] = {0}; return count ? MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(empty, 4), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_load_caller_information_obj, host_load_caller_information);
static mp_obj_t host_load_call_stack(void) {
    uint32_t count = 0, size = 0; CHECK(casper_load_call_stack(&count, &size));
    const uint8_t empty[4] = {0}; return count ? MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(empty, 4), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_load_call_stack_obj, host_load_call_stack);

static mp_obj_t host_dictionary_read(mp_obj_t key) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(key, &b, MP_BUFFER_READ), return (mp_obj_t){0};); uint32_t size;
    int32_t status = casper_dictionary_read(b.buf, b.len, &size);
    CHECK(status); return MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_dictionary_read_obj, host_dictionary_read);
static mp_obj_t host_create_contract_user_group(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args; size_t label_size; uint8_t *label = MP_NATIVE_CALL(name_bytes(args[1], &label_size), return (mp_obj_t){0};);
    mp_buffer_info_t urefs; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[3], &urefs, MP_BUFFER_READ), return (mp_obj_t){0};); uint32_t size;
    CHECK(casper_create_contract_user_group(hash_0, 32, label, label_size,
        MP_NATIVE_CALL(mp_obj_get_int(args[2]), return (mp_obj_t){0};), urefs.buf, urefs.len, &size)); return MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_create_contract_user_group_obj, 4, 4, host_create_contract_user_group);
static mp_obj_t host_remove_contract_user_group(mp_obj_t package, mp_obj_t label_obj) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(package, &hash_0), return (mp_obj_t){0};));
    size_t size; uint8_t *label = MP_NATIVE_CALL(name_bytes(label_obj, &size), return (mp_obj_t){0};);
    CHECK(casper_remove_contract_user_group(hash_0, 32, label, size)); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_remove_contract_user_group_obj, host_remove_contract_user_group);
static mp_obj_t host_provision_contract_user_group_uref(mp_obj_t package, mp_obj_t label_obj) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(package, &hash_0), return (mp_obj_t){0};));
    size_t size; uint8_t *label = MP_NATIVE_CALL(name_bytes(label_obj, &size), return (mp_obj_t){0};); uint32_t returned;
    CHECK(casper_provision_contract_user_group_uref(hash_0, 32, label, size, &returned));
    return MP_NATIVE_CALL(read_buffer(returned), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_provision_contract_user_group_uref_obj, host_provision_contract_user_group_uref);
static mp_obj_t host_remove_contract_user_group_urefs(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args; size_t size; uint8_t *label = MP_NATIVE_CALL(name_bytes(args[1], &size), return (mp_obj_t){0};);
    mp_buffer_info_t urefs; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &urefs, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_remove_contract_user_group_urefs(hash_0, 32, label, size, urefs.buf, urefs.len));
    return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_remove_contract_user_group_urefs_obj, 3, 3, host_remove_contract_user_group_urefs);

static mp_obj_t host_add_contract_version_legacy(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args; mp_buffer_info_t entries, keys;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &entries, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &keys, MP_BUFFER_READ), return (mp_obj_t){0};);
    uint8_t hash[33] = {1}; uint32_t version = 0, written = 0;
    CHECK(casper_add_contract_version(hash_0, 32, &version, entries.buf, entries.len,
        keys.buf, keys.len, hash + 1, 32, &written));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_tuple(2, (mp_obj_t[]){MP_NATIVE_CALL(mp_obj_new_bytes(hash, 33), return (mp_obj_t){0};), MP_NATIVE_CALL(mp_obj_new_int_from_uint(version), return (mp_obj_t){0};)}), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_add_contract_version_legacy_obj, 3, 3, host_add_contract_version_legacy);
static mp_obj_t host_add_package_version(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args; mp_buffer_info_t entries, keys, topics;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &entries, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &keys, MP_BUFFER_READ), return (mp_obj_t){0};);
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[3], &topics, MP_BUFFER_READ), return (mp_obj_t){0};); uint8_t hash[34] = {17, 2}, entity_enabled; uint32_t version;
    CHECK(casper_add_package_version_with_message_topics(hash_0, 32, &version,
        entries.buf, entries.len, keys.buf, keys.len, topics.buf, topics.len, hash + 2, 32));
    casper_get_block_info(5, &entity_enabled);
    // Both node configurations use this FFI; return the actual stored Key variant.
    if (!entity_enabled) hash[1] = 1;
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_tuple(2, (mp_obj_t[]){MP_NATIVE_CALL(mp_obj_new_bytes(hash + (entity_enabled ? 0 : 1),
        entity_enabled ? 34 : 33), return (mp_obj_t){0};), MP_NATIVE_CALL(mp_obj_new_int_from_uint(version), return (mp_obj_t){0};)}), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_add_package_version_obj, 4, 4, host_add_package_version);
static mp_obj_t host_enable_contract_version(mp_obj_t package, mp_obj_t contract) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(package, &hash_0), return (mp_obj_t){0};));
    const uint8_t *hash_1; CHECK(MP_NATIVE_CALL(hash_bytes(contract, &hash_1), return (mp_obj_t){0};));
    CHECK(casper_enable_contract_version(hash_0, 32, hash_1, 32)); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_enable_contract_version_obj, host_enable_contract_version);
static mp_obj_t host_call_versioned_contract(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args; mp_buffer_info_t version, arguments; size_t entry_size;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &version, MP_BUFFER_READ), return (mp_obj_t){0};); uint8_t *entry = MP_NATIVE_CALL(name_bytes(args[2], &entry_size), return (mp_obj_t){0};);
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[3], &arguments, MP_BUFFER_READ), return (mp_obj_t){0};); uint32_t returned;
    CHECK(casper_call_versioned_contract(hash_0, 32, version.buf, version.len, entry, entry_size,
        arguments.buf, arguments.len, &returned));
    return returned ? MP_NATIVE_CALL(read_buffer(returned), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(NULL, 0), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_call_versioned_contract_obj, 4, 4, host_call_versioned_contract);
static mp_obj_t host_call_package_version(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args; mp_buffer_info_t major, version, arguments; size_t entry_size;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &major, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &version, MP_BUFFER_READ), return (mp_obj_t){0};);
    uint8_t *entry = MP_NATIVE_CALL(name_bytes(args[3], &entry_size), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[4], &arguments, MP_BUFFER_READ), return (mp_obj_t){0};);
    uint32_t returned;
    CHECK(casper_call_package_version(hash_0, 32, major.buf, major.len, version.buf, version.len,
        entry, entry_size, arguments.buf, arguments.len, &returned));
    return returned ? MP_NATIVE_CALL(read_buffer(returned), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(NULL, 0), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_call_package_version_obj, 5, 5, host_call_package_version);

static mp_obj_t host_random_bytes(void) {
    uint8_t data[32]; CHECK(casper_random_bytes(data, 32)); return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, 32), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_random_bytes_obj, host_random_bytes);
static mp_obj_t host_generic_hash(mp_obj_t value, mp_obj_t algorithm) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (mp_obj_t){0};); uint8_t data[32];
    CHECK(casper_generic_hash(b.buf, b.len, MP_NATIVE_CALL(mp_obj_get_int(algorithm), return (mp_obj_t){0};), data, 32)); return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, 32), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_generic_hash_obj, host_generic_hash);
static mp_obj_t host_recover_secp256k1(size_t n_args, const mp_obj_t *args) {
    (void)n_args; mp_buffer_info_t message, signature;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[0], &message, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &signature, MP_BUFFER_READ), return (mp_obj_t){0};);
    uint8_t key[34]; CHECK(casper_recover_secp256k1(message.buf, message.len, signature.buf, signature.len,
        key, MP_NATIVE_CALL(mp_obj_get_int(args[2]), return (mp_obj_t){0};))); return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(key, 34), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_recover_secp256k1_obj, 3, 3, host_recover_secp256k1);
static mp_obj_t host_verify_signature(size_t n_args, const mp_obj_t *args) {
    (void)n_args; mp_buffer_info_t message, signature, key;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[0], &message, MP_BUFFER_READ), return (mp_obj_t){0};); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &signature, MP_BUFFER_READ), return (mp_obj_t){0};);
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &key, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_verify_signature(message.buf, message.len, signature.buf, signature.len, key.buf, key.len));
    return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_verify_signature_obj, 3, 3, host_verify_signature);
static mp_obj_t host_manage_message_topic(mp_obj_t topic, mp_obj_t operation) {
    size_t size; const char *name = MP_NATIVE_CALL(mp_obj_str_get_data(topic, &size), return (mp_obj_t){0};);
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(operation, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_manage_message_topic(name, size, b.buf, b.len)); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_manage_message_topic_obj, host_manage_message_topic);
