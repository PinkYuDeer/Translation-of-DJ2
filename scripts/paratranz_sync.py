#!/usr/bin/env python3
"""
DJ2 Translation Sync Script
Syncs translation files between GitHub and ParaTranz.

Usage:
    python paratranz_sync.py upload   [--version TAG]   Upload en_US + zh_CN to ParaTranz
    python paratranz_sync.py download                   Download translations from ParaTranz
"""

import argparse
import json
import os
import re
import sys
import time
import zipfile
import io
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from urllib.parse import quote

# ── Config ───────────────────────────────────────────────────────────────────

PROJECT_ID = 15018
PARATRANZ_API = "https://paratranz.cn/api"
DJ2_REPO = "Divine-Journey-2/Divine-Journey-2"

# Mapping: PT filename → (upstream path in DJ2 repo, local path in this repo)
# upstream_path is relative to overrides/ in the DJ2 repo
LANG_FILES = {
    "betterquesting": {
        "upstream": "resources/betterquesting/lang/en_us.lang",
        "local_en": "resources/betterquesting/lang/en_us.lang",
        "local_zh": "resources/betterquesting/lang/zh_cn.lang",
    },
    "contenttweaker": {
        "upstream": "resources/contenttweaker/lang/en_us.lang",
        "local_en": "resources/contenttweaker/lang/en_us.lang",
        "local_zh": "resources/contenttweaker/lang/zh_cn.lang",
    },
    "crafttweaker": {
        "upstream": "resources/crafttweaker/lang/en_us.lang",
        "local_en": "resources/crafttweaker/lang/en_us.lang",
        "local_zh": "resources/crafttweaker/lang/zh_cn.lang",
    },
    "enchantment_descriptions": {
        "upstream": "resources/enchantment_descriptions/lang/en_us.lang",
        "local_en": "resources/enchantment_descriptions/lang/en_us.lang",
        "local_zh": "resources/enchantment_descriptions/lang/zh_cn.lang",
    },
    "requious_frakto": {
        "upstream": "resources/requious_frakto/lang/en_us.lang",
        "local_en": "resources/requious_frakto/lang/en_us.lang",
        "local_zh": "resources/requious_frakto/lang/zh_cn.lang",
    },
    "groovy": {
        "upstream": "groovy/assets/divine_journey_2/lang/en_us.lang",
        "local_en": "resources/groovy/lang/en_us.lang",
        "local_zh": "resources/groovy/lang/zh_cn.lang",
    },
}

# ── Lang file parsing ────────────────────────────────────────────────────────


def parse_lang(content: str) -> dict[str, str]:
    """Parse a .lang file into {key: value} dict, skipping comments and blanks."""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key] = value
    return result


def build_lang(entries: dict[str, str], original_content: str = "") -> str:
    """Rebuild a .lang file preserving comment/blank structure from original if available."""
    if not original_content:
        return "\n".join(f"{k}={v}" for k, v in entries.items()) + "\n"

    lines = []
    used_keys = set()
    for line in original_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            if key in entries:
                lines.append(f"{key}={entries[key]}")
                used_keys.add(key)
            else:
                lines.append(line)
        else:
            lines.append(line)

    # Append any new keys not in original
    for key, value in entries.items():
        if key not in used_keys:
            lines.append(f"{key}={value}")

    return "\n".join(lines) + "\n"


# ── ParaTranz API ────────────────────────────────────────────────────────────


def get_token() -> str:
    token = os.environ.get("PARATRANZ_TOKEN", "")
    if not token:
        print("Error: PARATRANZ_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)
    return token


def api_request(method: str, path: str, token: str, data=None, files=None,
                retry=3) -> dict | list | None:
    """Make a ParaTranz API request with retry logic."""
    url = f"{PARATRANZ_API}{path}"

    for attempt in range(retry):
        try:
            if files:
                # Multipart form upload
                boundary = "----PythonFormBoundary"
                body = b""
                for field_name, (filename, file_data, content_type) in files.items():
                    body += f"--{boundary}\r\n".encode()
                    body += f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
                    body += f"Content-Type: {content_type}\r\n\r\n".encode()
                    body += file_data if isinstance(file_data, bytes) else file_data.encode("utf-8")
                    body += b"\r\n"
                body += f"--{boundary}--\r\n".encode()

                req = Request(url, data=body, method=method)
                req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            elif data is not None:
                body = json.dumps(data).encode("utf-8")
                req = Request(url, data=body, method=method)
                req.add_header("Content-Type", "application/json")
            else:
                req = Request(url, method=method)

            req.add_header("Authorization", token)

            with urlopen(req, timeout=60) as resp:
                resp_body = resp.read().decode("utf-8")
                if resp_body:
                    return json.loads(resp_body)
                return None

        except HTTPError as e:
            if e.code == 429:
                wait = min(2 ** attempt * 5, 60)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code >= 500 and attempt < retry - 1:
                time.sleep(2 ** attempt)
                continue
            print(f"  API error {e.code}: {e.read().decode()}", file=sys.stderr)
            raise
        except Exception as e:
            if attempt < retry - 1:
                time.sleep(2 ** attempt)
                continue
            raise

    return None


def get_pt_files(token: str) -> list[dict]:
    """Get all files in the PT project."""
    return api_request("GET", f"/projects/{PROJECT_ID}/files", token) or []


def get_pt_strings(token: str, file_id: int) -> list[dict]:
    """Get all strings for a PT file (handles pagination)."""
    all_strings = []
    page = 1
    while True:
        result = api_request(
            "GET",
            f"/projects/{PROJECT_ID}/strings?file={file_id}&page={page}&pageSize=500",
            token,
        )
        if not result:
            break
        items = result if isinstance(result, list) else result.get("results", [])
        all_strings.extend(items)
        if len(items) < 500:
            break
        page += 1
    return all_strings


def upload_file(token: str, pt_filename: str, json_content: str,
                existing_files: dict[str, int]) -> None:
    """Upload or update a file on ParaTranz."""
    file_data = json_content.encode("utf-8")
    files_payload = {
        "file": (f"{pt_filename}.json", file_data, "application/json"),
    }

    if pt_filename in existing_files:
        file_id = existing_files[pt_filename]
        print(f"  Updating existing file: {pt_filename} (id={file_id})")
        api_request(
            "POST",
            f"/projects/{PROJECT_ID}/files/{file_id}",
            token,
            files=files_payload,
        )
    else:
        print(f"  Creating new file: {pt_filename}")
        api_request(
            "POST",
            f"/projects/{PROJECT_ID}/files",
            token,
            files=files_payload,
        )


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_upload(args):
    """Upload en_US source + zh_CN translations to ParaTranz."""
    token = get_token()
    repo_root = Path(__file__).resolve().parent.parent
    version = args.version

    # If version specified, download fresh en_US from upstream
    if version:
        print(f"Downloading en_US files from DJ2 {version}...")
        for name, info in LANG_FILES.items():
            upstream_url = (
                f"https://raw.githubusercontent.com/{DJ2_REPO}/"
                f"{version}/overrides/{info['upstream']}"
            )
            try:
                with urlopen(upstream_url, timeout=30) as resp:
                    content = resp.read().decode("utf-8")
                en_path = repo_root / info["local_en"]
                en_path.parent.mkdir(parents=True, exist_ok=True)
                en_path.write_text(content, encoding="utf-8")
                print(f"  Downloaded: {name} ({len(parse_lang(content))} keys)")
            except HTTPError as e:
                if e.code == 404:
                    print(f"  Skipped (not found upstream): {name}")
                else:
                    raise

    # Get existing PT files
    pt_files = get_pt_files(token)
    existing_files = {}
    for f in pt_files:
        # PT filenames may have .json suffix, strip it for matching
        fname = f["name"]
        if fname.endswith(".json"):
            fname = fname[:-5]
        existing_files[fname] = f["id"]
    print(f"Existing PT files: {list(existing_files.keys())}")

    # Build and upload each file
    for name, info in LANG_FILES.items():
        en_path = repo_root / info["local_en"]
        zh_path = repo_root / info["local_zh"]

        if not en_path.exists():
            print(f"Skipping {name}: no en_US file")
            continue

        en_content = en_path.read_text(encoding="utf-8")
        en_entries = parse_lang(en_content)

        zh_entries = {}
        if zh_path.exists():
            zh_content = zh_path.read_text(encoding="utf-8")
            zh_entries = parse_lang(zh_content)

        # Build PT JSON
        pt_items = []
        for key, original in en_entries.items():
            item = {
                "key": key,
                "original": original,
                "translation": zh_entries.get(key, ""),
            }
            pt_items.append(item)

        json_content = json.dumps(pt_items, ensure_ascii=False, indent=2)

        print(f"Uploading {name}: {len(pt_items)} strings, "
              f"{sum(1 for i in pt_items if i['translation'])} translated")
        upload_file(token, name, json_content, existing_files)
        # Rate limit courtesy
        time.sleep(1)

    print("Upload complete!")


def cmd_download(args):
    """Download translations from ParaTranz and write to local zh_CN files."""
    token = get_token()
    repo_root = Path(__file__).resolve().parent.parent

    pt_files = get_pt_files(token)
    pt_file_map = {}
    for f in pt_files:
        fname = f["name"]
        if fname.endswith(".json"):
            fname = fname[:-5]
        pt_file_map[fname] = f

    for name, info in LANG_FILES.items():
        if name not in pt_file_map:
            print(f"Skipping {name}: not found on ParaTranz")
            continue

        file_id = pt_file_map[name]["id"]
        print(f"Downloading {name} (id={file_id})...")

        strings = get_pt_strings(token, file_id)
        print(f"  Got {len(strings)} strings")

        # Build zh_CN entries from PT strings
        zh_entries = {}
        for s in strings:
            key = s.get("key", "")
            translation = s.get("translation", "")
            if key and translation:
                zh_entries[key] = translation

        # Read en_US to preserve file structure
        en_path = repo_root / info["local_en"]
        en_content = ""
        if en_path.exists():
            en_content = en_path.read_text(encoding="utf-8")

        zh_content = build_lang(zh_entries, en_content)

        zh_path = repo_root / info["local_zh"]
        zh_path.parent.mkdir(parents=True, exist_ok=True)
        zh_path.write_text(zh_content, encoding="utf-8")
        print(f"  Wrote {len(zh_entries)} translations to {info['local_zh']}")
        time.sleep(0.5)

    print("Download complete!")


def cmd_check_release(args):
    """Check if there's a new DJ2 release compared to the stored version."""
    repo_root = Path(__file__).resolve().parent.parent
    version_file = repo_root / ".last_synced_version"

    # Get latest release from GitHub
    url = f"https://api.github.com/repos/{DJ2_REPO}/releases/latest"
    req = Request(url)
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token:
        req.add_header("Authorization", f"token {gh_token}")
    with urlopen(req, timeout=30) as resp:
        release = json.loads(resp.read().decode("utf-8"))

    latest = release["tag_name"]
    current = ""
    if version_file.exists():
        current = version_file.read_text().strip()

    if latest != current:
        print(f"NEW_RELEASE={latest}")
        print(f"CURRENT={current}")
        # Write to GITHUB_OUTPUT if in Actions
        gh_output = os.environ.get("GITHUB_OUTPUT", "")
        if gh_output:
            with open(gh_output, "a") as f:
                f.write(f"new_release=true\n")
                f.write(f"version={latest}\n")
                f.write(f"current={current}\n")
    else:
        print(f"Up to date: {current}")
        gh_output = os.environ.get("GITHUB_OUTPUT", "")
        if gh_output:
            with open(gh_output, "a") as f:
                f.write(f"new_release=false\n")
                f.write(f"version={latest}\n")


def cmd_update_version(args):
    """Update the stored version after a successful sync."""
    repo_root = Path(__file__).resolve().parent.parent
    version_file = repo_root / ".last_synced_version"
    version_file.write_text(args.version + "\n")
    print(f"Updated version to {args.version}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DJ2 Translation Sync")
    sub = parser.add_subparsers(dest="command")

    p_upload = sub.add_parser("upload", help="Upload translations to ParaTranz")
    p_upload.add_argument("--version", help="DJ2 release tag to download en_US from")

    p_download = sub.add_parser("download", help="Download translations from ParaTranz")

    p_check = sub.add_parser("check-release", help="Check for new DJ2 release")

    p_update = sub.add_parser("update-version", help="Update stored version")
    p_update.add_argument("version", help="Version tag")

    args = parser.parse_args()
    if args.command == "upload":
        cmd_upload(args)
    elif args.command == "download":
        cmd_download(args)
    elif args.command == "check-release":
        cmd_check_release(args)
    elif args.command == "update-version":
        cmd_update_version(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
