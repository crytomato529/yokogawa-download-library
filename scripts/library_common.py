"""Shared integrity and persistence helpers; Python standard library only."""

from __future__ import annotations

import hashlib
import json
import errno
import os
import sys
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_direct_after_proxy_failure = False
_certificate_bundle = None


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


def network_status() -> str:
    mode = os.environ.get("LIBRARY_NETWORK_MODE", "auto").lower()
    return "direct_after_local_proxy_failure" if _direct_after_proxy_failure else mode


def certificate_status() -> str:
    return "certifi" if _certificate_bundle else "system"


def _load_certifi_bundle():
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return None
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


def allowed_url(url: str, domains: list[str]) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return (parts.scheme in ("https", "http") and not parts.username and
            any(host == domain or host.endswith("." + domain) for domain in domains))


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, domains):
        self.domains = domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl, self.domains):
            raise ValueError("Redirect outside configured official domains requires review")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_request(request, timeout, direct, allowed_domains=None):
    if not direct and not _certificate_bundle and not allowed_domains:
        return urllib.request.urlopen(request, timeout=timeout)
    handlers = [urllib.request.ProxyHandler({})] if direct else []
    if allowed_domains:
        handlers.append(OfficialRedirect(allowed_domains))
    if _certificate_bundle:
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=_certificate_bundle)))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


def open_url(request, timeout: int = 60, allowed_domains=None):
    """Recover only from a refused loopback proxy, never from a remote HTTP denial."""
    global _direct_after_proxy_failure, _certificate_bundle
    mode = os.environ.get("LIBRARY_NETWORK_MODE", "auto").lower()
    url = request.full_url if isinstance(request, urllib.request.Request) else request
    if allowed_domains and not allowed_url(url, allowed_domains):
        raise ValueError("URL is outside configured official domains")
    if mode not in ("auto", "default", "direct"):
        raise ValueError("LIBRARY_NETWORK_MODE must be auto, default or direct")
    original = request
    if isinstance(request, urllib.request.Request):
        original = urllib.request.Request(request.full_url, data=request.data,
            headers=dict(request.header_items()), method=request.get_method(),
            origin_req_host=request.origin_req_host, unverifiable=request.unverifiable)
    try:
        direct = mode == "direct" or (mode == "auto" and _direct_after_proxy_failure)
        return _open_request(request, timeout, direct, allowed_domains)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError) and not _certificate_bundle:
            bundle = _load_certifi_bundle()
            if bundle:
                _certificate_bundle = bundle
                print("System CA validation failed; retrying with certifi and TLS verification enabled.", file=sys.stderr)
                return open_url(original, timeout=timeout, allowed_domains=allowed_domains)
        if isinstance(exc, urllib.error.HTTPError) or mode != "auto":
            raise
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        proxies = urllib.request.getproxies()
        proxy = proxies.get(urllib.parse.urlsplit(url).scheme) or proxies.get("all", "")
        local_proxy = urllib.parse.urlsplit(proxy).hostname in ("localhost", "127.0.0.1", "::1")
        reason = exc.reason
        refused = (isinstance(reason, ConnectionRefusedError) or
                   getattr(reason, "errno", None) == errno.ECONNREFUSED or
                   getattr(reason, "winerror", None) == 10061)
        if not local_proxy or not refused or direct:
            raise
        _direct_after_proxy_failure = True
        print("Local proxy is unavailable; using a direct connection for this process.", file=sys.stderr)
        return open_url(original, timeout=timeout, allowed_domains=allowed_domains)


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def fingerprint(item: dict, file_info: dict | None = None) -> str:
    fields = ("code", "name", "category", "edition", "updated_at", "updated_at_display",
              "reference", "title", "version", "revision", "last_modified", "document_date",
              "display_language", "locales")
    data = {field: item.get(field) for field in fields if item.get(field) is not None}
    if file_info is not None:
        data["file"] = {field: file_info.get(field) for field in
                        ("filename", "extension", "checksum", "size")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def valid_record(record: dict | None, url: str, expected_fingerprint: str | None = None) -> bool:
    if not record or record.get("url") != url or record.get("status", "completed") != "completed":
        return False
    if expected_fingerprint is not None and record.get("fingerprint") != expected_fingerprint:
        return False
    path = Path(record.get("path", ""))
    if not path.is_file() or not record.get("bytes") or record["bytes"] != path.stat().st_size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return bool(record.get("sha256")) and digest.hexdigest() == record["sha256"]


def validate_payload(head: bytes, size: int, extension: str, content_type: str = "") -> None:
    if size == 0:
        raise ValueError("Empty response: not a completed download")
    sample = head.lstrip().lower()
    html_body = "text/html" in content_type.lower() or sample.startswith((b"<!doctype html", b"<html"))
    if extension.lower() == ".html":
        if not html_body or any(marker in sample for marker in
                                (b"awswaf", b"aws-waf", b"aws waf", b"request blocked",
                                 b"forbidden", b"captcha", b"access denied", b"just a moment")):
            raise ValueError("Page is empty, blocked, or not HTML")
    elif html_body:
        raise ValueError("Received HTML/login/challenge instead of a file")
    elif extension.lower() == ".pdf" and b"%PDF-" not in head[:1024]:
        raise ValueError("Invalid PDF signature")
    elif extension.lower() in (".zip", ".docx", ".xlsx", ".pptx") and not head.startswith(b"PK"):
        raise ValueError("Invalid ZIP/Office signature")


def download_validated(url: str, dest: Path, headers: dict, existing: dict | None = None) -> dict:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("Only HTTP(S) downloads are supported")
    request_headers = dict(headers)
    if existing:
        if existing.get("etag"):
            request_headers["If-None-Match"] = existing["etag"]
        if existing.get("last_modified_http"):
            request_headers["If-Modified-Since"] = existing["last_modified_http"]
    request = urllib.request.Request(url, headers=request_headers)
    temporary = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        try:
            response = open_url(request, timeout=180)
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and existing:
                return dict(existing, unchanged=True)
            raise
        with response, temporary.open("wb") as handle:
            if response.status != 200:
                raise ValueError(f"HTTP {response.status}: expected a complete file response")
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
            etag = response.headers.get("ETag", "")
            modified = response.headers.get("Last-Modified", "")
            expected_size = response.headers.get("Content-Length")
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                if len(head) < 8192:
                    head += chunk[:8192 - len(head)]
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        validate_payload(head, size, dest.suffix, content_type)
        if expected_size and size != int(expected_size):
            raise ValueError("Incomplete response: Content-Length mismatch")
        sha256 = digest.hexdigest()
        if existing and sha256 == existing.get("sha256"):
            return dict(existing, etag=etag, last_modified_http=modified, unchanged=True)
        temporary.replace(dest)
        return {"path": str(dest), "bytes": size, "sha256": sha256, "etag": etag,
                "last_modified_http": modified, "content_type": content_type,
                "final_url": final_url, "unchanged": False}
    finally:
        if temporary.exists():
            temporary.unlink()


def save_snapshot(path: Path, previous: dict | None, manifest: dict) -> bool:
    """Keep a complete prior inventory when a test or unstable pagination is partial."""
    if previous:
        stamp = str(manifest["generated_at"]).replace(":", "-").replace("+", "_")
        atomic_json(path.parent / (path.stem + "_history") / (stamp + ".json"), previous)
        if previous.get("query") != manifest.get("query"):
            raise ValueError("Manifest query changed; use a separate manifest for each search scope")
        if not manifest.get("search_complete", True):
            atomic_json(path.with_name(path.stem + "_partial.json"), manifest)
            return False
    atomic_json(path, manifest)
    return True
