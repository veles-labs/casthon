"""Execute real Wasm against independent Casper host fixtures using Wasmtime.

This is deliberately separate from cspr.testing.MockHost: the wire fixtures and
FFI implementation must catch mistakes in the SDK and its native adapter.
"""

from functools import lru_cache
from hashlib import blake2b
import os
from pathlib import Path

import wasmtime

from codec import envelope, key_length, payload, text, u32, unwrap

ROOT = Path(__file__).resolve().parents[2]
CONFIG = wasmtime.Config()
# Wasm backtraces remain available. Skip platform-profiler frame registration,
# whose teardown is quadratic on macOS when loading many large probe modules.
# https://docs.wasmtime.dev/api/wasmtime/struct.Config.html#method.native_unwind_info
CONFIG.native_unwind_info = False
ENGINE = wasmtime.Engine(CONFIG)


def build_file(name):
    return ROOT / os.environ.get("CSPR_BUILD_DIR", "build") / name


@lru_cache(maxsize=32)
def _compile(data):
    return wasmtime.Module(ENGINE, data)


def load_module(path):
    return _compile(Path(path).read_bytes())


@lru_cache(maxsize=2)
def _gas_module(parameter):
    # Keep per-instruction gas accounting inside Wasm instead of crossing into
    # Python for every basic block. This preserves the instrumenter's exact sum.
    extend = "i64.extend_i32_u" if parameter == "i32" else ""
    return wasmtime.Module(ENGINE, f'''(module
      (global (export "total") (mut i64) (i64.const 0))
      (func (export "gas") (param {parameter})
        global.get 0 local.get 0 {extend} i64.add global.set 0))''')


class Revert(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Revert {code}")


class _Return(BaseException):
    def __init__(self, data):
        self.data = data


class Harness:
    def __init__(self, path=None):
        self.module = load_module(path or build_file("counter.metered.wasm"))
        self.account = {}
        self.contract = {}
        self.cells = {}
        self.dictionaries = {}
        self.next = 1
        self.gas = 0
        self.prints = []
        self.messages = []
        self.message_topics = set()
        self.caller_information = None
        self.caller = bytes([0x11]) * 32
        self.entry_points = None
        self.contract_module = None
        self._active = None

    def write_u32(self, pointer, value):
        """Available to host overrides, including host-buffer corruption probes."""
        self._active.write(pointer, u32(value))

    def invoke(self, entry, args=None, overrides=None):
        before = (self.account.copy(), self.contract.copy(), self.cells.copy(),
                  {seed: items.copy() for seed, items in self.dictionaries.items()},
                  self.next, self.entry_points, self.messages.copy(), self.message_topics.copy(), self.contract_module)
        active = self._active
        try:
            with wasmtime.Store(ENGINE) as store:
                call = _Invocation(self, store, entry, args or {}, overrides or {})
                self._active = call
                call.run(entry)
        except _Return as result:
            return result.data
        except BaseException as error:
            (self.account, self.contract, self.cells, self.dictionaries,
             self.next, self.entry_points, self.messages, self.message_topics, self.contract_module) = before
            if isinstance(error, Revert):
                error.args = (str(error) + "\n" + "".join(self.prints),)
            raise
        finally:
            self._active = active

    def stored(self, name):
        return self.cells.get(self.contract[name][1:33].hex())


class _Invocation:
    def __init__(self, host, store, entry, args, overrides):
        self.host, self.store, self.args, self.overrides = host, store, args, overrides
        self.context = host.account if entry in ("call", "call_counter", "read_count") else host.contract
        self.host_buffer = None
        self.gas_instance = None
        imports = []
        for item in host.module.imports:
            assert item.module == "env" and isinstance(item.type, wasmtime.FuncType)
            if item.name == "gas" and "gas" not in overrides:
                self.gas_instance = wasmtime.Instance(store, _gas_module(str(item.type.params[0])), [])
                imports.append(self.gas_instance.exports(store)["gas"])
                continue
            function = overrides.get(item.name, getattr(self, item.name, None))
            if function is None:
                def function(*args, name=item.name):
                    raise AssertionError("Unexpected host operation: " + name)
            # Host functions returning void may mutate a dict and return a value.
            def callback(*args, function=function, returns=bool(item.type.results)):
                result = function(*args)
                return result if returns else None
            imports.append(wasmtime.Func(store, item.type, callback))
        self.instance = wasmtime.Instance(store, host.module, imports)
        self.memory = self.instance.exports(store).get("memory")

    def run(self, entry):
        try:
            self.instance.exports(self.store)[entry](self.store)
        finally:
            if self.gas_instance is not None:
                self.host.gas += self.gas_instance.exports(self.store)["total"].value(self.store)

    def read(self, pointer, size):
        assert pointer >= 0 and size >= 0 and pointer + size <= self.memory.data_len(self.store)
        return bytes(self.memory.read(self.store, pointer, pointer + size))

    def write(self, pointer, data):
        self.memory.write(self.store, data, pointer)

    def set(self, pointer, value):
        self.write(pointer, u32(value))

    def name(self, pointer, size):
        data = self.read(pointer, size)
        assert int.from_bytes(data[:4], "little") == size - 4
        return data[4:].decode()

    def gas(self, amount):
        self.host.gas += amount

    def casper_revert(self, code):
        raise Revert(code)

    def casper_ret(self, pointer, size):
        raise _Return(self.read(pointer, size))

    def casper_print(self, pointer, size):
        self.host.prints.append(self.name(pointer, size))

    def casper_has_key(self, pointer, size):
        return 0 if self.name(pointer, size) in self.context else 1

    def casper_remove_key(self, pointer, size):
        self.context.pop(self.name(pointer, size), None)

    def casper_load_named_keys(self, count, size):
        self.host_buffer = u32(len(self.context)) + b"".join(
            text(name) + key for name, key in sorted(self.context.items()))
        self.set(count, len(self.context))
        self.set(size, len(self.host_buffer) if self.context else 0)
        return 0

    def casper_get_caller(self, out):
        self.host_buffer = self.host.caller
        self.set(out, 32)
        return 0

    def casper_load_caller_information(self, action, count, size):
        assert action in (0, 1, 2)
        if action == 1 and self.context is self.host.account:
            return 31
        data = self.host.caller_information
        if data is None or action == 0:
            data = u32(1) + b"\0" + u32(5)
            for index in range(5):
                value = b"\1" + self.host.caller if index == 0 else b"\0"
                kind = b"\x0d\x15" if index == 3 else b"\x0d\x0f\x20\0\0\0"
                data += bytes([index]) + u32(len(value)) + value + kind
        self.host_buffer = data
        self.set(count, int.from_bytes(data[:4], "little"))
        self.set(size, len(data))
        return 0

    def casper_emit_message(self, topic, topic_size, message, message_size):
        name = self.read(topic, topic_size).decode()
        if name not in self.host.message_topics:
            return 3
        self.host.messages.append((name, self.read(message, message_size)))
        return 0

    def casper_get_block_info(self, field, out):
        assert field == 4
        self.write(out, u32(2) + u32(2) + u32(0))

    def casper_blake2b(self, pointer, size, out, capacity):
        assert capacity == 32
        self.write(out, blake2b(self.read(pointer, size), digest_size=32).digest())
        return 0

    def casper_put_key(self, pointer, size, key, key_size):
        self.context[self.name(pointer, size)] = self.read(key, key_size)

    def casper_get_key(self, pointer, size, out, capacity, written):
        key = self.context.get(self.name(pointer, size))
        if key is None:
            return 24
        assert capacity >= len(key)
        self.write(out, key)
        self.set(written, len(key))
        return 0

    def allocate(self):
        address = u32(self.host.next) + bytes(28)
        self.host.next += 1
        return address

    def casper_new_uref(self, out, value, size):
        address = self.allocate()
        self.write(out, address + b"\x07")
        self.host.cells[address.hex()] = self.read(value, size)

    def casper_read_value(self, key, size, out):
        data = self.read(key, size)
        if size == 33 and data[0] == 1:
            assert data[1:] == b"\xff" * 32
            return 6
        assert size == 34 and data[0] == 2
        value = self.host.cells.get(data[1:33].hex())
        if value is None:
            return 6
        self.host_buffer = unwrap(value)
        self.set(out, len(self.host_buffer))
        return 0

    def casper_read_host_buffer(self, out, capacity, written):
        assert capacity == len(self.host_buffer)
        self.write(out, self.host_buffer)
        self.set(written, capacity)
        self.host_buffer = None
        return 0

    def casper_write(self, key, size, value, length):
        data = self.read(key, size)
        assert size == 34 and data[0] == 2
        self.host.cells[data[1:33].hex()] = self.read(value, length)

    def casper_add(self, key, size, value, length):
        address = self.read(key + 1, 32).hex()
        incoming, old = self.read(value, length), self.host.cells[address]
        assert incoming[-1] == old[-1] == 7, "Host add only supports U256"
        total = int.from_bytes(unwrap(old)[1:], "little") + int.from_bytes(unwrap(incoming)[1:], "little")
        self.host.cells[address] = envelope("U256", total)

    def casper_new_dictionary(self, out):
        address = self.allocate()
        self.host_buffer = address + b"\x07"
        self.host.dictionaries[address.hex()] = {}
        self.set(out, 33)
        return 0

    def casper_dictionary_get(self, seed, seed_size, item, item_size, out):
        assert seed_size == 33
        value = self.host.dictionaries[self.read(seed, 32).hex()].get(self.read(item, item_size).decode())
        if value is None:
            return 6
        self.host_buffer = unwrap(value)
        self.set(out, len(self.host_buffer))
        return 0

    def casper_dictionary_put(self, seed, seed_size, item, item_size, value, length):
        assert seed_size == 33
        self.host.dictionaries[self.read(seed, 32).hex()][self.read(item, item_size).decode()] = self.read(value, length)
        return 0

    def casper_call_contract(self, contract_hash, hash_size, entry, entry_size, arg_bytes, arg_size, out):
        assert hash_size == 32 and self.read(contract_hash, hash_size) == bytes([13]) * 32
        data, args, offset = self.read(arg_bytes, arg_size), {}, 4
        for _ in range(int.from_bytes(data[:4], "little")):
            size = int.from_bytes(data[offset:offset + 4], "little")
            offset += 4
            label = data[offset:offset + size].decode()
            offset += size
            length = int.from_bytes(data[offset:offset + 4], "little")
            offset += 4
            args[label] = data[offset:offset + length]
            offset += length + 1
        assert offset == arg_size
        module = self.host.module
        self.host.module = self.host.contract_module or load_module(build_file("counter.metered.wasm"))
        try:
            result = self.host.invoke(self.name(entry, entry_size), args)
        finally:
            self.host.module = module
        self.host_buffer = unwrap(result) if result else None
        self.set(out, len(self.host_buffer) if self.host_buffer else 0)
        return 0

    def casper_get_named_arg_size(self, pointer, size, out):
        value = self.args.get(self.read(pointer, size).decode())
        if value is None:
            return 2
        self.set(out, len(value))
        return 0

    def casper_get_named_arg(self, pointer, size, out, capacity):
        value = self.args.get(self.read(pointer, size).decode())
        if value is None:
            return 2
        assert capacity == len(value)
        self.write(out, value)
        return 0

    def casper_create_contract_package_at_hash(self, contract_hash, access, locked):
        assert locked == 0
        self.write(contract_hash, bytes([11]) * 32)
        self.write(access, bytes([12]) * 32)

    def casper_add_contract_version_with_message_topics(self, contract_hash, hash_size,
            version, ep, ep_size, keys, key_size, topics, topic_size, out, capacity):
        assert hash_size == capacity == 32
        self.host.entry_points = self.read(ep, ep_size)
        topic_data = self.read(topics, topic_size)
        assert len(topic_data) >= 4
        topic_names, offset = [], 4
        for _ in range(int.from_bytes(topic_data[:4], "little")):
            assert offset + 4 <= len(topic_data)
            size = int.from_bytes(topic_data[offset:offset + 4], "little")
            offset += 4
            assert size > 0 and offset + size < len(topic_data)
            topic_names.append(topic_data[offset:offset + size].decode("utf-8"))
            offset += size
            assert topic_data[offset] == 0  # MessageTopicOperation::Add
            offset += 1
        assert offset == len(topic_data)
        assert topic_names == sorted(set(topic_names))
        self.host.message_topics.update(topic_names)
        self.host.contract_module = self.host.module
        data, offset = self.read(keys, key_size), 4
        for _ in range(int.from_bytes(data[:4], "little")):
            length = int.from_bytes(data[offset:offset + 4], "little")
            offset += 4
            label = data[offset:offset + length].decode()
            offset += length
            size = key_length(data, offset)
            self.host.contract[label] = data[offset:offset + size]
            offset += size
        assert offset == key_size
        self.set(version, 1)
        self.write(out, bytes([13]) * 32)
        return 0
