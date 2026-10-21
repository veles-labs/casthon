fn main() -> anyhow::Result<()> {
    wasm_softfloat::run_tool(std::env::args().skip(1).collect())
}
