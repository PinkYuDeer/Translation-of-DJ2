#!/usr/bin/env python3
"""Validate Minecraft 1.12.2 resource packs and remove ZIP wrapper directories.

Usage: python scripts/prepare_resourcepacks.py [resourcepacks-directory-or-zip]
       python scripts/prepare_resourcepacks.py --check [directory-or-zip]

Preparation is in place and atomic per archive. File contents and ZIP entry
metadata are preserved; only the common directory above pack.mcmeta is removed.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import zipfile
import zlib


class ResourcePackError(ValueError):
    """An archive cannot be safely used as a Minecraft 1.12.2 resource pack."""


def _pack_prefix(archive: zipfile.ZipFile) -> str:
    entries = archive.infolist()
    seen = set()
    for entry in entries:
        name = entry.filename
        parts = name.rstrip("/").split("/")
        # ZipInfo may normalize backslashes on Windows and truncate NULs.
        if (not name or "\\" in entry.orig_filename or "\x00" in entry.orig_filename or name.startswith("/")
                or any(part in ("", ".", "..") or ":" in part for part in parts)):
            raise ResourcePackError(f"Unsafe ZIP entry: {name!r}")
        if name.rstrip("/") in seen:
            raise ResourcePackError(f"Duplicate ZIP entry: {name!r}")
        seen.add(name.rstrip("/"))
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ResourcePackError(f"Symbolic links are not supported: {name!r}")

    files = {entry.filename for entry in entries if not entry.is_dir()}
    for entry in entries:
        parts = entry.filename.rstrip("/").split("/")
        if any("/".join(parts[:index]) in files for index in range(1, len(parts))):
            raise ResourcePackError(f"ZIP file also used as a directory: {entry.filename!r}")

    metadata = [entry for entry in entries
                if not entry.is_dir() and entry.filename.split("/")[-1] == "pack.mcmeta"]
    if len(metadata) != 1:
        raise ResourcePackError(f"Expected exactly one pack.mcmeta, found {len(metadata)}")
    prefix = metadata[0].filename[:-len("pack.mcmeta")]
    for entry in entries:
        # Explicit empty entries for the wrapper and its ancestors are harmless.
        ancestor = entry.is_dir() and prefix.startswith(entry.filename)
        if not entry.filename.startswith(prefix) and not ancestor:
            raise ResourcePackError(f"Entry outside resource pack root: {entry.filename!r}")

    try:
        document = json.loads(archive.read(metadata[0]).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResourcePackError(f"Invalid pack.mcmeta JSON: {error}") from error
    pack = document.get("pack") if isinstance(document, dict) else None
    if not isinstance(pack, dict) or type(pack.get("pack_format")) is not int or pack["pack_format"] != 3:
        raise ResourcePackError("Minecraft 1.12.2 requires pack.pack_format = 3")
    if "description" not in pack or not isinstance(pack["description"], (str, dict, list)):
        raise ResourcePackError("pack.mcmeta must contain a text pack.description")
    if not any(not entry.is_dir() and entry.filename.startswith(prefix + "assets/")
               for entry in entries):
        raise ResourcePackError("Resource pack must contain files under assets/")
    for entry in entries:
        # Reading all files also verifies decompression and CRC, before rewriting.
        archive.read(entry)
    return prefix


def prepare_resourcepack(path: Path, *, check_only: bool = False) -> bool:
    """Return whether a wrapper was removed; raise without changing invalid ZIPs."""
    temporary_path = None
    try:
        with zipfile.ZipFile(path) as source:
            prefix = _pack_prefix(source)
            if not prefix:
                return False
            if check_only:
                raise ResourcePackError("pack.mcmeta must be at the ZIP root (run preparation first)")
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as temporary:
                temporary_path = Path(temporary.name)
            with zipfile.ZipFile(temporary_path, "w") as destination:
                destination.comment = source.comment
                for entry in source.infolist():
                    if not entry.filename.startswith(prefix):
                        continue  # A directory entry for a wrapper ancestor.
                    relative_name = entry.filename[len(prefix):]
                    if not relative_name:
                        continue  # The wrapper directory itself.
                    renamed = copy.copy(entry)
                    renamed.filename = relative_name
                    renamed.orig_filename = relative_name
                    destination.writestr(renamed, source.read(entry))
        # Validate the completed archive before replacing the source.
        with zipfile.ZipFile(temporary_path) as destination:
            if _pack_prefix(destination):
                raise ResourcePackError("Prepared archive still has a wrapper directory")
        os.replace(temporary_path, path)
        return True
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, zlib.error) as error:
        raise ResourcePackError(str(error)) from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path("resourcepacks"))
    parser.add_argument("--check", action="store_true", help="validate without modifying archives; reject wrapper directories")
    args = parser.parse_args()
    if args.path.is_dir():
        paths = sorted(path for path in args.path.iterdir() if path.is_file() and path.suffix.lower() == ".zip")
    elif args.path.is_file():
        paths = [args.path]
    else:
        parser.error(f"Path does not exist: {args.path}")
    if not paths:
        parser.error(f"No resource pack ZIPs found in {args.path}")
    for path in paths:
        try:
            changed = prepare_resourcepack(path, check_only=args.check)
        except ResourcePackError as error:
            print(f"ERROR: {path}: {error}", file=sys.stderr)
            return 1
        print(f"{'Prepared' if changed else 'Validated'}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
