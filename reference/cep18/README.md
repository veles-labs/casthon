# Independent Rust serialization fixtures

`fixtures.json` is retained from the earlier CEP18 experiment as an independent reference for the Python codecs and the [Cep18 base class](../../contracts/cep18.py), inherited by [MyToken](../../contracts/my_token.py).

The file is copied unchanged from `../cspr-js/reference/cep18/fixtures.json`. That experiment's `tools/cep18-reference` generates it using upstream **CEP18 2.0.0** at [`7fa83c559d04b3516e06b4d7202aba912c14c235`](https://github.com/casper-ecosystem/cep18/tree/7fa83c559d04b3516e06b4d7202aba912c14c235), `casper-types 6.1.0` and `casper-event-standard 0.7.0`. Its [Apache 2.0 license](LICENSE) is included.

The fixtures cover the serialized EntryPoints map, primitive/compound CLValues, every Key variant's bytes and canonical formatting, dictionary item keys, events and caller information. Current tests compare the inherited Python ABI, dictionary keys, all nine event encodings, native JSON and the CES schema against the independent Rust bytes, including compiled Wasm checks. Earlier CEP18 validation measurements are in [../class-based-results](../class-based-results/README.md).

Regenerate in the sibling experiment with `npm run reference:cep18`, then copy the output here. Current builds do not require the sibling checkout or execute the upstream contract.
