#!/usr/bin/env python3
"""Search, compare, and incrementally download Schneider Electric Download Center materials."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from library_common import atomic_json, configure_console, download_validated, fingerprint, open_url, save_snapshot, valid_record


DEFAULT_SITE_BASE = "https://www.schneider-electric.cn"
DEFAULT_COUNTRY = "cn"
DEFAULT_LANGUAGE = "zh"
DEFAULT_APP_SOURCE = "DDC_SE"
DEFAULT_VIEW = "list"
DEFAULT_VIEW_PORT = "desktop"
DEFAULT_PAGE_SIZE = 40
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36"
)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def absolute_url(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    return urllib.parse.urljoin(DEFAULT_SITE_BASE, value)


def request_json(url: str, params: dict[str, str], retries: int = 3) -> dict[str, Any]:
    encoded_url = url + "?" + urllib.parse.urlencode(params)
    payload = json.dumps({"accessToken": "", "classLevel1": "", "classLevel2": ""}).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN",
        "Content-Type": "application/json",
        "Referer": f"{DEFAULT_SITE_BASE}/",
        "User-Agent": USER_AGENT,
        "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(encoded_url, data=payload, method="POST", headers=headers)
        try:
            with open_url(req, timeout=60) as response:
                content_type = response.headers.get("content-type", "")
                content_encoding = response.headers.get("content-encoding", "")
                body = response.read()
            if "gzip" in content_encoding.lower():
                body = gzip.decompress(body)
            if "json" not in content_type.lower():
                snippet = body[:160].decode("utf-8", errors="replace")
                raise RuntimeError(f"Expected JSON, got {content_type}: {snippet}")
            return json.loads(body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404, 567):
                break
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch Schneider JSON from {encoded_url}: {last_error}") from last_error


def base_api(args: argparse.Namespace) -> str:
    return f"{args.site_base.rstrip('/')}/{args.language}/download/download-api"


def build_params(args: argparse.Namespace, page_number: int, items_per_page: int | str) -> dict[str, str]:
    return {
        "appSource": args.app_source,
        "view": args.view,
        "docTypeGroup": args.doc_type_group,
        "docType": args.doc_type,
        "category": args.category,
        "subCategory": args.sub_category,
        "range": args.range,
        "language": args.doc_language,
        "contentType": args.content_type,
        "operatingSystem": args.operating_system,
        "perimeter": args.perimeter,
        "conformityInformation": args.conformity_information,
        "certificationCountry": args.certification_country,
        "approvalOffice": args.approval_office,
        "content": args.content,
        "businessType": args.business_type,
        "domain": args.domain,
        "support_level": args.support_level,
        "System_Version": args.system_version,
        "segment": args.segment,
        "sortByField": args.sort_by,
        "itemsPerPage": str(items_per_page),
        "pageNumber": str(page_number),
        "viewPort": args.view_port,
    }


def file_key(item: dict[str, Any], file_info: dict[str, Any]) -> str:
    for field in ("download_url", "url"):
        value = file_info.get(field)
        if value:
            return str(value)
    return f"{item.get('reference','')}::{file_info.get('filename','')}"


def normalize_file(raw: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    url = absolute_url(raw.get("downloadFileURL") or raw.get("downloadUrl") or raw.get("url") or "")
    filename = clean_text(raw.get("filename") or raw.get("fileName") or item.get("filename") or "")
    extension = clean_text(raw.get("extension") or item.get("extension") or "").lstrip(".")
    if not filename and url:
        filename = Path(urllib.parse.urlparse(url).path).name
    return {
        "id": raw.get("id") or "",
        "filename": filename,
        "extension": extension,
        "size": clean_text(raw.get("size") or item.get("size")),
        "download_url": url,
        "disable_download": bool(raw.get("disableDownload", item.get("disableDownload", False))),
        "checksum": clean_text(raw.get("checkSum") or raw.get("checksum")),
        "audience": clean_text((raw.get("audience") or {}).get("label") if isinstance(raw.get("audience"), dict) else raw.get("audience")),
    }


def normalize_document(raw: dict[str, Any]) -> dict[str, Any]:
    item = {
        "reference": clean_text(raw.get("reference")),
        "title": clean_text(raw.get("title")),
        "document_date": clean_text(raw.get("documentDate")),
        "last_modified": clean_text(raw.get("lastModificationDate")),
        "version": clean_text(raw.get("version")),
        "revision": clean_text(raw.get("revision")),
        "locales": clean_text(raw.get("locales")),
        "display_language": clean_text(raw.get("displayLanguage")),
        "extension": clean_text(raw.get("extension")).lstrip("."),
        "size": clean_text(raw.get("size")),
        "en_doc_type": clean_text(raw.get("enDocType")),
        "document_type": clean_text(raw.get("documentTypeDisplayLabel")),
        "description": clean_text(raw.get("description") or raw.get("shortDescription")),
        "image_url": absolute_url(raw.get("imageUrl")),
        "banner_url": absolute_url(raw.get("bannerUrl")),
        "download_url": absolute_url(raw.get("downloadUrl")),
        "filename": clean_text(raw.get("filename") or raw.get("fileName")),
        "disable_download": bool(raw.get("disableDownload", False)),
        "private": bool(raw.get("private", False)),
        "online": bool(raw.get("online", False)),
        "online_cad": bool(raw.get("onlineCad", False)),
        "has_previous_version": bool(raw.get("hasPreviousVersion", False)),
        "has_translations": bool(raw.get("hasTranslations", False)),
        "number_of_doc": raw.get("numberOfDoc"),
        "product_references": raw.get("productReferences") or [],
        "doc_type_groups": raw.get("docTypeGroups") or [],
        "ranges": raw.get("ranges") or [],
        "categories": raw.get("categories") or [],
        "raw": raw,
    }
    files = []
    if item["download_url"]:
        files.append(normalize_file({"downloadUrl": item["download_url"], "filename": item["filename"], "extension": item["extension"], "size": item["size"]}, item))
    for raw_file in raw.get("documentFiles") or []:
        files.append(normalize_file(raw_file, item))
    deduped: dict[str, dict[str, Any]] = {}
    for file_info in files:
        key = file_key(item, file_info)
        if key and key not in deduped:
            deduped[key] = file_info
    item["files"] = list(deduped.values())
    identity = "::".join(part for part in (item["reference"], item["locales"]) if part)
    item["key"] = identity or hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return item


def search_library(args: argparse.Namespace) -> dict[str, Any]:
    keyword_path = urllib.parse.quote(args.keyword, safe="")
    url = f"{base_api(args)}/keyword/{keyword_path}/"
    page = 1
    total = None
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    effective_page_size: int | str = ""
    repeated_page = False

    while True:
        data = request_json(url, build_params(args, page, effective_page_size))
        if total is None:
            total = int(data.get("documentsCount") or 0)
        criteria = data.get("criteria") or {}
        page_size = int(criteria.get("itemsPerPage") or DEFAULT_PAGE_SIZE)
        effective_page_size = page_size
        docs = data.get("documents") or []
        if not docs:
            break
        before_count = len(items)
        for raw_doc in docs:
            item = normalize_document(raw_doc)
            if item["key"] not in seen:
                seen.add(item["key"])
                items.append(item)
        print(f"Fetched page {page}: {len(items)} of {total}", file=sys.stderr)
        if len(items) == before_count:
            repeated_page = True
            break
        if args.max_results and len(items) >= args.max_results:
            items = items[: args.max_results]
            break
        if total is not None and len(items) >= total:
            break
        if page >= int(data.get("pagination", {}).get("totalPages") or 10_000):
            break
        page += 1

    manifest = {
        "generated_at": now_iso(),
        "source": "Schneider Electric China Download Center",
        "site_url": f"{args.site_base.rstrip('/')}/{args.language}/download/",
        "api_url": url,
        "query": {
            "keyword": args.keyword,
            "country": args.country,
            "language": args.language,
            "app_source": args.app_source,
            "sort_by": args.sort_by,
        },
        "total_reported": total,
        "count": len(items),
        "search_complete": not repeated_page and total is not None and len(items) >= total,
        "search_warning": "Partial/unstable search; no removal conclusions" if repeated_page or total is None or len(items) < total else "",
        "download_file_count": sum(len([f for f in item["files"] if f.get("download_url") and not f.get("disable_download")]) for item in items),
        "items": items,
    }
    return manifest


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    atomic_json(path, manifest)


def write_csv(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "reference",
        "title",
        "document_date",
        "version",
        "locales",
        "extension",
        "size",
        "en_doc_type",
        "document_type",
        "download_url",
        "file_count",
        "disable_download",
        "private",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in manifest.get("items", []):
            writer.writerow({field: item.get(field, "") for field in fields[:-1]} | {"file_count": len(item.get("files", [])), "private": item.get("private", False)})


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def item_key(item: dict[str, Any]) -> str:
    return str(item.get("key") or item.get("reference") or hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest())


def compare_manifests(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_items = {item_key(item): item for item in old.get("items", [])}
    new_items = {item_key(item): item for item in new.get("items", [])}
    added_keys = sorted(set(new_items) - set(old_items))
    removed_keys = sorted(set(old_items) - set(new_items))
    fields = ["title", "document_date", "last_modified", "version", "revision", "locales", "extension", "size", "download_url", "document_type", "files"]
    changed = []
    for key in sorted(set(old_items) & set(new_items)):
        before = old_items[key]
        after = new_items[key]
        changes = {}
        for field in fields:
            old_value, new_value = before.get(field), after.get(field)
            if field == "files":
                old_value = sorted(old_value or [], key=lambda f: f.get("download_url", ""))
                new_value = sorted(new_value or [], key=lambda f: f.get("download_url", ""))
            if old_value != new_value:
                changes[field] = {"old": old_value, "new": new_value}
        if changes:
            changed.append({"key": key, "reference": after.get("reference"), "title": after.get("title"), "changes": changes})
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


def sanitize_filename(value: str, max_len: int = 150) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or "schneider_file")[:max_len].strip(" .")


def extension_for(url: str, filename: str, extension: str) -> str:
    for candidate in (Path(filename).suffix, Path(urllib.parse.urlparse(url).path).suffix, "." + extension.lstrip(".")):
        if candidate and candidate != ".":
            return candidate.lower()
    guessed = mimetypes.guess_extension(mimetypes.guess_type(url)[0] or "") or ""
    return guessed


def filename_for(item: dict[str, Any], file_info: dict[str, Any]) -> str:
    url = file_info.get("download_url", "")
    ext = extension_for(url, file_info.get("filename", ""), file_info.get("extension", ""))
    doc_type = re.sub(r"^\d+-", "", clean_text(item.get("document_type") or item.get("en_doc_type") or "Document"))
    version = clean_text(item.get("version"))
    if version and re.fullmatch(r"[\d.]+", version):
        version = "v" + version
    stem_parts = [doc_type, item.get("reference", ""), item.get("title", ""), version]
    if len(item.get("files", [])) > 1 and file_info.get("filename"):
        stem_parts.append(Path(file_info["filename"]).stem)
    fixed_length = sum(len(clean_text(part)) for index, part in enumerate(stem_parts) if index != 2)
    stem_parts[2] = clean_text(stem_parts[2])[:max(16, 150 - fixed_length - 3 * (len(stem_parts) - 1))]
    stem = sanitize_filename(" - ".join(clean_text(part) for part in stem_parts if clean_text(part)))
    if ext and not stem.lower().endswith(ext):
        stem += ext
    return stem


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        return load_json(path)
    return {"updated_at": None, "files": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    atomic_json(path, state)


def download_one(url: str, dest: Path) -> tuple[int, str]:
    result = download_validated(url, dest, {"User-Agent": USER_AGENT, "Referer": DEFAULT_SITE_BASE})
    return result["bytes"], result["sha256"]


def iter_eligible_files(manifest: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    eligible = []
    for item in manifest.get("items", []):
        if item.get("private") or item.get("disable_download"):
            continue
        for file_info in item.get("files", []):
            if file_info.get("download_url") and not file_info.get("disable_download"):
                eligible.append((item, file_info))
    return eligible


def command_search(args: argparse.Namespace) -> int:
    manifest = search_library(args)
    write_manifest(manifest, Path(args.out))
    if args.csv:
        write_csv(manifest, Path(args.csv))
    print(f"Saved {manifest['count']} results ({manifest['download_file_count']} downloadable files) to {args.out}")
    return 0


def command_download(args: argparse.Namespace) -> int:
    manifest = load_json(Path(args.manifest))
    download_dir = Path(args.dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    state_path = Path(args.state) if args.state else download_dir / ".schneider_download_state.json"
    state = load_state(state_path)
    files_state = state.setdefault("files", {})
    errors = state.setdefault("errors", {})
    downloaded = skipped = failed = 0
    eligible = iter_eligible_files(manifest)
    for item, file_info in eligible:
        url = file_info["download_url"]
        key = hashlib.sha256(f"{item_key(item)}::{file_key(item, file_info)}".encode("utf-8")).hexdigest()
        dest = download_dir / filename_for(item, file_info)
        existing = files_state.get(key)
        item_fingerprint = fingerprint(item, file_info)
        current = valid_record(existing, url, item_fingerprint)
        if not args.force and current and not getattr(args, "revalidate", False):
            skipped += 1
            continue
        if args.limit and downloaded >= args.limit:
            continue
        if dest.exists():
            suffix = key[:10]
            candidate = dest.with_name(f"{dest.stem} [{suffix}]{dest.suffix}")
            counter = 2
            while candidate.exists():
                candidate = dest.with_name(f"{dest.stem} [{suffix}-{counter}]{dest.suffix}")
                counter += 1
            dest = candidate
        try:
            print(f"Downloading: {dest.name}", file=sys.stderr)
            result = download_validated(url, dest, {"User-Agent": USER_AGENT, "Referer": manifest.get("site_url") or DEFAULT_SITE_BASE},
                                        existing if current and not args.force else None)
            if existing and not result["unchanged"] and existing.get("path") != result["path"]:
                state.setdefault("history", []).append(existing)
            files_state[key] = {
                **result,
                "status": "completed",
                "key": item_key(item),
                "fingerprint": item_fingerprint,
                "url": url,
                "downloaded_at": existing.get("downloaded_at") if result["unchanged"] and existing else now_iso(),
                "checked_at": now_iso(),
                "reference": item.get("reference", ""),
                "title": item.get("title", ""),
                "document_type": item.get("document_type") or item.get("en_doc_type") or "Document",
                "version": item.get("version", ""),
                "source_url": item.get("source_url") or url,
                "source_tier": item.get("source_tier", "official"),
                "metadata_verified": item.get("metadata_verified", False),
                "language": item.get("document_language") or item.get("display_language", ""),
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
                "skipped": skipped, "failed": failed, "eligible": len(eligible), "errors": errors})
    print(f"Download complete: {downloaded} downloaded, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


def command_compare(args: argparse.Namespace) -> int:
    diff = compare_manifests(load_json(Path(args.old)), load_json(Path(args.new)))
    if args.out:
        Path(args.out).write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Compare complete: {diff['added_count']} added, {diff['removed_count']} removed, {diff['changed_count']} changed")
    return 0


def command_sync(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    previous = load_json(manifest_path) if manifest_path.exists() else None
    manifest = search_library(args)
    if not save_snapshot(manifest_path, previous, manifest):
        print("Partial search saved separately; previous full manifest retained", file=sys.stderr)
        return 2
    if args.csv:
        write_csv(manifest, Path(args.csv))
    if previous:
        diff = compare_manifests(previous, manifest)
        diff_path = manifest_path.with_name(manifest_path.stem + "_diff.json")
        diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Manifest updated: {diff['added_count']} added, {diff['removed_count']} removed, {diff['changed_count']} changed")
    download_args = argparse.Namespace(manifest=str(manifest_path), dir=args.dir, state=args.state, limit=args.limit, force=args.force, revalidate=args.revalidate)
    return command_download(download_args)


def add_search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keyword", "-k", required=True, help="Search keyword, for example M580 or Modicon M580.")
    parser.add_argument("--site-base", default=DEFAULT_SITE_BASE, help="Site base URL.")
    parser.add_argument("--country", default=DEFAULT_COUNTRY, help="Country code; default cn.")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, help="Language path/code; default zh.")
    parser.add_argument("--app-source", default=DEFAULT_APP_SOURCE, help="Schneider app source; default DDC_SE.")
    parser.add_argument("--view", default=DEFAULT_VIEW, help="Result view; default list.")
    parser.add_argument("--view-port", default=DEFAULT_VIEW_PORT, help="View port flag used by the API.")
    parser.add_argument("--sort-by", default="", help="Sort field, e.g. Relevance, Popularity, Document_Date_New.")
    parser.add_argument("--doc-type-group", default="", help="Document type group filter ID.")
    parser.add_argument("--doc-type", default="", help="Document type filter ID.")
    parser.add_argument("--category", default="", help="Product category filter ID.")
    parser.add_argument("--sub-category", default="", help="Product sub-category filter ID.")
    parser.add_argument("--range", default="", help="Product range filter ID.")
    parser.add_argument("--doc-language", default="", help="Document language filter ID/name.")
    parser.add_argument("--content-type", default="", help="Content type filter.")
    parser.add_argument("--operating-system", default="", help="Operating system filter.")
    parser.add_argument("--perimeter", default="", help="Perimeter filter.")
    parser.add_argument("--conformity-information", default="", help="Conformity information filter.")
    parser.add_argument("--certification-country", default="", help="Certification country filter.")
    parser.add_argument("--approval-office", default="", help="Approval office filter.")
    parser.add_argument("--content", default="", help="Content/subtype filter.")
    parser.add_argument("--business-type", default="", help="Business type filter.")
    parser.add_argument("--domain", default="", help="Domain filter.")
    parser.add_argument("--support-level", default="", help="Support level filter.")
    parser.add_argument("--system-version", default="", help="System version filter.")
    parser.add_argument("--segment", default="", help="Segment filter.")
    parser.add_argument("--max-results", type=int, default=0, help="Stop after this many unique results; 0 means all.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search and write a manifest.")
    add_search_args(search)
    search.add_argument("--out", required=True, help="Output manifest JSON path.")
    search.add_argument("--csv", default="", help="Optional CSV summary path.")
    search.set_defaults(func=command_search)

    download = subparsers.add_parser("download", help="Download files from a manifest incrementally.")
    download.add_argument("--manifest", required=True, help="Input manifest JSON path.")
    download.add_argument("--dir", required=True, help="Download directory.")
    download.add_argument("--state", default="", help="Optional state JSON path.")
    download.add_argument("--limit", type=int, default=0, help="Download at most N new files; completed files do not consume the limit.")
    download.add_argument("--revalidate", action="store_true", help="Check existing URLs using HTTP validators or content SHA-256.")
    download.add_argument("--force", action="store_true", help="Redownload files even if state says they exist.")
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
    sync.add_argument("--state", default="", help="Optional state JSON path.")
    sync.add_argument("--limit", type=int, default=0, help="Download at most N new files; completed files do not consume the limit.")
    sync.add_argument("--revalidate", action="store_true", help="Check existing URLs for silent content replacement.")
    sync.add_argument("--force", action="store_true", help="Redownload files even if state says they exist.")
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
