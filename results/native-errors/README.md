# Preserved native error-return measurements

These reports retain the full validation before Asyncify became the default:
97 Casper 2.2.0 transactions, with the network stopped, and a 204,372-byte
counter (SHA-256
`b02716f7adae13788e38463f724d19caaf879bb211e01507f4d0da27c915c26c`).
`native-unwinding.json` also retains the earlier before/after patch comparison.

The corresponding local artifacts and reports were copied into
`build/native-errors/reference/`. That directory is independent of new builds.
The source patches and regeneration recipe remain in
[`native/micropython`](../../native/micropython/README.md).

Build the maintained alternative with `--runtime native-errors`; new artifacts
go to `build/native-errors/`. Its outer dispatcher shares the current port code,
so a rebuild can differ from this snapshot. A new full devnet run followed by
`CSPR_BUILD_DIR=build/native-errors make compare` explicitly refreshes the reports
in this directory. The default Asyncify reports live in the parent `results/`.
