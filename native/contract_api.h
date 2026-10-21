#if MICROPY_NLR_ERROR_RETURNS
#include "py/nativeerror.h"
#else
#define MP_NATIVE_CALL(expression, failure) (expression)
#define MP_NATIVE_CALL_VOID(expression, failure) (expression)
#define MP_NATIVE_RAISE(expression, failure) (expression)
#endif
// Low-level wrappers. Domain-specific contract behavior belongs in Python.
static mp_obj_t host_get_key(mp_obj_t name) {
    size_t size; uint8_t *data = MP_NATIVE_CALL(name_bytes(name, &size), return (mp_obj_t){0};), key[128]; uint32_t written;
    int32_t status = casper_get_key(data, size, key, sizeof key, &written);
    CHECK(status);
    if (written > sizeof key) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(key, written), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_get_key_obj, host_get_key);

static mp_obj_t host_has_key(mp_obj_t name) {
    size_t size; uint8_t *data = MP_NATIVE_CALL(name_bytes(name, &size), return (mp_obj_t){0};);
    int32_t status = casper_has_key(data, size);
    if (status == 0) return MP_NATIVE_CALL(host_ok(mp_const_true), return (mp_obj_t){0};);
    if (status == 1) return MP_NATIVE_CALL(host_ok(mp_const_false), return (mp_obj_t){0};);
    CHECK(status); return MP_NATIVE_CALL(host_ok(mp_const_false), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_has_key_obj, host_has_key);

static mp_obj_t host_put_key(mp_obj_t name, mp_obj_t key) {
    size_t size; uint8_t *data = MP_NATIVE_CALL(name_bytes(name, &size), return (mp_obj_t){0};);
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(key, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    casper_put_key(data, size, b.buf, b.len); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_put_key_obj, host_put_key);

static mp_obj_t host_remove_key(mp_obj_t name) {
    size_t size; uint8_t *data = MP_NATIVE_CALL(name_bytes(name, &size), return (mp_obj_t){0};);
    casper_remove_key(data, size); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_remove_key_obj, host_remove_key);

static mp_obj_t host_list_named_keys(void) {
    uint32_t count, size; CHECK(casper_load_named_keys(&count, &size));
    const uint8_t empty[4] = {0};
    return count ? MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(empty, sizeof empty), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_list_named_keys_obj, host_list_named_keys);

static mp_obj_t host_get_named_arg(mp_obj_t object) {
    size_t length; const char *name = MP_NATIVE_CALL(mp_obj_str_get_data(object, &length), return (mp_obj_t){0};); uint32_t size;
    CHECK(casper_get_named_arg_size(name, length, &size));
    if (!size) return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(NULL, 0), return (mp_obj_t){0};)), return (mp_obj_t){0};);
    if (size > 1024 * 1024) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    uint8_t *data = MP_NATIVE_CALL(m_new(uint8_t, size), return (mp_obj_t){0};);
    CHECK(casper_get_named_arg(name, length, data, size));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, size), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_get_named_arg_obj, host_get_named_arg);

static mp_obj_t host_read_value(mp_obj_t key) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(key, &b, MP_BUFFER_READ), return (mp_obj_t){0};); uint32_t size;
    int32_t status = casper_read_value(b.buf, b.len, &size);
    CHECK(status); return MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_read_value_obj, host_read_value);
static mp_obj_t host_new_uref(mp_obj_t value) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    uint8_t key[34] = {2}; casper_new_uref(key + 1, b.buf, b.len);
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(key, sizeof key), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_new_uref_obj, host_new_uref);
static mp_obj_t host_write(mp_obj_t key, mp_obj_t value) {
    mp_buffer_info_t uref, b; CHECK(MP_NATIVE_CALL(uref_bytes(key, &uref), return (mp_obj_t){0};)); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    casper_write(uref.buf, uref.len, b.buf, b.len); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_write_obj, host_write);
static mp_obj_t host_add(mp_obj_t key, mp_obj_t value) {
    mp_buffer_info_t uref, b; CHECK(MP_NATIVE_CALL(uref_bytes(key, &uref), return (mp_obj_t){0};)); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    casper_add(uref.buf, uref.len, b.buf, b.len); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_add_obj, host_add);

static mp_obj_t host_new_dictionary(void) {
    uint32_t size, written; uint8_t key[34] = {2};
    CHECK(casper_new_dictionary(&size));
    if (size != 33) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    CHECK(casper_read_host_buffer(key + 1, 33, &written));
    if (written != 33) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    mp_obj_t seed = MP_NATIVE_CALL(mp_obj_new_bytes(key, sizeof key), return (mp_obj_t){0};);
    return MP_NATIVE_CALL(host_ok(seed), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_new_dictionary_obj, host_new_dictionary);
static mp_obj_t host_dictionary_get(mp_obj_t seed, mp_obj_t item) {
    mp_buffer_info_t key; CHECK(MP_NATIVE_CALL(uref_bytes(seed, &key), return (mp_obj_t){0};));
    size_t length; const char *text = MP_NATIVE_CALL(mp_obj_str_get_data(item, &length), return (mp_obj_t){0};); uint32_t size;
    int32_t status = casper_dictionary_get((uint8_t *)key.buf + 1, 33, text, length, &size);
    CHECK(status); return MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_dictionary_get_obj, host_dictionary_get);
static mp_obj_t host_dictionary_put(mp_obj_t seed, mp_obj_t item, mp_obj_t value) {
    mp_buffer_info_t key, b; CHECK(MP_NATIVE_CALL(uref_bytes(seed, &key), return (mp_obj_t){0};)); MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    size_t length; const char *text = MP_NATIVE_CALL(mp_obj_str_get_data(item, &length), return (mp_obj_t){0};);
    CHECK(casper_dictionary_put((uint8_t *)key.buf + 1, 33, text, length, b.buf, b.len));
    return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_3(host_dictionary_put_obj, host_dictionary_put);

static mp_obj_t host_get_caller(void) {
    uint32_t size; CHECK(casper_get_caller(&size));
    if (size != 32) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    return MP_NATIVE_CALL(read_buffer(size), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_get_caller_obj, host_get_caller);
static mp_obj_t host_get_protocol_version(void) {
    uint8_t version[12]; casper_get_block_info(4, version);
    mp_obj_t result[] = {MP_NATIVE_CALL(mp_obj_new_int_from_uint(get_u32(version)), return (mp_obj_t){0};),
        MP_NATIVE_CALL(mp_obj_new_int_from_uint(get_u32(version + 4)), return (mp_obj_t){0};), MP_NATIVE_CALL(mp_obj_new_int_from_uint(get_u32(version + 8)), return (mp_obj_t){0};)};
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_tuple(3, result), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_0(host_get_protocol_version_obj, host_get_protocol_version);
static mp_obj_t host_blake2b(mp_obj_t value) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (mp_obj_t){0};); uint8_t hash[32];
    CHECK(casper_blake2b(b.buf, b.len, hash, sizeof hash));
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(hash, sizeof hash), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_blake2b_obj, host_blake2b);
static int32_t hash_bytes(mp_obj_t value, const uint8_t **data) {
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, &b, MP_BUFFER_READ), return (int32_t){0};); const uint8_t *key = b.buf;
    if (b.len == 33 && (key[0] == 1 || key[0] == 16)) { *data = key + 1; return 0; }
    if (b.len == 34 && key[0] == 17 && key[1] == 2) { *data = key + 2; return 0; }
    return ABI_ERROR;
}
static mp_obj_t host_create_contract_package_at_hash(mp_obj_t locked) {
    uint8_t key[33] = {1}, access[34] = {2};
    casper_create_contract_package_at_hash(key + 1, access + 1, MP_NATIVE_CALL(mp_obj_is_true(locked), return (mp_obj_t){0};)); access[33] = 7;
    mp_obj_t result[] = {MP_NATIVE_CALL(mp_obj_new_bytes(key, sizeof key), return (mp_obj_t){0};), MP_NATIVE_CALL(mp_obj_new_bytes(access, sizeof access), return (mp_obj_t){0};)};
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_tuple(2, result), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_1(host_create_contract_package_at_hash_obj, host_create_contract_package_at_hash);
static mp_obj_t host_add_contract_version(size_t n_args, const mp_obj_t *args) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(args[0], &hash_0), return (mp_obj_t){0};));
    (void)n_args;
    mp_buffer_info_t entries, keys, topics;
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[1], &entries, MP_BUFFER_READ), return (mp_obj_t){0};);
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[2], &keys, MP_BUFFER_READ), return (mp_obj_t){0};);
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(args[3], &topics, MP_BUFFER_READ), return (mp_obj_t){0};);
    uint8_t hash[33] = {1}; uint32_t version;
    CHECK(casper_add_contract_version_with_message_topics(hash_0, 32, &version,
        entries.buf, entries.len, keys.buf, keys.len, topics.buf, topics.len, hash + 1, 32));
    mp_obj_t result[] = {MP_NATIVE_CALL(mp_obj_new_bytes(hash, sizeof hash), return (mp_obj_t){0};), MP_NATIVE_CALL(mp_obj_new_int_from_uint(version), return (mp_obj_t){0};)};
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_tuple(2, result), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(host_add_contract_version_obj, 4, 4, host_add_contract_version);
static mp_obj_t host_disable_contract_version(mp_obj_t package, mp_obj_t contract) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(package, &hash_0), return (mp_obj_t){0};));
    const uint8_t *hash_1; CHECK(MP_NATIVE_CALL(hash_bytes(contract, &hash_1), return (mp_obj_t){0};));
    CHECK(casper_disable_contract_version(hash_0, 32, hash_1, 32));
    return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_disable_contract_version_obj, host_disable_contract_version);
static mp_obj_t host_call_contract(mp_obj_t contract, mp_obj_t entry, mp_obj_t arguments) {
    const uint8_t *hash_0; CHECK(MP_NATIVE_CALL(hash_bytes(contract, &hash_0), return (mp_obj_t){0};));
    size_t size; uint8_t *name = MP_NATIVE_CALL(name_bytes(entry, &size), return (mp_obj_t){0};); uint32_t returned;
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(arguments, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_call_contract(hash_0, 32, name, size, b.buf, b.len, &returned));
    return returned ? MP_NATIVE_CALL(read_buffer(returned), return (mp_obj_t){0};) : MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(NULL, 0), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_3(host_call_contract_obj, host_call_contract);
static mp_obj_t host_emit_message(mp_obj_t topic, mp_obj_t payload) {
    size_t length; const char *name = MP_NATIVE_CALL(mp_obj_str_get_data(topic, &length), return (mp_obj_t){0};);
    mp_buffer_info_t b; MP_NATIVE_CALL_VOID(mp_get_buffer_raise(payload, &b, MP_BUFFER_READ), return (mp_obj_t){0};);
    CHECK(casper_emit_message(name, length, b.buf, b.len)); return MP_NATIVE_CALL(host_ok(mp_const_none), return (mp_obj_t){0};);
}
static MP_DEFINE_CONST_FUN_OBJ_2(host_emit_message_obj, host_emit_message);
