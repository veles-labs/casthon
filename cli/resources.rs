//! Compiler and SDK resources embedded in the registry-installed binary.

use anyhow::{Context, Result};
use include_dir::{Dir, DirEntry, include_dir};
use sha2::{Digest, Sha256};
use std::{env, fs, path::PathBuf, time::SystemTime};

static NATIVE: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/native");
static SCRIPTS: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/scripts");
static RUNTIME: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/runtime");
static SDK: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/src/casthon");
static CONTRACTS: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/contracts");
static CEP18_REFERENCE: Dir<'_> = include_dir!("$CARGO_MANIFEST_DIR/reference/cep18");
static MANIFEST: &[u8] = include_bytes!("../pyproject.toml");

const DIRECTORIES: [(&str, &Dir<'_>); 6] = [
    ("native", &NATIVE),
    ("scripts", &SCRIPTS),
    ("runtime", &RUNTIME),
    ("src/casthon", &SDK),
    ("contracts", &CONTRACTS),
    ("reference/cep18", &CEP18_REFERENCE),
];

fn hash_dir(hash: &mut Sha256, directory: &Dir<'_>) {
    for entry in directory.entries() {
        match entry {
            DirEntry::Dir(child) => hash_dir(hash, child),
            DirEntry::File(file) => {
                hash.update(file.path().to_string_lossy().as_bytes());
                hash.update(file.contents());
            }
        }
    }
}

fn cache_root() -> PathBuf {
    env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
        .unwrap_or_else(env::temp_dir)
        .join("casthon")
}

pub fn sdk_root() -> Result<PathBuf> {
    let mut hash = Sha256::new();
    hash.update(MANIFEST);
    for (name, directory) in DIRECTORIES {
        hash.update(name.as_bytes());
        hash_dir(&mut hash, directory);
    }
    let digest: String = hash
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let destination = cache_root().join(format!("{}-{}", env!("CARGO_PKG_VERSION"), &digest[..16]));
    if destination.join(".complete").is_file() {
        return Ok(destination);
    }

    fs::create_dir_all(cache_root()).context("Create Casthon resource cache")?;
    let nonce = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)?
        .as_nanos();
    let staging = cache_root().join(format!(".extract-{}-{nonce}", std::process::id()));
    fs::create_dir(&staging).context("Create temporary Casthon resource directory")?;
    let extracted = (|| -> Result<()> {
        for (name, directory) in DIRECTORIES {
            let folder = staging.join(name);
            fs::create_dir_all(&folder)?;
            directory.extract(&folder)?;
        }
        fs::write(staging.join("pyproject.toml"), MANIFEST)?;
        fs::write(staging.join(".complete"), digest.as_bytes())?;
        Ok(())
    })();
    if let Err(error) = extracted {
        let _ = fs::remove_dir_all(&staging);
        return Err(error).context("Extract bundled Casthon resources");
    }
    if destination.exists() && !destination.join(".complete").is_file() {
        fs::remove_dir_all(&destination).context("Remove incomplete Casthon resource cache")?;
    }
    if let Err(error) = fs::rename(&staging, &destination) {
        let _ = fs::remove_dir_all(&staging);
        if !destination.join(".complete").is_file() {
            return Err(error).context("Install bundled Casthon resources");
        }
    }
    Ok(destination)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_resources_contain_the_build_worker_and_recipe() {
        let root = sdk_root().unwrap();
        assert!(root.join("scripts/build.py").is_file());
        assert!(root.join("native/toolchain.json").is_file());
        assert!(root.join("src/casthon/__init__.py").is_file());
        assert!(root.join("contracts/cep18.py").is_file());
        assert_eq!(root, sdk_root().unwrap());
    }
}
