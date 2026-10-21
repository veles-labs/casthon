#include <stdlib.h>
#include <string.h>
#include "py/runtime.h"
#include "unwind.h"
#include "interpreter.h"
#include "casper.h"

enum { ABI_ERROR = 3 };

static void put_u32(uint8_t *p, uint32_t n) {
    p[0] = n; p[1] = n >> 8; p[2] = n >> 16; p[3] = n >> 24;
}
static uint32_t get_u32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
// Every binding returns (ApiError status, value). No exception policy lives here.
static mp_obj_t host_result(int32_t status, mp_obj_t value) {
    return MP_NATIVE_CALL(mp_obj_new_tuple(2, (mp_obj_t[]){MP_NATIVE_CALL(mp_obj_new_int(status), return (mp_obj_t){0};), value}), return (mp_obj_t){0};);
}
static mp_obj_t host_ok(mp_obj_t value) { return MP_NATIVE_CALL(host_result(0, value), return (mp_obj_t){0};); }
#define CHECK(expression) do { int32_t status_ = (expression); \
    if (mp_native_error_pending()) return MP_OBJ_NULL; \
    if (status_) return host_result(status_, mp_const_none); } while (0)
static uint8_t *name_bytes(mp_obj_t object, size_t *size) {
    size_t length; const char *name = MP_NATIVE_CALL(mp_obj_str_get_data(object, &length), return (uint8_t *){0};);
    uint8_t *data = MP_NATIVE_CALL(m_new(uint8_t, length + 4), return (uint8_t *){0};);
    put_u32(data, length); memcpy(data + 4, name, length); *size = length + 4;
    return data;
}
static mp_obj_t read_buffer(uint32_t size) {
    if (size > 1024 * 1024) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    uint8_t *data = MP_NATIVE_CALL(m_new(uint8_t, size ? size : 1), return (mp_obj_t){0};); uint32_t written;
    CHECK(casper_read_host_buffer(data, size, &written));
    if (written != size) return MP_NATIVE_CALL(host_result(ABI_ERROR, mp_const_none), return (mp_obj_t){0};);
    return MP_NATIVE_CALL(host_ok(MP_NATIVE_CALL(mp_obj_new_bytes(data, size), return (mp_obj_t){0};)), return (mp_obj_t){0};);
}
static int32_t uref_bytes(mp_obj_t value, mp_buffer_info_t *buffer) {
    MP_NATIVE_CALL_VOID(mp_get_buffer_raise(value, buffer, MP_BUFFER_READ), return (int32_t){0};);
    if (buffer->len != 34 || ((uint8_t *)buffer->buf)[0] != 2) return ABI_ERROR;
    return 0;
}

#include "contract_api.h"
#include "extended_api.h"

static const mp_rom_map_elem_t host_globals[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR__casper)},
    {MP_ROM_QSTR(MP_QSTR_get_named_arg), MP_ROM_PTR(&host_get_named_arg_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_key), MP_ROM_PTR(&host_get_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_has_key), MP_ROM_PTR(&host_has_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_put_key), MP_ROM_PTR(&host_put_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove_key), MP_ROM_PTR(&host_remove_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_list_named_keys), MP_ROM_PTR(&host_list_named_keys_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_caller), MP_ROM_PTR(&host_get_caller_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_protocol_version), MP_ROM_PTR(&host_get_protocol_version_obj)},
    {MP_ROM_QSTR(MP_QSTR_blake2b), MP_ROM_PTR(&host_blake2b_obj)},
    {MP_ROM_QSTR(MP_QSTR_call_contract), MP_ROM_PTR(&host_call_contract_obj)},
    {MP_ROM_QSTR(MP_QSTR_emit_message), MP_ROM_PTR(&host_emit_message_obj)},
    {MP_ROM_QSTR(MP_QSTR_read_value), MP_ROM_PTR(&host_read_value_obj)},
    {MP_ROM_QSTR(MP_QSTR_new_uref), MP_ROM_PTR(&host_new_uref_obj)},
    {MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&host_write_obj)},
    {MP_ROM_QSTR(MP_QSTR_add), MP_ROM_PTR(&host_add_obj)},
    {MP_ROM_QSTR(MP_QSTR_new_dictionary), MP_ROM_PTR(&host_new_dictionary_obj)},
    {MP_ROM_QSTR(MP_QSTR_dictionary_get), MP_ROM_PTR(&host_dictionary_get_obj)},
    {MP_ROM_QSTR(MP_QSTR_dictionary_put), MP_ROM_PTR(&host_dictionary_put_obj)},
    {MP_ROM_QSTR(MP_QSTR_create_contract_package_at_hash), MP_ROM_PTR(&host_create_contract_package_at_hash_obj)},
    {MP_ROM_QSTR(MP_QSTR_add_contract_version), MP_ROM_PTR(&host_add_contract_version_obj)},
    {MP_ROM_QSTR(MP_QSTR_disable_contract_version), MP_ROM_PTR(&host_disable_contract_version_obj)},
    {MP_ROM_QSTR(MP_QSTR_list_authorization_keys), MP_ROM_PTR(&host_list_authorization_keys_obj)},
    {MP_ROM_QSTR(MP_QSTR_is_valid_uref), MP_ROM_PTR(&host_is_valid_uref_obj)},
    {MP_ROM_QSTR(MP_QSTR_add_associated_key), MP_ROM_PTR(&host_add_associated_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove_associated_key), MP_ROM_PTR(&host_remove_associated_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_update_associated_key), MP_ROM_PTR(&host_update_associated_key_obj)},
    {MP_ROM_QSTR(MP_QSTR_set_action_threshold), MP_ROM_PTR(&host_set_action_threshold_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_main_purse), MP_ROM_PTR(&host_get_main_purse_obj)},
    {MP_ROM_QSTR(MP_QSTR_create_purse), MP_ROM_PTR(&host_create_purse_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_purse_balance), MP_ROM_PTR(&host_get_purse_balance_obj)},
    {MP_ROM_QSTR(MP_QSTR_transfer_to_account), MP_ROM_PTR(&host_transfer_to_account_obj)},
    {MP_ROM_QSTR(MP_QSTR_transfer_from_purse_to_account), MP_ROM_PTR(&host_transfer_from_purse_to_account_obj)},
    {MP_ROM_QSTR(MP_QSTR_transfer_from_purse_to_purse), MP_ROM_PTR(&host_transfer_from_purse_to_purse_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_blocktime), MP_ROM_PTR(&host_get_blocktime_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_phase), MP_ROM_PTR(&host_get_phase_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_block_info), MP_ROM_PTR(&host_get_block_info_obj)},
    {MP_ROM_QSTR(MP_QSTR_get_system_contract), MP_ROM_PTR(&host_get_system_contract_obj)},
    {MP_ROM_QSTR(MP_QSTR_load_caller_information), MP_ROM_PTR(&host_load_caller_information_obj)},
    {MP_ROM_QSTR(MP_QSTR_load_call_stack), MP_ROM_PTR(&host_load_call_stack_obj)},
    {MP_ROM_QSTR(MP_QSTR_dictionary_read), MP_ROM_PTR(&host_dictionary_read_obj)},
    {MP_ROM_QSTR(MP_QSTR_create_contract_user_group), MP_ROM_PTR(&host_create_contract_user_group_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove_contract_user_group), MP_ROM_PTR(&host_remove_contract_user_group_obj)},
    {MP_ROM_QSTR(MP_QSTR_provision_contract_user_group_uref), MP_ROM_PTR(&host_provision_contract_user_group_uref_obj)},
    {MP_ROM_QSTR(MP_QSTR_remove_contract_user_group_urefs), MP_ROM_PTR(&host_remove_contract_user_group_urefs_obj)},
    {MP_ROM_QSTR(MP_QSTR_add_contract_version_legacy), MP_ROM_PTR(&host_add_contract_version_legacy_obj)},
    {MP_ROM_QSTR(MP_QSTR_add_package_version), MP_ROM_PTR(&host_add_package_version_obj)},
    {MP_ROM_QSTR(MP_QSTR_enable_contract_version), MP_ROM_PTR(&host_enable_contract_version_obj)},
    {MP_ROM_QSTR(MP_QSTR_call_versioned_contract), MP_ROM_PTR(&host_call_versioned_contract_obj)},
    {MP_ROM_QSTR(MP_QSTR_call_package_version), MP_ROM_PTR(&host_call_package_version_obj)},
    {MP_ROM_QSTR(MP_QSTR_random_bytes), MP_ROM_PTR(&host_random_bytes_obj)},
    {MP_ROM_QSTR(MP_QSTR_generic_hash), MP_ROM_PTR(&host_generic_hash_obj)},
    {MP_ROM_QSTR(MP_QSTR_recover_secp256k1), MP_ROM_PTR(&host_recover_secp256k1_obj)},
    {MP_ROM_QSTR(MP_QSTR_verify_signature), MP_ROM_PTR(&host_verify_signature_obj)},
    {MP_ROM_QSTR(MP_QSTR_manage_message_topic), MP_ROM_PTR(&host_manage_message_topic_obj)},
};
static MP_DEFINE_CONST_DICT(host_globals_dict, host_globals);
const mp_obj_module_t casper_module = {.base = {&mp_type_module}, .globals = (mp_obj_dict_t *)&host_globals_dict};
MP_REGISTER_MODULE(MP_QSTR__casper, casper_module);

mp_uint_t mp_hal_stdout_tx_strn(const char *text, size_t length) {
#if CSPR_DEBUG
    uint8_t *data = MP_NATIVE_CALL(m_new(uint8_t, length + 4), return (mp_uint_t){0};); put_u32(data, length);
    memcpy(data + 4, text, length); casper_print(data, length + 4);
    m_del(uint8_t, data, length + 4);
#else
    (void)text;
#endif
    return length;
}

void mp_hal_stdout_tx_strn_cooked(const char *text, size_t length) {
    MP_NATIVE_CALL(mp_hal_stdout_tx_strn(text, length), return;);
}

// Keep the host adapter reusable by the isolated dispatcher experiments.
void cspr_dispatch(const char *entry);
#include "dispatcher.h"
