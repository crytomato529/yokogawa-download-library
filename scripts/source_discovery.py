"""Bounded discovery from configured public manufacturer pages; no browser or login."""

from collections import deque
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.parse
import urllib.request

from library_common import allowed_url, open_url


def normalize_download_url(url):
    parts = urllib.parse.urlsplit(url)
    # This DAM exposes identical PDF bytes with or without its UI download flag.
    if parts.hostname == "prod-edam.honeywell.com" and parts.path.lower().endswith(".pdf"):
        query = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                 if not (key == "download" and value in ("false", "true"))]
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment))
    return url


def pdf_link(url):
    parts = urllib.parse.urlsplit(url)
    if Path(urllib.parse.unquote(parts.path)).suffix.lower() == ".pdf":
        return True
    query = {key.lower(): value for key, value in urllib.parse.parse_qsl(parts.query)}
    return (any(value.lower().endswith(".pdf") for key, value in query.items()
                if key in ("p_file_name", "filename", "file")) or
            parts.hostname == "library.yokogawa.com" and "/document/download/" in parts.path)


def detail_link(url):
    path = urllib.parse.urlsplit(url).path
    return "/download/document/" in path or bool(re.search(r"/cs/(?:\w+/\w+/)?(?:view|document)/\d+", path))


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.title, self.heading = [], [], []
        self.active = None
        self.in_title = self.in_heading = False
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.ignored += 1
        if tag == "title":
            self.in_title = True
        if tag == "h1":
            self.in_heading = True
        if tag == "a" and attrs.get("href"):
            self.active = {"href": attrs["href"], "label": [], "restricted":
                any(word in (attrs.get("class", "") + " " + attrs.get("href", "")).lower()
                    for word in ("login", "sign-in", "signin", "agreement", "restricted"))}

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title.append(data)
        if self.in_heading:
            self.heading.append(data)
        if self.active is not None:
            self.active["label"].append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignored = max(0, self.ignored - 1)
        if tag == "title":
            self.in_title = False
        if tag == "h1":
            self.in_heading = False
        if tag == "a" and self.active is not None:
            self.active["label"] = " ".join(" ".join(self.active["label"]).split())
            self.links.append(self.active)
            self.active = None


def fetch_links(url, domains):
    request = urllib.request.Request(url, headers={"User-Agent": "IndustrialManualLibrary/1.1", "Accept": "text/html"})
    with open_url(request, timeout=35, allowed_domains=domains) as response:
        if response.status != 200 or "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError(f"Not a public HTML page (HTTP {response.status})")
        body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            raise ValueError("Page exceeds 4 MiB discovery limit")
        text = body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        if any(marker in text.lower() for marker in ("awswaf", "aws-waf", "challenge-platform")):
            raise ValueError("Access challenge; not a document listing")
        parser = Links()
        parser.feed(text)
        return response.geturl(), parser


def discover(product, domains, page_budget=12, depth=1):
    queue = deque((url, 0) for url in product.get("seed_pages", []))
    visited, documents, reports = set(), {}, []
    while queue and len(visited) < page_budget:
        url, level = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        report = {"url": url, "ok": False, "depth": level}
        reports.append(report)
        try:
            if not allowed_url(url, domains):
                raise ValueError("Seed is not on an official domain")
            final_url, page = fetch_links(url, domains)
            heading = " ".join(page.heading or page.title).strip()
            report.update(final_url=final_url, discovered_files=0)
            for link in page.links:
                target = normalize_download_url(urllib.parse.urljoin(final_url, link["href"]))
                if not allowed_url(target, domains):
                    continue
                if pdf_link(target):
                    documents.setdefault(target, {"product": product["id"], "url": final_url,
                        "download_url": target, "file_ext": "pdf", "title": link["label"] or heading,
                        "content": heading, "discovery_method": "official_page_link",
                        "verified": False, "login_required": link["restricted"]})
                    report["discovered_files"] += 1
                elif level < depth and detail_link(target) and not link["restricted"]:
                    queue.append((target, level + 1))
            report["ok"] = bool(report["discovered_files"] or any(detail_link(x["href"]) for x in page.links))
            if not report["ok"]:
                report["error"] = "No extractable document links; dynamic/login page or unsupported layout"
        except Exception as exc:
            report["error"] = str(exc)
    remaining = sorted({url for url, _ in queue} - visited)
    return {"results": list(documents.values()), "pages": reports,
            "pending_pages": remaining, "complete": not remaining and all(p["ok"] for p in reports)}
