"""Build cache invalidation and filesystem behavior without a compiler toolchain."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_cache import BuildState, digest, sync_tree, write_changed


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_unchanged_generated_files_preserve_mtime(self):
        path = self.root / "nested/mpconfigport.h"
        self.assertTrue(write_changed(path, "configuration"))
        before = path.stat().st_mtime_ns
        self.assertFalse(write_changed(path, b"configuration"))
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertTrue(write_changed(path, "new configuration"))
        self.assertEqual(path.read_text(), "new configuration")

    def test_port_sync_preserves_overlay_and_unchanged_sources(self):
        source, destination = self.root / "native", self.root / "port"
        write_changed(source / "adapter.c", "adapter")
        write_changed(source / "mpconfigport.h", "baseline config")
        write_changed(source / "micropython/patch", "preserved patch")
        write_changed(destination / "mpconfigport.h", "asyncify config")
        sync_tree(source, destination, ignore=("micropython", "mpconfigport.h"))
        before = (destination / "adapter.c").stat().st_mtime_ns
        sync_tree(source, destination, ignore=("micropython", "mpconfigport.h"))
        self.assertEqual((destination / "adapter.c").stat().st_mtime_ns, before)
        self.assertEqual((destination / "mpconfigport.h").read_text(), "asyncify config")
        self.assertFalse((destination / "micropython").exists())
        (source / "adapter.c").unlink()
        sync_tree(source, destination, ignore=("micropython", "mpconfigport.h"))
        self.assertFalse((destination / "adapter.c").exists())
        self.assertEqual((destination / "mpconfigport.h").read_text(), "asyncify config")

    def test_hits_require_all_outputs_with_matching_hashes(self):
        paths = [self.root / "contract.wasm", self.root / "contract.metered.wasm"]
        for path in paths:
            path.write_bytes(b"wasm")
        state = BuildState(self.root / "build-cache.json")
        self.assertFalse(state.matches("inputs", paths))
        state.save("inputs", paths)
        loaded = BuildState(state.path)
        self.assertTrue(loaded.matches("inputs", paths))
        paths[0].write_bytes(b"corrupt")
        self.assertFalse(loaded.matches("inputs", paths))
        paths[0].write_bytes(b"wasm")
        paths[1].unlink()
        self.assertFalse(loaded.matches("inputs", paths))

    def test_different_inputs_and_output_sets_miss(self):
        path = self.root / "contract.wasm"
        path.write_bytes(b"wasm")
        state = BuildState(self.root / "build-cache.json")
        state.save("old profile", [path])
        self.assertFalse(state.matches("new profile", [path]))
        self.assertFalse(state.matches("old profile", []))
        self.assertFalse(state.matches("old profile", [path, self.root / "extra"]))

    def test_unreadable_or_malformed_state_misses(self):
        path = self.root / "build-cache.json"
        for content in ("", "{partial", "null", "[]", '{"fingerprint":"inputs","outputs":[]}'):
            path.write_text(content)
            self.assertFalse(BuildState(path).matches("inputs", [self.root / "wasm"]))

    def test_profile_digest_is_order_independent_and_tracks_settings(self):
        settings = {"micropython": "1.29.0", "heap": "emmalloc-gc0"}
        self.assertEqual(digest(settings), digest(dict(reversed(list(settings.items())))))
        self.assertNotEqual(digest(settings), digest({**settings, "heap": "static"}))
        self.assertNotEqual(digest(settings), digest({**settings, "micropython": "other"}))


if __name__ == "__main__":
    unittest.main()
