import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_resourcepacks", ROOT / "scripts" / "prepare_resourcepacks.py")
resourcepacks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resourcepacks)

METADATA = json.dumps({"pack": {"pack_format": 3, "description": "Chinese translations"}}).encode()


class ResourcePackTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "pack.zip"

    def write_pack(self, prefix="", metadata=METADATA, extra=None):
        with zipfile.ZipFile(self.path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"archive metadata"
            if prefix:
                archive.writestr(prefix, b"")
            archive.writestr(prefix + "pack.mcmeta", metadata)
            archive.writestr(prefix + "assets/example/lang/zh_cn.lang", "key=中文\n".encode())
            archive.writestr(prefix + "pack.png", b"image content")
            for name, content in (extra or {}).items():
                archive.writestr(name, content)

    def assert_invalid_unchanged(self):
        before = self.path.read_bytes()
        with self.assertRaises(resourcepacks.ResourcePackError):
            resourcepacks.prepare_resourcepack(self.path)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([self.path], list(self.path.parent.iterdir()))

    def test_nested_archive_preserves_payload_and_metadata(self):
        prefix = "上传目录/资源包/"
        self.write_pack(prefix, extra={"上传目录/": b""})
        with zipfile.ZipFile(self.path) as archive:
            before = {entry.filename[len(prefix):]: (archive.read(entry), entry.date_time, entry.compress_type, entry.external_attr)
                      for entry in archive.infolist() if entry.filename.startswith(prefix) and entry.filename != prefix}
        self.assertTrue(resourcepacks.prepare_resourcepack(self.path))
        with zipfile.ZipFile(self.path) as archive:
            after = {entry.filename: (archive.read(entry), entry.date_time, entry.compress_type, entry.external_attr)
                     for entry in archive.infolist()}
            self.assertEqual(before, after)
            self.assertEqual(b"archive metadata", archive.comment)
            self.assertIn("pack.mcmeta", archive.namelist())
        # Already prepared archives remain byte-for-byte unchanged.
        prepared = self.path.read_bytes()
        self.assertFalse(resourcepacks.prepare_resourcepack(self.path))
        self.assertEqual(prepared, self.path.read_bytes())

    def test_check_rejects_wrappers_without_rewriting(self):
        self.write_pack("wrapper/")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(resourcepacks.ResourcePackError, "ZIP root"):
            resourcepacks.prepare_resourcepack(self.path, check_only=True)
        self.assertEqual(before, self.path.read_bytes())

    def test_multiple_pack_roots_are_rejected(self):
        self.write_pack("one/", extra={"two/pack.mcmeta": METADATA})
        self.assert_invalid_unchanged()

    def test_missing_metadata_and_empty_assets_are_rejected(self):
        for entries in ({"assets/example/file": b"data"}, {"pack.mcmeta": METADATA, "assets/": b""}):
            with self.subTest(entries=entries):
                with zipfile.ZipFile(self.path, "w") as archive:
                    for name, content in entries.items():
                        archive.writestr(name, content)
                self.assert_invalid_unchanged()

    def test_invalid_metadata_is_rejected(self):
        for metadata in (b"{", b"[]", b'{"pack": {"pack_format": 4, "description": "wrong"}}',
                         b'{"pack": {"pack_format": true, "description": "wrong"}}',
                         b'{"pack": {"pack_format": 3}}'):
            with self.subTest(metadata=metadata):
                self.write_pack("wrapper/", metadata)
                self.assert_invalid_unchanged()

    def test_files_outside_wrapper_are_rejected(self):
        self.write_pack("wrapper/", extra={"unrelated.txt": b"must not be lost"})
        self.assert_invalid_unchanged()

    def test_unsafe_paths_are_rejected(self):
        for name in ("../escape", "/absolute", "C:/drive", "assets/../escape", "assets//file"):
            with self.subTest(name=name):
                self.write_pack(extra={name: b"data"})
                self.assert_invalid_unchanged()

    def test_backslash_and_nul_names_are_rejected(self):
        for replacement in (b"assets\\file", b"assets\x00file"):
            with self.subTest(replacement=replacement):
                self.write_pack(extra={"assets/file": b"data"})
                # zipfile normalizes names when writing on Windows. Modify both
                # stored filename records to emulate an externally uploaded ZIP.
                self.path.write_bytes(self.path.read_bytes().replace(b"assets/file", replacement))
                self.assert_invalid_unchanged()

    def test_file_directory_collision_is_rejected(self):
        self.write_pack(extra={"assets": b"not a directory"})
        self.assert_invalid_unchanged()

    def test_duplicate_entries_are_rejected(self):
        self.write_pack()
        with zipfile.ZipFile(self.path, "a") as archive:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("assets/example/lang/zh_cn.lang", b"duplicate")
        self.assert_invalid_unchanged()

    def test_symlinks_are_rejected(self):
        self.write_pack()
        with zipfile.ZipFile(self.path, "a") as archive:
            info = zipfile.ZipInfo("assets/link")
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "../../outside")
        self.assert_invalid_unchanged()

    def test_invalid_zip_is_rejected(self):
        self.path.write_bytes(b"not a zip")
        self.assert_invalid_unchanged()

    def test_corrupt_file_crc_is_rejected_before_rewrite(self):
        self.write_pack("wrapper/")
        with zipfile.ZipFile(self.path, "a") as archive:
            archive.writestr("wrapper/assets/corrupt", b"original payload", compress_type=zipfile.ZIP_STORED)
        self.path.write_bytes(self.path.read_bytes().replace(b"original payload", b"modified payload"))
        self.assert_invalid_unchanged()

    def test_repository_packs_are_ready_to_load(self):
        packs = list((ROOT / "resourcepacks").glob("*.zip"))
        self.assertTrue(packs)
        for path in packs:
            with self.subTest(path=path):
                self.assertFalse(resourcepacks.prepare_resourcepack(path, check_only=True))


if __name__ == "__main__":
    unittest.main()
