from __future__ import annotations

import shutil
import stat
import struct
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


class ArchiveError(ValueError):
    pass


def _safe_parts(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    # Common TAR creation commands include a harmless root directory entry
    # named `.` or `./` (for example: tar -C site -czf site.tar.gz .).
    if normalized in {".", "./"}:
        return PurePosixPath(".")
    if path.is_absolute() or not path.parts or ".." in path.parts or any("\x00" in p for p in path.parts):
        raise ArchiveError(f"Unsafe archive path: {name!r}")
    if any(":" in part for part in path.parts):
        raise ArchiveError(f"Colon-bearing Windows path in archive: {name!r}")
    if any(part in {"", "."} for part in path.parts):
        raise ArchiveError(f"Non-canonical archive path: {name!r}")
    return path


def _check_case_collision(seen: set[str], rel: str) -> None:
    key = rel.casefold()
    if key in seen:
        raise ArchiveError(f"Duplicate or case-colliding archive path: {rel}")
    seen.add(key)


def _zip_entry_count(archive: Path) -> int:
    """Read ZIP EOCD metadata without materializing ZipInfo objects."""
    eocd_signature = b"PK\x05\x06"
    zip64_locator_signature = b"PK\x06\x07"
    zip64_eocd_signature = b"PK\x06\x06"
    file_size = archive.stat().st_size
    max_eocd = 22 + 65535
    with archive.open("rb") as stream:
        tail_start = max(0, file_size - max_eocd)
        stream.seek(tail_start)
        tail = stream.read()
        relative = tail.rfind(eocd_signature)
        eocd_relative = None
        while relative >= 0:
            if relative + 22 <= len(tail):
                comment_length = struct.unpack_from("<H", tail, relative + 20)[0]
                if relative + 22 + comment_length == len(tail):
                    eocd_relative = relative
                    break
            relative = tail.rfind(eocd_signature, 0, relative)
        if eocd_relative is None:
            raise ArchiveError("ZIP end-of-central-directory record is missing or malformed")

        eocd_absolute = tail_start + eocd_relative
        (_, disk_number, central_disk, entries_on_disk, entries_total,
         central_size, central_offset, _comment_length) = struct.unpack_from("<4s4H2LH", tail, eocd_relative)
        if disk_number != 0 or central_disk != 0:
            raise ArchiveError("Multi-disk ZIP archives are not supported")

        needs_zip64 = (entries_on_disk == 0xFFFF or entries_total == 0xFFFF
                       or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF)
        if not needs_zip64:
            if entries_on_disk != entries_total:
                raise ArchiveError("Inconsistent ZIP central-directory entry counts")
            return int(entries_total)

        locator_absolute = eocd_absolute - 20
        if locator_absolute < 0:
            raise ArchiveError("ZIP64 locator is missing")
        stream.seek(locator_absolute)
        locator = stream.read(20)
        if len(locator) != 20 or locator[:4] != zip64_locator_signature:
            raise ArchiveError("ZIP64 locator is missing or malformed")
        _, zip64_disk, zip64_offset, disk_count = struct.unpack("<4sLQL", locator)
        if zip64_disk != 0 or disk_count != 1:
            raise ArchiveError("Multi-disk ZIP64 archives are not supported")

        zip64_record = None
        # Normal archives store an absolute offset that is directly seekable.
        stream.seek(zip64_offset)
        candidate = stream.read(56)
        if len(candidate) == 56 and candidate[:4] == zip64_eocd_signature:
            record_size = struct.unpack_from("<Q", candidate, 4)[0]
            if record_size >= 44:
                zip64_record = candidate

        # SFX archives may prepend a stub while keeping offsets relative to the
        # embedded ZIP. Locate the ZIP64 record ending immediately at its locator.
        if zip64_record is None:
            scan_start = max(0, locator_absolute - 1024 * 1024)
            stream.seek(scan_start)
            scan = stream.read(locator_absolute - scan_start)
            pos = scan.rfind(zip64_eocd_signature)
            while pos >= 0:
                if pos + 12 <= len(scan):
                    record_size = struct.unpack_from("<Q", scan, pos + 4)[0]
                    if record_size >= 44 and scan_start + pos + 12 + record_size == locator_absolute:
                        zip64_record = scan[pos:pos + 56]
                        break
                pos = scan.rfind(zip64_eocd_signature, 0, pos)
        if zip64_record is None or len(zip64_record) < 56:
            raise ArchiveError("ZIP64 end-of-central-directory record is missing or malformed")
        values = struct.unpack("<4sQ2H2L4Q", zip64_record[:56])
        _, record_size, _made, _needed, disk, cd_disk, entries_disk64, entries_total64, _cd_size64, _cd_offset64 = values
        if record_size < 44 or disk != 0 or cd_disk != 0 or entries_disk64 != entries_total64:
            raise ArchiveError("Unsupported or inconsistent ZIP64 central-directory metadata")
        return int(entries_total64)


def extract_zip(archive: Path, destination: Path, *, max_bytes: int, max_files: int,
                max_ratio: float = 1000.0) -> int:
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    seen: set[str] = set()
    try:
        entry_count = _zip_entry_count(archive)
        if entry_count > max_files:
            raise ArchiveError(f"ZIP contains {entry_count} entries; maximum is {max_files}")
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) != entry_count:
                raise ArchiveError("ZIP central-directory entry count does not match its directory records")
            for info in infos:
                parts = _safe_parts(info.filename)
                rel = parts.as_posix().rstrip("/")
                if rel in {"", "."}:
                    continue
                _check_case_collision(seen, rel)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise ArchiveError(f"Symlink in ZIP is forbidden: {rel}")
                file_type = stat.S_IFMT(mode)
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ArchiveError(f"Special file in ZIP is forbidden: {rel}")
                if info.file_size > 0 and info.compress_size == 0:
                    raise ArchiveError(f"Invalid compressed size in ZIP entry: {rel}")
                if info.compress_size and info.file_size / info.compress_size > max_ratio:
                    raise ArchiveError(f"ZIP entry compression ratio exceeds {max_ratio}: {rel}")
                total += info.file_size
                if total > max_bytes:
                    raise ArchiveError(f"ZIP expands beyond maximum {max_bytes} bytes")
                target = destination.joinpath(*parts.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ArchiveError(f"ZIP path escapes extraction root: {rel}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, target.open("xb") as dst:
                        while chunk := src.read(1024 * 1024):
                            dst.write(chunk)
        return total
    except Exception as original:
        try:
            if destination.exists():
                shutil.rmtree(destination)
        except OSError as cleanup_error:
            raise ArchiveError(f"Archive extraction failed ({original}) and partial-output cleanup failed ({cleanup_error})") from cleanup_error
        raise


def extract_tar(archive: Path, destination: Path, *, max_bytes: int, max_files: int,
                max_ratio: float = 1000.0) -> int:
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    seen: set[str] = set()
    try:
        archive_size = max(archive.stat().st_size, 1)
        # Stream headers instead of calling getmembers(): getmembers() materializes
        # the complete archive directory before max_files can be enforced. A TAR
        # with an excessive number of tiny entries could otherwise exhaust memory.
        with tarfile.open(archive, "r|*") as tf:
            count = 0
            for member in tf:
                count += 1
                if count > max_files:
                    raise ArchiveError(f"TAR contains more than {max_files} entries")
                parts = _safe_parts(member.name)
                rel = parts.as_posix().rstrip("/")
                if rel in {"", "."}:
                    continue
                _check_case_collision(seen, rel)
                if member.issym() or member.islnk() or member.isdev() or not (member.isfile() or member.isdir()):
                    raise ArchiveError(f"Unsupported special TAR entry: {rel}")
                total += member.size
                if total > max_bytes:
                    raise ArchiveError(f"TAR expands beyond maximum {max_bytes} bytes")
                if total / archive_size > max_ratio:
                    raise ArchiveError(f"TAR overall compression ratio exceeds {max_ratio}")
                target = destination.joinpath(*parts.parts)
                if not target.resolve().is_relative_to(destination.resolve()):
                    raise ArchiveError(f"TAR path escapes extraction root: {rel}")
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    stream = tf.extractfile(member)
                    if stream is None:
                        raise ArchiveError(f"Could not read TAR entry: {rel}")
                    with stream, target.open("xb") as dst:
                        while chunk := stream.read(1024 * 1024):
                            dst.write(chunk)
        return total
    except Exception as original:
        try:
            if destination.exists():
                shutil.rmtree(destination)
        except OSError as cleanup_error:
            raise ArchiveError(f"Archive extraction failed ({original}) and partial-output cleanup failed ({cleanup_error})") from cleanup_error
        raise
