# {{PROJECT_NAME}}

A minimal Casthon smart contract that stores a boolean and flips it.

Install the pinned SDK and development tools, then run the native tests and
build the contract:

```sh
uv sync
casthon test
casthon check contracts
casthon build
```

Deployments use the Veles Labs `casper-cli`, including its selected wallet and
network configuration. The first command builds release Wasm and asks the
selected network RPC to speculatively execute the installation. Add
`--broadcast` only after reviewing that result:

```sh
casthon deploy --network testnet --from mywallet:account-0 \
  --arg initial:Bool=false
casthon deploy --network testnet --from mywallet:account-0 \
  --arg initial:Bool=false --broadcast
```

Pass `--simulate` on the first command to use the experimental local execution
engine backed by verified public-RPC state queries instead.

Successful submissions are recorded in `deployments/<network>/flipper.json`.
Commit public testnet and mainnet manifests; they contain addresses and hashes,
not wallet secrets.

The live test starts an isolated Casper network, deploys the compiled contract,
calls `flip`, and queries the resulting state. It is opt-in because it requires
`casper-devnet` and the Casthon Wasm toolchain:

```sh
CSPR_LIVE_TESTS=1 casthon test tests/live
```
