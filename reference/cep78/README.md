# Independent CEP-78 Rust fixtures

`fixtures.json` was generated from CEP-78 **2.0.0**, commit
[`9a624aa9a4f5cba59260f93652b76948e528c7f2`](https://github.com/casper-ecosystem/cep-78-enhanced-nft/tree/9a624aa9a4f5cba59260f93652b76948e528c7f2),
using `casper-types 6.1.0` and `casper-event-standard 0.7.0`. The upstream
[Apache 2.0 license](LICENSE) is included.

[generate.py](../../tools/cep78-reference/generate.py) verifies the checkout's
commit, extracts the unmodified Rust entrypoint function and event/metadata
record declarations, and compiles a small independent Rust fixture generator.
It does not import the Python SDK or port when generating expectations.

```sh
git clone https://github.com/casper-ecosystem/cep-78-enhanced-nft .cache/cep78-upstream
git -C .cache/cep78-upstream checkout 9a624aa9a4f5cba59260f93652b76948e528c7f2
.venv/bin/python tools/cep78-reference/generate.py
```

The script builds in `.cache/cep78-reference` with Cargo offline. On the first
run, fetch the manifest's dependencies with `cargo fetch --manifest-path
.cache/cep78-reference/Cargo.toml` if they are not already cached, then rerun.
An existing checkout can be supplied as its sole command-line argument.

Fixtures include the full upstream entrypoint map, all ten event layouts,
both Transfer spender cases, CES schemas, native JSON message envelopes,
dictionary key encodings, pretty metadata, and tuple/URef receipt CLValues.
The CES fixture includes the declared `RevokedForAll` record, which the pinned
revision omits from its initialization registry. The native Bytes fixture
encodes UTF-8 JSON as MessagePayload::Bytes, correcting the upstream emitter's
attempt to parse JSON text as an already serialized MessagePayload.

Tests compare fourteen unchanged entrypoint schemas and all seventeen return
types against Rust. `init`, `set_variables`, and `migrate` use the Python
constructor/dynamic-argument convention described in [the port guide](../../docs/cep78.md).
Fixtures validate serialization; they do not run Rust contract execution or
establish historical Rust storage migration compatibility.
