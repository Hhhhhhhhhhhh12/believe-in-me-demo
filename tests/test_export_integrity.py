"""Verify that the published Pyodide bundle is identical to its readable sources.

The browser loads docs/engine-bundle.json, while Python smoke tests import
docs/source/. Both representations must stay in sync on every pull request.
"""
from __future__ import annotations

import base64
import hashlib
import json
import unittest
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "docs"
SOURCES = EXPORT / "source"
BUNDLE = EXPORT / "engine-bundle.json"
MANIFEST = EXPORT / "EXPORT-MANIFEST.json"


def exported_source_files() -> list[Path]:
    """Ignore Python bytecode generated during tests; it is never exported."""
    return sorted(
        path for path in SOURCES.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


class PublishedEngineIntegrityTests(unittest.TestCase):
    def test_browser_bundle_matches_all_readable_sources(self) -> None:
        bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
        self.assertIsInstance(bundle.get("files"), list)

        decoded: dict[str, bytes] = {}
        for entry in bundle["files"]:
            self.assertIsInstance(entry, dict)
            path = entry["path"]
            self.assertIsInstance(path, str)
            self.assertEqual(PurePosixPath(path).as_posix(), path)
            self.assertFalse(PurePosixPath(path).is_absolute())
            self.assertNotIn("..", PurePosixPath(path).parts)
            self.assertNotIn("\\", path)
            self.assertNotIn(path, decoded, f"Duplicate file in bundle: {path}")
            self.assertIsInstance(entry["content"], str)
            decoded[path] = base64.b64decode(entry["content"], validate=True)

        source_paths = {
            path.relative_to(SOURCES).as_posix()
            for path in exported_source_files()
        }
        self.assertTrue(source_paths, "No readable engine sources found")
        self.assertEqual(
            set(decoded), source_paths,
            "Published bundle and docs/source/ must contain exactly the same files",
        )

        for path, bundled_bytes in decoded.items():
            with self.subTest(path=path):
                self.assertEqual(
                    bundled_bytes,
                    (SOURCES / path).read_bytes(),
                    f"Browser is running a different version of {path}",
                )

    def test_bundle_and_sources_match_export_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], 1)
        recorded = manifest["files"]

        published_files = [BUNDLE, *exported_source_files()]
        for file_path in published_files:
            name = file_path.relative_to(EXPORT).as_posix()
            with self.subTest(path=name):
                self.assertTrue(name in recorded, f"Missing export manifest entry: {name}")
                raw = file_path.read_bytes()
                self.assertEqual(recorded[name]["bytes"], len(raw))
                self.assertEqual(
                    recorded[name]["sha256"],
                    hashlib.sha256(raw).hexdigest(),
                    f"Export hash is stale for {name}",
                )


if __name__ == "__main__":
    unittest.main()
