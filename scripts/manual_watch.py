#!/usr/bin/env python3
"""Multi-keyword official-library and web-search manual collection."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from library_common import atomic_json, certificate_status, configure_console, network_status, open_url, valid_record
from source_discovery import discover, normalize_download_url, pdf_link


_skill_text = (Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8")
VENDOR = "yokogawa" if re.search(r"(?m)^name:\s*yokogawa-library\s*$", _skill_text) else "schneider"
LIBRARY = importlib.import_module("yokogawa_library" if VENDOR == "yokogawa" else "schneider_download_library")
OFFICIAL_DOMAINS = ["yokogawa.com", "yokocms.com"] if VENDOR == "yokogawa" else ["se.com", "schneider-electric.cn", "schneider-electric.com"]
SOURCE_MODE = "official_api"
HOMEPAGE = "https://www.yokogawa.com/library/" if VENDOR == "yokogawa" else "https://www.se.com/ww/en/download/"
SEARCH_DOMAINS = OFFICIAL_DOMAINS


def configure_brand(brand: str) -> None:
    global VENDOR, LIBRARY, OFFICIAL_DOMAINS, SOURCE_MODE, HOMEPAGE, SEARCH_DOMAINS
    path = Path(__file__).resolve().parent.parent / "references" / "brand-profiles.json"
    profiles = read_json(path)
    if brand not in profiles:
        raise ValueError(f"Unknown brand: {brand}; choose {', '.join(sorted(profiles))}")
    profile = profiles[brand]
    VENDOR, OFFICIAL_DOMAINS = brand, profile["official_domains"]
    SEARCH_DOMAINS = profile.get("search_domains", OFFICIAL_DOMAINS)
    SOURCE_MODE, HOMEPAGE = profile["source_mode"], profile["homepage"]
    if SOURCE_MODE == "official_api":
        LIBRARY = importlib.import_module(profile["module"])
    else:
        from web_library import WebLibrary
        LIBRARY = WebLibrary(brand)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_config(path: Path) -> dict:
    config = read_json(path)
    if not config.get("products"):
        raise ValueError("Config needs a nonempty products list")
    ids = set()
    for product in config["products"]:
        identity = product.get("id", "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", identity) or identity in ids:
            raise ValueError("Product IDs must be unique safe directory names")
        if not product.get("keywords") or not all(isinstance(k, str) and k.strip() for k in product["keywords"]):
            raise ValueError("Each product needs nonempty keyword strings")
        for field in ("seed_pages", "document_numbers", "extra_queries"):
            if not isinstance(product.get(field, []), list) or not all(isinstance(x, str) and x.strip() for x in product.get(field, [])):
                raise ValueError(f"{field} must be a list of nonempty strings")
        ids.add(identity)
    return config


def query_plan(config: dict) -> list[dict]:
    queries = []
    sites = "(" + " OR ".join("site:" + domain for domain in SEARCH_DOMAINS) + ")"
    for product in config["products"]:
        for keyword in product["keywords"]:
            for query in (f'"{keyword}" {sites} (manual OR guide OR specification)',
                          f'"{keyword}" filetype:pdf (manual OR guide OR specification)',
                          f'"{keyword}" (手册 OR 用户指南 OR 安全手册)'):
                queries.append({"product": product["id"], "query": query})
        for query in product.get("extra_queries", []):
            queries.append({"product": product["id"], "query": query})
        for number in product.get("document_numbers", []):
            queries.append({"product": product["id"], "query": f'"{number}" {sites}'})
    unique = {(q["product"], q["query"]): q for q in queries}
    return list(unique.values())


def tavily_search(plan: list[dict], max_results: int) -> dict:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise ValueError("TAVILY_API_KEY is not set; use --web-results from any search tool instead")
    output = {"generated_at": now(), "provider": "tavily", "executed_queries": [], "results": [], "errors": []}
    for entry in plan:
        request = urllib.request.Request("https://api.tavily.com/search", method="POST",
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            data=json.dumps({"query": entry["query"], "max_results": max_results,
                             "search_depth": "basic", "include_answer": False}).encode("utf-8"))
        try:
            with open_url(request, timeout=60) as response:
                data = json.loads(response.read())
            output["executed_queries"].append({**entry, "searched_at": now()})
            for result in data.get("results", []):
                output["results"].append({**result, **entry})
        except Exception as exc:
            output["errors"].append({**entry, "error": str(exc)})
    return output


def canonical_url(url: str) -> str:
    url = normalize_download_url(url)
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username:
        raise ValueError("Search result needs a public HTTP(S) URL")
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")]
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                                   urllib.parse.urlencode(query), ""))


def is_official(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in OFFICIAL_DOMAINS)


def native_web_item(result: dict, product: dict) -> tuple[dict | None, dict]:
    url = canonical_url(result["url"])
    download_url = canonical_url(result.get("download_url") or url)
    direct = (pdf_link(download_url) or
              bool(result.get("download_url") and result.get("file_ext") == "pdf" and result.get("verified") is True))
    text = " ".join(str(result.get(field) or "") for field in ("title", "content", "url"))
    folded = re.sub(r"[^\w]", "", text).casefold()
    relevant = any(re.sub(r"[^\w]", "", keyword).casefold() in folded
                   for keyword in [*product["keywords"], *product.get("document_numbers", [])])
    verified = result.get("verified") is True
    restricted = bool(result.get("login_required") or result.get("agreement_required"))
    official = is_official(download_url)
    accepted = (relevant or verified) and direct and not restricted and (official or verified)
    evidence = {**result, "url": url, "download_url": download_url,
                "source_tier": "official" if official else "third_party",
                "discovered_at": now(), "status": "download_candidate" if accepted else
                "restricted" if restricted else "needs_review" if relevant or verified else "excluded_irrelevant"}
    if not accepted:
        return None, evidence
    key = "web-" + hashlib.sha256(download_url.encode("utf-8")).hexdigest()[:20]
    title = str(result.get("title") or Path(urllib.parse.urlsplit(url).path).name)
    version = str(result.get("version", ""))
    doc_type = str(result.get("document_type") or "Document")
    reference = str(result.get("document_number") or "")
    common = {"key": key, "source_url": url, "source_tier": evidence["source_tier"],
              "source_query": result.get("query", ""), "metadata_verified": verified,
              "collected_product": product["id"]}
    common["document_language"] = result.get("document_language", "")
    if VENDOR == "yokogawa":
        item = {**common, "id": key, "name": title, "code": reference, "category": doc_type,
                "edition": version, "file_ext": "pdf", "direct_download_url": download_url,
                "detail_page_url": "", "locked": False, "software_agreement": False}
    else:
        filename = str(result.get("filename") or reference or key)
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        item = {**common, "reference": reference, "title": title, "document_type": doc_type,
                "version": version, "files": [{"download_url": download_url, "extension": "pdf",
                "filename": filename}], "private": False,
                "disable_download": False}
    return item, evidence


def item_urls(item: dict) -> set[str]:
    urls = [item.get("direct_download_url")] if VENDOR == "yokogawa" else [f.get("download_url") for f in item.get("files", [])]
    return {canonical_url(url) for url in urls if url}


def merge_web_metadata(previous: dict, incoming: dict) -> dict:
    merged = dict(previous)
    trusted_previous = previous.get("metadata_verified") or (
        previous.get("source_tier") == "official" and not previous["key"].startswith("web-"))
    if incoming.get("metadata_verified") or not trusted_previous:
        for field, value in incoming.items():
            if field not in ("id", "node_id", "key") and value not in (None, "", [], {}):
                if field == "files" and previous.get("files"):
                    files = {canonical_url(f["download_url"]): f for f in previous["files"]}
                    for file in value:
                        url = canonical_url(file["download_url"])
                        # A single web attachment must not replace a native multi-file document.
                        files.setdefault(url, file)
                    merged[field] = list(files.values())
                else:
                    merged[field] = value
    merged["key"] = previous["key"]
    return merged


def fresh_query(entry: dict, web: dict, max_age_hours: float) -> bool:
    try:
        value = entry["searched_at"] if "searched_at" in entry else web.get("generated_at", "")
        timestamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
        age = (dt.datetime.now(dt.timezone.utc) - timestamp).total_seconds() / 3600
        return 0 <= age <= max_age_hours
    except ValueError:
        return False


def export_catalog(path: Path, items: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["key", "title", "document_number", "document_type", "version", "source_tier", "first_seen", "last_seen", "seen_this_run", "url"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in items:
            writer.writerow({"key": item["key"], "title": item.get("name") or item.get("title"),
                "document_number": item.get("code") or item.get("reference"),
                "document_type": item.get("category") or item.get("document_type"),
                "version": item.get("edition") or item.get("version"),
                **{field: item.get(field, "") for field in ("source_tier", "first_seen", "last_seen", "seen_this_run")},
                "url": " | ".join(sorted(item_urls(item)))})


def download_candidates(items: list[dict], formats: list[str]) -> list[dict]:
    allowed = {"." + extension.lower().lstrip(".") for extension in formats}
    selected = []
    for item in items:
        if VENDOR == "yokogawa":
            url = item.get("direct_download_url", "")
            extension = "." + str(item.get("file_ext") or "").lstrip(".").lower()
            if url and (extension in allowed or Path(urllib.parse.urlsplit(url).path).suffix.lower() in allowed):
                selected.append(item)
        else:
            files = [file for file in item.get("files", []) if
                     ("." + str(file.get("extension") or "").lstrip(".").lower()) in allowed or
                     Path(str(file.get("filename") or "")).suffix.lower() in allowed or
                     Path(urllib.parse.urlsplit(file.get("download_url", "")).path).suffix.lower() in allowed]
            if files:
                selected.append({**item, "files": files})
    return selected


def export_rag(directory: Path, catalog: dict) -> int:
    state_path = directory / "downloads" / f".{VENDOR}_download_state.json"
    state = read_json(state_path) if state_path.exists() else {}
    items = {item["key"]: item for item in catalog["items"]}
    by_url = {url: item for item in catalog["items"] for url in item_urls(item)}
    hashes = {}
    rows = []
    records = [(record, "current") for record in state.get("files", {}).values()]
    records += [(record, "historical") for record in state.get("history", [])]
    for record, local_status in records:
        path = Path(record.get("path", ""))
        if not valid_record(record, record.get("url", "")):
            continue
        item = items.get(record.get("key")) or by_url.get(canonical_url(record["url"]), {})
        if local_status == "current" and str(record.get("version", "")) != str(item.get("edition") or item.get("version") or ""):
            local_status = "catalog_revision_pending"
        # Historical metadata belongs to that file, never today's catalog revision.
        fallback = item if local_status != "historical" else {}
        row = {"path": str(path), "sha256": record.get("sha256"), "bytes": record["bytes"],
               "source_url": record.get("source_url") or fallback.get("source_url") or record["url"], "download_url": record["url"],
               "product": directory.name, "vendor": VENDOR, "title": record.get("name") or record.get("title") or fallback.get("name") or fallback.get("title"),
               "document_number": record.get("code") or record.get("reference") or fallback.get("code") or fallback.get("reference"),
               "document_type": record.get("document_type") or fallback.get("category") or fallback.get("document_type"),
               "version": record.get("version", fallback.get("edition") or fallback.get("version")),
               "source_tier": record.get("source_tier", fallback.get("source_tier", "unknown")),
               "local_status": local_status, "latest_applicability": "not_established",
               "language": record.get("language", ""), "metadata_verified": record.get("metadata_verified", False),
               "checked_at": record.get("checked_at"), "final_url": record.get("final_url", record["url"]),
               "downloaded_at": record.get("downloaded_at")}
        sha256 = row["sha256"]
        if sha256 in hashes:
            row["duplicate_of"] = hashes[sha256]
        else:
            hashes[sha256] = str(path)
        rows.append(row)
    temporary = directory / "rag-index.jsonl.tmp"
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    temporary.replace(directory / "rag-index.jsonl")
    current = [row for row in rows if row["local_status"] == "current" and not row.get("duplicate_of")]
    temporary = directory / "rag-current.jsonl.tmp"
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in current), encoding="utf-8")
    temporary.replace(directory / "rag-current.jsonl")
    return len(rows)


def download_catalog(directory, catalog, product, args):
    candidates = download_candidates(catalog["items"], product.get("download_formats", ["pdf"]))
    manifest = directory / "download-manifest.json"
    atomic_json(manifest, {"generated_at": now(), "site_url": HOMEPAGE, "count": len(candidates), "items": candidates})
    flags = ["download", "--manifest", str(manifest), "--dir", str(directory / "downloads"), "--limit", str(args.limit)]
    if VENDOR == "yokogawa":
        flags.append("--direct-only")
    if args.revalidate:
        flags.append("--revalidate")
    started_at = now()
    code = 0 if args.search_only else LIBRARY.main(flags)
    summary = None
    if not args.search_only:
        path = directory / "downloads" / "download_report.json"
        if path.exists():
            value = read_json(path)
            if value.get("generated_at", "") >= started_at:
                summary = value
    return candidates, code, summary


def run_product(product: dict, root: Path, web: dict, args) -> dict:
    directory = root / product["id"]
    directory.mkdir(parents=True, exist_ok=True)
    stamp = now().replace(":", "-").replace("+", "_")
    run_dir = directory / "runs" / stamp
    run_dir.mkdir(parents=True)
    catalog_path = directory / "catalog.json"
    old = read_json(catalog_path) if catalog_path.exists() else {"items": []}
    if old.get("vendor", VENDOR) != VENDOR:
        raise ValueError("Existing product catalog belongs to a different brand; use a separate root or product ID")
    if old.get("scope") and old["scope"].get("library_args", []) != product.get("library_args", []):
        raise ValueError("Official locale/filter scope changed; use a new product ID")
    if getattr(args, "command", "run") == "resume":
        if not catalog_path.exists():
            raise ValueError("No saved catalog; run collection once before resume")
        candidates, code, summary = download_catalog(directory, old, old.get("scope", product), args)
        report = {"generated_at": now(), "mode": "resume", "vendor": VENDOR, "product": product["id"],
                  "ok": code == 0, "catalog_count": len(old["items"]), "download_summary": summary,
                  "discovery_performed": False, "catalog_generated_at": old.get("generated_at"),
                  "test_limited": bool(args.limit), "rag_file_count": export_rag(directory, old)}
        atomic_json(run_dir / "report.json", report)
        atomic_json(directory / "latest-resume-report.json", report)
        return report
    registry = {item["key"]: dict(item, seen_this_run=False) for item in old["items"]}
    observed = {}
    sources = []
    endpoint_denied = None
    for keyword in product["keywords"] if SOURCE_MODE == "official_api" else []:
        if endpoint_denied:
            sources.append({"keyword": keyword, "ok": False, "complete": False,
                            "status": "not_attempted_endpoint_denied", "http_status": endpoint_denied})
            continue
        search_flags = list(product.get("library_args", []))
        try:
            native_args = LIBRARY.build_parser().parse_args(["search", "--keyword", keyword, "--out", "unused", *search_flags,
                                                           "--max-results", str(args.max_results)])
            manifest = LIBRARY.search_library(native_args)
            atomic_json(run_dir / (hashlib.sha256(keyword.encode()).hexdigest()[:10] + ".json"), manifest)
            sources.append({"keyword": keyword, "ok": True, "complete": manifest.get("search_complete"),
                            "count": manifest["count"], "reported": manifest.get("total_reported")})
            for item in manifest["items"]:
                observed[item["key"]] = {**item, "source_tier": "official", "collected_product": product["id"]}
        except (Exception, SystemExit) as exc:
            sources.append({"keyword": keyword, "ok": False, "complete": False, "error": str(exc)})
            cause = exc
            while cause is not None:
                if isinstance(cause, urllib.error.HTTPError) and cause.code in (401, 403, 567):
                    endpoint_denied = cause.code
                    sources[-1]["http_status"] = cause.code
                    break
                cause = cause.__cause__
    known_urls = {url: item["key"] for item in [*registry.values(), *observed.values()] for url in item_urls(item)}
    evidence = []
    discovery = discover(product, OFFICIAL_DOMAINS, getattr(args, "seed_page_budget", 12)) if product.get("seed_pages") else None
    if discovery is not None:
        atomic_json(run_dir / "seed-discovery.json", discovery)
    for result in [*web.get("results", []), *(discovery or {}).get("results", [])]:
        if result.get("product") != product["id"]:
            continue
        try:
            item, record = native_web_item(result, product)
            evidence.append(record)
            if item:
                matched = [known_urls[url] for url in item_urls(item) if url in known_urls]
                if matched:
                    known_key = matched[0]
                    if known_key not in observed:
                        observed[known_key] = merge_web_metadata(registry[known_key], item)
                    elif observed[known_key].get("metadata_verified") is not None:
                        observed[known_key] = merge_web_metadata(observed[known_key], item)
                    record["duplicate_of"] = known_key
                else:
                    observed[item["key"]] = item
                    for url in item_urls(item):
                        known_urls[url] = item["key"]
        except (ValueError, KeyError) as exc:
            evidence.append({**result, "status": "invalid", "error": str(exc)})
    for key, item in observed.items():
        registry[key] = {**item, "first_seen": registry.get(key, {}).get("first_seen", stamp),
                         "last_seen": stamp, "seen_this_run": True}
    catalog = {"generated_at": now(), "vendor": VENDOR, "product": product["id"],
               "scope": product, "count": len(registry), "items": list(registry.values())}
    atomic_json(run_dir / "previous-catalog.json", old)
    atomic_json(catalog_path, catalog)
    atomic_json(run_dir / "web-evidence.json", {"results": evidence, "executed_queries": web.get("executed_queries", [])})
    export_catalog(directory / "catalog.csv", catalog["items"])
    candidates, exit_code, download_summary = download_catalog(directory, catalog, product, args)
    old_items = {item["key"]: item for item in old["items"]}
    changed = [key for key, item in observed.items() if key in old_items and
               any(old_items[key].get(field) != item.get(field) for field in
                   ("name", "title", "edition", "version", "updated_at", "last_modified", "files", "direct_download_url"))]
    planned = {(entry["product"], entry["query"]) for entry in query_plan({"products": [product]})}
    executed = {(entry["product"], entry["query"]) for entry in web.get("executed_queries", [])}
    fresh = {(entry["product"], entry["query"]) for entry in web.get("executed_queries", [])
             if fresh_query(entry, web, getattr(args, "web_max_age_hours", 24))}
    web_errors = [entry for entry in web.get("errors", []) if entry.get("product") == product["id"]]
    try:
        web_time = dt.datetime.fromisoformat(str(web.get("generated_at", "")).replace("Z", "+00:00"))
        if web_time.tzinfo is None:
            web_time = web_time.replace(tzinfo=dt.timezone.utc)
        age_hours = (dt.datetime.now(dt.timezone.utc) - web_time).total_seconds() / 3600
        web_fresh = planned <= fresh
    except ValueError:
        age_hours, web_fresh = None, planned <= fresh
    report = {"generated_at": now(), "product": product["id"], "official_sources": sources,
              "vendor": VENDOR, "source_mode": SOURCE_MODE,
              "official_enumeration": ("complete" if all(source["ok"] and source["complete"] for source in sources)
                                        else "partial_or_failed") if SOURCE_MODE == "official_api" else "not_implemented",
              "network_mode": network_status(),
              "seed_discovery": discovery,
              "tls_trust_store": certificate_status(),
              "scope_changed": bool(old.get("scope") and old["scope"] != product),
              "web_queries_planned": len(planned), "web_queries_executed": len(planned & executed),
              "web_queries_fresh": len(planned & fresh),
              "web_errors": web_errors, "web_coverage": "planned_queries_executed" if planned <= executed and not web_errors else "partial_or_not_run",
              "web_results_generated_at": web.get("generated_at"), "web_results_age_hours": age_hours,
              "web_results_fresh": web_fresh,
              "coverage_note": "Search engines are bounded and do not prove entire-web completeness.",
              "catalog_count": len(registry), "added": sorted(set(observed) - set(old_items)), "changed": changed,
              "download_candidate_items": len(candidates),
              "download_summary": download_summary,
              "not_observed": sorted(set(old_items) - set(observed)),
              "needs_review": len({record.get("url") for record in evidence if record["status"] == "needs_review"}),
              "restricted": len({record.get("url") for record in evidence if record["status"] == "restricted"}),
              "test_limited": bool(args.limit or args.max_results),
              "download_exit_code": exit_code, "rag_file_count": export_rag(directory, catalog)}
    report["ok"] = all(source["ok"] and source["complete"] for source in sources) and planned <= executed and web_fresh and not web_errors and exit_code == 0
    if discovery is not None and not discovery["complete"]:
        report["ok"] = False
    atomic_json(run_dir / "report.json", report)
    atomic_json(directory / "latest-report.json", report)
    return report


def main(argv=None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "resume", "discover"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--brand", default=VENDOR, help="yokogawa, schneider, honeywell or siemens; see brand-profiles.json")
    parser.add_argument("--root", default="manual-library")
    parser.add_argument("--out", default="web-query-plan.json")
    parser.add_argument("--web-results", default="", help="JSON from any search tool; see references/manual-watch.md")
    parser.add_argument("--web-provider", choices=["none", "tavily"], default="none")
    parser.add_argument("--web-max-results", type=int, choices=range(1, 21), default=10)
    parser.add_argument("--web-max-age-hours", type=float, default=24, help="Older imported searches are marked stale, but can still resume downloads")
    parser.add_argument("--max-results", type=int, default=0, help="Official API result cap; testing only")
    parser.add_argument("--limit", type=int, default=0, help="New files per product; 0 downloads all")
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--revalidate", action="store_true")
    parser.add_argument("--seed-page-budget", type=int, default=12, help="Max official HTML pages per product, depth 1; reports unvisited links")
    args = parser.parse_args(argv)
    try:
        configure_brand(args.brand)
        if args.max_results < 0 or args.limit < 0 or args.web_max_age_hours < 0:
            raise ValueError("Limits cannot be negative")
        if args.seed_page_budget < 1:
            raise ValueError("Seed page budget must be positive")
        if args.command == "resume" and (args.web_results or args.web_provider != "none" or args.search_only or args.max_results):
            raise ValueError("resume uses saved catalogs only; omit search options")
        config = load_config(Path(args.config))
        plan = query_plan(config)
        if args.command == "discover":
            batches = [{"product": product["id"], **discover(product, OFFICIAL_DOMAINS, args.seed_page_budget)}
                       for product in config["products"]]
            atomic_json(Path(args.out), {"generated_at": now(), "provider": "official_pages", "executed_queries": [],
                "results": [result for batch in batches for result in batch["results"]], "discovery": batches})
            print(f"Saved {sum(len(batch['results']) for batch in batches)} public link candidates to {args.out}")
            return 0 if all(batch["complete"] for batch in batches) else 2
        if args.command == "plan":
            atomic_json(Path(args.out), {"vendor": VENDOR, "queries": plan})
            print(f"Saved {len(plan)} web queries to {args.out}")
            return 0
        root = Path(args.root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        lock = root / ".manual-watch.lock"
        try:
            with lock.open("x", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "started_at": now()}, handle)
        except FileExistsError:
            raise ValueError("Another run or stale lock exists; inspect .manual-watch.lock before retrying")
        try:
            web = read_json(Path(args.web_results)) if args.web_results else {"results": [], "executed_queries": []}
            if args.web_provider == "tavily":
                for entry in web.get("executed_queries", []):
                    entry.setdefault("searched_at", web.get("generated_at", ""))
                provider_web = tavily_search(plan, args.web_max_results)
                web["generated_at"] = provider_web["generated_at"]
                for field in ("results", "executed_queries", "errors"):
                    web.setdefault(field, []).extend(provider_web.get(field, []))
            reports = []
            for product in config["products"]:
                try:
                    report = run_product(product, root, web, args)
                except Exception as exc:
                    report = {"generated_at": now(), "product": product["id"], "vendor": VENDOR,
                              "ok": False, "runtime_error": str(exc)}
                    atomic_json(root / product["id"] / ("latest-resume-report.json" if args.command == "resume" else "latest-report.json"), report)
                reports.append(report)
                if report.get("runtime_error"):
                    print(f"{product['id']}: {report['runtime_error']}", file=sys.stderr)
                elif report.get("mode") == "resume":
                    print(f"{product['id']}: resumed saved catalog; no searches performed")
                else:
                    print(f"{product['id']}: {report['catalog_count']} known items; {len(report['added'])} added; {len(report['changed'])} changed; {report['web_coverage']}")
            atomic_json(root / ("latest-resume-report.json" if args.command == "resume" else "latest-report.json"), {"generated_at": now(), "products": reports})
            if any(report.get("runtime_error") for report in reports):
                return 1
            return 0 if all(report["ok"] for report in reports) else 2
        finally:
            lock.unlink()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
