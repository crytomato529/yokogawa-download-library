#!/usr/bin/env python3
"""Search, compare, and incrementally download Yokogawa Library materials."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from library_common import atomic_json, configure_console, download_validated, fingerprint, open_url, save_snapshot, valid_record


API_URL = "https://yc3.yokocms.com/api/technical-library/"
SITE_BASE = "https://www.yokogawa.com"
DEFAULT_REGION_ID = 1
DEFAULT_BATCH_SIZE = 20
DOWNLOAD_EXTS = {
    ".pdf",
    ".zip",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".exe",
    ".msi",
    ".csv",
}
USER_AGENT = (
    "Mozilla/5.0 (compatible; YokogawaLibrarySkill/1.0; "
    "+https://www.yokogawa.com/library/)"
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def request_json(url: str, retries: int = 3, delay: float = 1.0) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Origin": SITE_BASE,
                    "Referer": f"{SITE_BASE}/library/search/",
                    "User-Agent": USER_AGENT,
                },
            )
            with open_url(req, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404, 567):
                break
            if attempt + 1 < retries:
                time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"Failed to fetch JSON from {url}: {last_error}") from last_error


def request_bytes(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": SITE_BASE})
    with open_url(req, timeout=timeout) as response:
        return response.read()


def strip_tags(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def absolute_url(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    return urllib.parse.urljoin(SITE_BASE, value)


def url_ext(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    return Path(path).suffix.lower()


def is_direct_file_url(url: str, file_ext: str = "") -> bool:
    ext = url_ext(url)
    if ext in DOWNLOAD_EXTS:
        return True
    if file_ext:
        normalized = "." + file_ext.lower().lstrip(".")
        return normalized in DOWNLOAD_EXTS and bool(url)
    return False


def item_key(item: dict[str, Any]) -> str:
    for field in ("id", "node_id", "direct_download_url", "detail_page_url", "url"):
        value = item.get(field)
        if value not in (None, ""):
            return str(value)
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode("utf-8")).hexdigest()


def normalize_hit(raw_hit: dict[str, Any]) -> dict[str, Any]:
    source = raw_hit.get("_source", raw_hit)
    raw_url = source.get("offsite_url") or source.get("url") or ""
    resolved_url = absolute_url(raw_url)
    detail_page = bool(source.get("detail_page"))
    locked = bool(source.get("locked"))
    software_agreement = bool(source.get("software_agreement"))
    file_ext = str(source.get("file_ext") or "").lower().lstrip(".")

    direct_download_url = ""
    detail_page_url = ""
    skip_reason = ""
    if detail_page:
        detail_page_url = resolved_url
        skip_reason = "detail_page"
    elif locked:
        skip_reason = "locked"
    elif software_agreement:
        skip_reason = "software_agreement"
    elif is_direct_file_url(resolved_url, file_ext):
        direct_download_url = resolved_url
    else:
        detail_page_url = resolved_url
        skip_reason = "not_direct_file"

    item = {
        "id": source.get("id"),
        "node_id": source.get("node_id"),
        "name": strip_tags(source.get("name")),
        "code": strip_tags(source.get("code")),
        "resource_type": source.get("resource_type") or "",
        "category": source.get("category") or "",
        "file_ext": file_ext,
        "file_size": source.get("file_size") or "",
        "edition": strip_tags(source.get("edition")),
        "updated_at": source.get("updated_at") or "",
        "updated_at_display": source.get("updated_at_display") or "",
        "locked": locked,
        "software_agreement": software_agreement,
        "detail_page": detail_page,
        "url": resolved_url,
        "direct_download_url": direct_download_url,
        "detail_page_url": detail_page_url,
        "download_skip_reason": skip_reason,
        "summary": strip_tags(source.get("summary") or source.get("details")),
        "products": [r.get("name", "") for r in source.get("products", [])],
        "product_categories": [r.get("name", "") for r in source.get("product_categories", [])],
        "industries": [r.get("name", "") for r in source.get("industries", [])],
    }
    item["key"] = item_key(item)
    return item


def parse_ids(value: str | None) -> str | None:
    if not value:
        return None
    ids = []
    for part in value.split(","):
        part = part.strip()
        if part:
            ids.append(str(int(part)))
    return ",".join(ids) if ids else None


def build_params(args: argparse.Namespace, offset: int, size: int) -> dict[str, Any]:
    params: dict[str, Any] = {
        "offset": offset,
        "page": (offset // size) + 1,
        "region_id": args.region_id,
        "s": args.sort,
        "size": size,
    }
    if args.keyword:
        params["q"] = args.keyword
    if args.relevancy:
        params["relevancy"] = args.relevancy
    for arg_name, api_name in (("types", "t"), ("products", "p"), ("industries", "i")):
        parsed = parse_ids(getattr(args, arg_name, None))
        if parsed:
            params[api_name] = parsed
    return params


def search_library(args: argparse.Namespace) -> dict[str, Any]:
    size = args.batch_size
    offset = 0
    items: list[dict[str, Any]] = []
    total = None
    seen_keys: set[str] = set()
    repeated_page = False

    while True:
        params = build_params(args, offset, size)
        url = API_URL + "?" + urllib.parse.urlencode(params)
        data = request_json(url)
        hits = data.get("hits", {})
        total = hits.get("total", total)
        if isinstance(total, dict):
            total = total.get("value")
        raw_hits = hits.get("hits", [])
        if not raw_hits:
            break
        before_count = len(items)
        for raw_hit in raw_hits:
            item = normalize_hit(raw_hit)
            if item["key"] not in seen_keys:
                seen_keys.add(item["key"])
                items.append(item)
        print(f"Fetched {len(items)} of {total if total is not None else '?'}", file=sys.stderr)
        if len(items) == before_count:
            repeated_page = True
            break
        offset += len(raw_hits)
        if args.max_results and len(items) >= args.max_results:
            items = items[: args.max_results]
            break
        if total is not None and offset >= int(total):
            break

    manifest = {
        "generated_at": now_iso(),
        "source": "Yokogawa Library",
        "api_url": API_URL,
        "site_url": f"{SITE_BASE}/library/",
        "query": {
            "keyword": args.keyword,
            "region_id": args.region_id,
            "sort": args.sort,
            "types": args.types,
            "products": args.products,
            "industries": args.industries,
        },
        "total_reported": total,
        "count": len(items),
        "search_complete": not repeated_page and total is not None and len(items) >= int(total),
        "direct_download_count": sum(1 for item in items if item["direct_download_url"]),
        "download_target_count": sum(1 for item in items if item["direct_download_url"]),
        "detail_page_count": sum(1 for item in items if item["download_skip_reason"] == "detail_page"),
        "accessible_archive_count": sum(
            1
            for item in items
            if item["direct_download_url"] or item["download_skip_reason"] == "detail_page"
        ),
        "manual_required_count": sum(
            1
            for item in items
            if not item["direct_download_url"] and item["download_skip_reason"] != "detail_page"
        ),
        "items": items,
    }
    return manifest


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    atomic_json(path, manifest)


def write_csv(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "name",
        "code",
        "resource_type",
        "category",
        "file_ext",
        "file_size",
        "edition",
        "updated_at_display",
        "direct_download_url",
        "detail_page_url",
        "download_skip_reason",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in manifest["items"]:
            writer.writerow({field: item.get(field, "") for field in fields})


def sanitize_filename(value: str, max_len: int = 150) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or "yokogawa_file")[:max_len].strip(" .")


def document_type_for_item(item: dict[str, Any]) -> str:
    category = str(item.get("category") or "").strip()
    resource_type = str(item.get("resource_type") or "").strip()
    if category:
        return category
    if resource_type:
        return resource_type
    return "Document"


def version_for_item(item: dict[str, Any]) -> str:
    edition = str(item.get("edition") or "").strip()
    if edition:
        return f"Edition {edition}" if re.fullmatch(r"[\d.]+", edition) else edition
    updated = str(item.get("updated_at_display") or "").strip()
    if updated:
        return updated
    return ""


def filename_for_item(item: dict[str, Any]) -> str:
    url = item.get("direct_download_url") or item.get("detail_page_url") or item.get("url") or ""
    ext = url_ext(url)
    if item.get("direct_download_url") and not ext and item.get("file_ext"):
        ext = "." + item["file_ext"].lower().lstrip(".")
    if item.get("detail_page_url") and ext not in DOWNLOAD_EXTS:
        ext = ".html"
    parts = [
        document_type_for_item(item),
        str(item.get("code") or "").strip(),
        str(item.get("name") or "").strip(),
        version_for_item(item),
    ]
    fixed_length = sum(len(part) for index, part in enumerate(parts) if index != 2)
    parts[2] = parts[2][:max(16, 150 - fixed_length - 9)]
    stem = sanitize_filename(" - ".join(part for part in parts if part))
    suffix = "" if ext and stem.lower().endswith(ext.lower()) else ext
    return stem + suffix


def unique_destination(path: Path, key: str) -> Path:
    if not path.exists():
        return path
    suffix = path.suffix
    stem = path.stem
    key = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    candidate = path.with_name(f"{stem} [{key}]{suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{stem} [{key}-{counter}]{suffix}")
        counter += 1
    return candidate


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return load_json(path)
    return {"updated_at": None, "files": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    atomic_json(path, state)


def download_one(url: str, dest: Path) -> tuple[int, str]:
    result = download_validated(url, dest, {"User-Agent": USER_AGENT, "Referer": SITE_BASE})
    return result["bytes"], result["sha256"]


def save_page(url: str, dest: Path) -> tuple[int, str]:
    return download_one(url, dest)


def item_archive_url(item: dict[str, Any], direct_only: bool = True) -> tuple[str, str]:
    if item.get("locked") or item.get("software_agreement"):
        return "", ""
    if item.get("direct_download_url"):
        return item["direct_download_url"], "file"
    if not direct_only and item.get("detail_page_url") and item.get("download_skip_reason") == "detail_page":
        return item["detail_page_url"], "page"
    return "", ""


def completed_record_is_current(record: dict[str, Any] | None, url: str) -> bool:
    return valid_record(record, url)


def move_completed_record_to_desired_path(record: dict[str, Any], desired: Path) -> Path:
    current = Path(record.get("path", ""))
    if current == desired:
        return desired
    if current.exists():
        desired.parent.mkdir(parents=True, exist_ok=True)
        if desired.exists():
            desired = unique_destination(desired, str(record.get("key") or "duplicate"))
        current.replace(desired)
        record["path"] = str(desired)
    return desired


def command_search(args: argparse.Namespace) -> int:
    manifest = search_library(args)
    write_manifest(manifest, Path(args.out))
    if args.csv:
        write_csv(manifest, Path(args.csv))
    print(
        f"Saved {manifest['count']} results "
        f"({manifest['direct_download_count']} direct files, "
        f"{manifest['accessible_archive_count']} accessible items) to {args.out}"
    )
    return 0


def command_download(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest))
    download_dir = Path(args.dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state) if args.state else download_dir / ".yokogawa_download_state.json"
    state = load_state(state_path)
    files = state.setdefault("files", {})
    errors = state.setdefault("errors", {})
    downloaded = skipped = failed = inaccessible = 0

    for item in manifest.get("items", []):
        url, archive_type = item_archive_url(item, args.direct_only)
        key = item_key(item)
        if not url:
            inaccessible += 1
            continue
        filename = filename_for_item(item)
        desired = download_dir / filename
        existing = files.get(key)
        item_fingerprint = fingerprint(item)
        current = valid_record(existing, url, item_fingerprint)
        if not args.force and current and not getattr(args, "revalidate", False):
            skipped += 1
            continue
        if args.limit and downloaded >= args.limit:
            continue
        try:
            print(f"Downloading: {filename}", file=sys.stderr)
            dest = desired
            if dest.exists():
                dest = unique_destination(dest, key)
            result = download_validated(url, dest, {"User-Agent": USER_AGENT, "Referer": SITE_BASE},
                                        existing if current and not args.force else None)
            if existing and not result["unchanged"] and existing.get("path") != result["path"]:
                state.setdefault("history", []).append(existing)
            files[key] = {
                **result,
                "key": key,
                "status": "completed",
                "fingerprint": item_fingerprint,
                "archive_type": archive_type,
                "url": url,
                "downloaded_at": existing.get("downloaded_at") if result["unchanged"] and existing else now_iso(),
                "checked_at": now_iso(),
                "name": item.get("name", ""),
                "code": item.get("code", ""),
                "document_type": document_type_for_item(item),
                "version": item.get("edition", ""),
                "source_url": item.get("source_url") or url,
                "source_tier": item.get("source_tier", "official"),
                "metadata_verified": item.get("metadata_verified", False),
                "language": item.get("document_language") or item.get("language", ""),
            }
            errors.pop(key, None)
            if result["unchanged"]:
                skipped += 1
            else:
                downloaded += 1
            save_state(state_path, state)
        except Exception as exc:  # noqa: BLE001 - CLI should continue per file.
            failed += 1
            errors[key] = {"url": url, "error": str(exc), "failed_at": now_iso()}
            save_state(state_path, state)
            print(f"FAILED {url}: {exc}", file=sys.stderr)

    save_state(state_path, state)
    atomic_json(download_dir / "download_report.json", {"generated_at": now_iso(), "downloaded": downloaded,
                "skipped": skipped, "failed": failed, "inaccessible": inaccessible, "errors": errors})
    print(
        f"Download complete: {downloaded} downloaded, {skipped} skipped, "
        f"{inaccessible} inaccessible, {failed} failed"
    )
    return 1 if failed else 0


def compare_manifests(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_items = {item_key(item): item for item in old.get("items", [])}
    new_items = {item_key(item): item for item in new.get("items", [])}
    added_keys = sorted(set(new_items) - set(old_items))
    removed_keys = sorted(set(old_items) - set(new_items))
    fields = [
        "name",
        "code",
        "resource_type",
        "category",
        "file_ext",
        "file_size",
        "edition",
        "updated_at",
        "updated_at_display",
        "direct_download_url",
        "detail_page_url",
    ]
    changed = []
    for key in sorted(set(old_items) & set(new_items)):
        before = old_items[key]
        after = new_items[key]
        changes = {
            field: {"old": before.get(field), "new": after.get(field)}
            for field in fields
            if before.get(field) != after.get(field)
        }
        if changes:
            changed.append({"key": key, "id": after.get("id"), "name": after.get("name"), "changes": changes})

    return {
        "generated_at": now_iso(),
        "old_count": len(old_items),
        "new_count": len(new_items),
        "added_count": len(added_keys),
        "removed_count": len(removed_keys),
        "removal_confirmed": False,
        "removal_note": "Not observed in this search; local files are retained. Check source before declaring withdrawal.",
        "changed_count": len(changed),
        "added": [new_items[key] for key in added_keys],
        "removed": [old_items[key] for key in removed_keys],
        "changed": changed,
    }


def command_compare(args: argparse.Namespace) -> int:
    diff = compare_manifests(load_json(Path(args.old)), load_json(Path(args.new)))
    if args.out:
        Path(args.out).write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Compare complete: {diff['added_count']} added, "
        f"{diff['removed_count']} removed, {diff['changed_count']} changed"
    )
    return 0


def command_sync(args: argparse.Namespace) -> int:
    manifest = search_library(args)
    manifest_path = Path(args.manifest)
    previous = load_json(manifest_path) if manifest_path.exists() else None
    if not save_snapshot(manifest_path, previous, manifest):
        print("Partial search saved separately; previous full manifest retained", file=sys.stderr)
        return 2
    if args.csv:
        write_csv(manifest, Path(args.csv))
    if previous:
        diff = compare_manifests(previous, manifest)
        diff_path = manifest_path.with_name(manifest_path.stem + "_diff.json")
        diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"Manifest updated: {diff['added_count']} added, "
            f"{diff['removed_count']} removed, {diff['changed_count']} changed"
        )
    download_args = argparse.Namespace(
        manifest=str(manifest_path),
        dir=args.dir,
        state=args.state,
        limit=args.limit,
        direct_only=args.direct_only,
        force=args.force,
        revalidate=args.revalidate,
    )
    return command_download(download_args)


def add_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keyword", "-k", default="", help="Search keyword, for example prosafe-rs.")
    parser.add_argument("--region-id", type=int, default=DEFAULT_REGION_ID, help="Yokogawa region ID; 1 is Global.")
    parser.add_argument("--sort", default="r", choices=["r", "d"], help="Sort mode: r=relevance, d=site default/date.")
    parser.add_argument("--relevancy", default="", help="Optional relevancy threshold, e.g. .25.")
    parser.add_argument("--types", default="", help="Comma-separated resource type category IDs for API parameter t.")
    parser.add_argument("--products", default="", help="Comma-separated product category IDs for API parameter p.")
    parser.add_argument("--industries", default="", help="Comma-separated industry category IDs for API parameter i.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="API page size.")
    parser.add_argument("--max-results", type=int, default=0, help="Stop after this many results; 0 means all.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search and write a full manifest.")
    add_search_args(search)
    search.add_argument("--out", required=True, help="Output manifest JSON path.")
    search.add_argument("--csv", default="", help="Optional CSV summary path.")
    search.set_defaults(func=command_search)

    download = subparsers.add_parser("download", help="Archive accessible items from a manifest incrementally.")
    download.add_argument("--manifest", required=True, help="Input manifest JSON path.")
    download.add_argument("--dir", required=True, help="Download directory.")
    download.add_argument("--state", default="", help="Optional download state JSON path.")
    download.add_argument("--limit", type=int, default=0, help="Download at most N new accessible items in this run.")
    download_mode = download.add_mutually_exclusive_group()
    download_mode.add_argument("--direct-only", dest="direct_only", action="store_true", default=True, help="Download direct files only (default).")
    download_mode.add_argument("--include-detail-pages", dest="direct_only", action="store_false", help="Also try public detail-page HTML; may be blocked by WAF.")
    download.add_argument("--force", action="store_true", help="Redownload files even if state says they exist.")
    download.add_argument("--revalidate", action="store_true", help="Check existing URLs using HTTP validators or content SHA-256.")
    download.set_defaults(func=command_download)

    compare = subparsers.add_parser("compare", help="Compare old and new manifests.")
    compare.add_argument("--old", required=True, help="Previous manifest JSON path.")
    compare.add_argument("--new", required=True, help="New manifest JSON path.")
    compare.add_argument("--out", default="", help="Optional diff JSON path.")
    compare.set_defaults(func=command_compare)

    sync = subparsers.add_parser("sync", help="Search, save manifest, compare previous, and download incrementally.")
    add_search_args(sync)
    sync.add_argument("--manifest", required=True, help="Manifest JSON path to create/update.")
    sync.add_argument("--csv", default="", help="Optional CSV summary path.")
    sync.add_argument("--dir", required=True, help="Download directory.")
    sync.add_argument("--state", default="", help="Optional download state JSON path.")
    sync.add_argument("--limit", type=int, default=0, help="Download at most N new accessible items in this run.")
    sync_mode = sync.add_mutually_exclusive_group()
    sync_mode.add_argument("--direct-only", dest="direct_only", action="store_true", default=True, help="Download direct files only (default).")
    sync_mode.add_argument("--include-detail-pages", dest="direct_only", action="store_false", help="Also try public detail-page HTML; may be blocked by WAF.")
    sync.add_argument("--force", action="store_true", help="Redownload files even if state says they exist.")
    sync.add_argument("--revalidate", action="store_true", help="Check existing URLs for silent content replacement.")
    sync.set_defaults(func=command_sync)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - command line entry point.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
