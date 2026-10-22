#![cfg_attr(not(test), no_std)]
#![cfg_attr(not(test), no_main)]

use odra::prelude::*;

#[odra::module]
pub struct BenchCounter {
    value: Var<u32>,
}

#[odra::module]
impl BenchCounter {
    pub fn init(&mut self) {
        self.value.set(0);
    }

    pub fn get(&self) -> u32 {
        self.value.get_or_default()
    }

    pub fn set(&mut self, value: u32) {
        self.value.set(value);
    }

    pub fn increment_by(&mut self, amount: u32) {
        self.value.set(self.get() + amount);
    }

    pub fn version(&self) -> u32 {
        1 // benchmark-edit
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use odra::host::{Deployer, NoArgs};

    fn deploy() -> BenchCounterHostRef {
        BenchCounter::deploy(&odra_test::env(), NoArgs)
    }

    #[test]
    fn initial_value() {
        assert_eq!(deploy().get(), 0);
    }

    #[test]
    fn set() {
        let mut counter = deploy();
        counter.set(42);
        assert_eq!(counter.get(), 42);
    }

    #[test]
    fn increment() {
        let mut counter = deploy();
        counter.increment_by(7);
        assert_eq!(counter.get(), 7);
    }

    #[test]
    fn repeated_increments() {
        let mut counter = deploy();
        for _ in 0..10 {
            counter.increment_by(3);
        }
        assert_eq!(counter.get(), 30);
    }

    #[test]
    fn independent_deployments() {
        let mut first = deploy();
        let second = deploy();
        first.set(99);
        assert_eq!(first.get(), 99);
        assert_eq!(second.get(), 0);
    }

    #[test]
    fn version() {
        let expected: u32 = std::env::var("BENCHMARK_EXPECTED_VERSION")
            .unwrap_or_else(|_| "1".to_string())
            .parse()
            .unwrap();
        assert_eq!(deploy().version(), expected);
    }
}
