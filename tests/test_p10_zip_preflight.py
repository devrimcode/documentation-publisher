from __future__ import annotations

import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from publisher_engine.archive import ArchiveError, _zip_entry_count, extract_zip


class ZipCentralDirectoryPreflightTests(unittest.TestCase):
    def _archive(self, path: Path, count: int = 2, *, comment: bytes = b""):
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.comment = comment
            for index in range(count):
                archive.writestr(f"file-{index}.txt", f"data-{index}")

    def _as_zip64(self, raw: bytes) -> bytes:
        eocd_sig = b"PK\x05\x06"
        eocd = raw.rfind(eocd_sig)
        self.assertGreaterEqual(eocd, 0)
        fields = struct.unpack_from("<4s4H2LH", raw, eocd)
        _, disk, cd_disk, entries_disk, entries_total, cd_size, cd_offset, comment_len = fields
        self.assertEqual(disk, 0)
        self.assertEqual(cd_disk, 0)
        self.assertEqual(entries_disk, entries_total)
        zip64 = struct.pack(
            "<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
            entries_disk, entries_total, cd_size, cd_offset,
        )
        locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, eocd, 1)
        ordinary = struct.pack(
            "<4s4H2LH", eocd_sig, 0, 0, 0xFFFF, 0xFFFF,
            0xFFFFFFFF, 0xFFFFFFFF, comment_len,
        ) + raw[eocd + 22:eocd + 22 + comment_len]
        return raw[:eocd] + zip64 + locator + ordinary

    def test_entry_limit_is_checked_before_zipinfo_materialization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "many.zip"
            self._archive(archive, count=3)
            with patch("zipfile.ZipFile.infolist", side_effect=AssertionError("infolist must not be called")):
                with self.assertRaisesRegex(ArchiveError, "contains 3 entries; maximum is 2"):
                    extract_zip(archive, root / "out", max_bytes=10_000, max_files=2)
            self.assertFalse((root / "out").exists())

    def test_archive_comment_is_accounted_for_when_finding_eocd(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "comment.zip"
            self._archive(archive, count=2, comment=b"comment" * 500)
            self.assertEqual(_zip_entry_count(archive), 2)
            self.assertEqual(extract_zip(archive, root / "out", max_bytes=10_000, max_files=2), 12)

    def test_self_extracting_prefix_is_supported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "plain.zip"
            self._archive(original, count=1)
            prefixed = root / "sfx.zip"
            prefixed.write_bytes(b"MZ-stub-for-test\x00" + original.read_bytes())
            self.assertEqual(_zip_entry_count(prefixed), 1)
            extract_zip(prefixed, root / "out", max_bytes=10_000, max_files=1)
            self.assertEqual((root / "out" / "file-0.txt").read_text(), "data-0")

    def test_zip64_entry_count_is_parsed_and_archive_extracts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "plain.zip"
            self._archive(original, count=2, comment=b"zip64-test")
            zip64 = root / "zip64.zip"
            zip64.write_bytes(self._as_zip64(original.read_bytes()))
            self.assertEqual(_zip_entry_count(zip64), 2)
            extract_zip(zip64, root / "out", max_bytes=10_000, max_files=2)
            self.assertEqual((root / "out" / "file-1.txt").read_text(), "data-1")

    def test_zip64_entry_limit_is_checked_before_zipinfo_materialization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "plain.zip"
            self._archive(original, count=2)
            zip64_bytes = bytearray(self._as_zip64(original.read_bytes()))
            eocd = zip64_bytes.rfind(b"PK\x05\x06")
            locator = eocd - 20
            zip64_offset = struct.unpack_from("<Q", zip64_bytes, locator + 8)[0]
            # total_entries is field 8 in <4sQ2H2L4Q: offset 32
            struct.pack_into("<Q", zip64_bytes, zip64_offset + 32, 500_000)
            struct.pack_into("<Q", zip64_bytes, zip64_offset + 24, 500_000)
            archive = root / "many-zip64.zip"
            archive.write_bytes(zip64_bytes)
            with patch("zipfile.ZipFile.infolist", side_effect=AssertionError("infolist must not be called")):
                with self.assertRaisesRegex(ArchiveError, "contains 500000 entries; maximum is 10"):
                    extract_zip(archive, root / "out", max_bytes=10_000, max_files=10)

    def test_malformed_archive_without_eocd_is_rejected_and_cleaned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "bad.zip"
            archive.write_bytes(b"not a zip archive")
            output = root / "out"
            with self.assertRaisesRegex(ArchiveError, "end-of-central-directory"):
                extract_zip(archive, output, max_bytes=10_000, max_files=10)
            self.assertFalse(output.exists())

    def test_sfx_prefixed_zip64_is_supported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / "plain.zip"
            self._archive(original, count=1)
            zip64 = root / "zip64.zip"
            zip64.write_bytes(b"self-extracting-stub" + self._as_zip64(original.read_bytes()))
            self.assertEqual(_zip_entry_count(zip64), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
