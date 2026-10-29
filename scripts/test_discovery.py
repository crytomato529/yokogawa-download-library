"""Regression tests for bounded discovery, offline resume, references and RAG lineage."""

import argparse
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import library_common as common
import manual_watch as watch
import manual_references as references
import source_discovery as discovery


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.original_brand = watch.VENDOR
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original_route = common._direct_after_proxy_failure
        common._direct_after_proxy_failure = False

    def tearDown(self):
        watch.configure_brand(self.original_brand)
        common._direct_after_proxy_failure = self.original_route
        self.temp.cleanup()

    def test_pdf_endpoint_detection(self):
        self.assertTrue(discovery.pdf_link("https://library.yokogawa.com/document/download/x/123//EN/"))
        self.assertTrue(discovery.pdf_link("https://download.schneider-electric.com/files?p_File_Name=A.11.pdf&p_Doc_Ref=A"))
        self.assertFalse(discovery.pdf_link("https://example.org/index.html?query=manual.pdf"))
        self.assertFalse(discovery.pdf_link("https://example.org/document/download/x/"))

    def test_dam_cosmetic_flag_deduplicated_but_file_parameters_kept(self):
        url = "https://prod-edam.honeywell.com/a.pdf"
        self.assertEqual(watch.canonical_url(url + "?download=false"), url)
        self.assertEqual(watch.canonical_url(url + "?download=true&version=2"), url + "?version=2")
        other = "https://download.schneider-electric.com/files?p_File_Name=x.pdf&p_Doc_Ref=A"
        self.assertEqual(watch.canonical_url(other), other)

    def test_official_endpoint_is_candidate_not_verified_metadata(self):
        watch.configure_brand("yokogawa")
        item, evidence = watch.native_web_item({"url": "https://library.yokogawa.com/document/download/x/123//EN/",
            "title": "ProSafe-RS Hardware", "version": ""}, {"id": "p", "keywords": ["ProSafe-RS"]})
        self.assertIsNotNone(item)
        self.assertFalse(item["metadata_verified"])
        self.assertEqual(evidence["status"], "download_candidate")

    def test_domain_and_redirect_boundaries(self):
        domains = ["yokogawa.com"]
        self.assertFalse(common.allowed_url("https://yokogawa.com.evil.test/a", domains))
        self.assertFalse(common.allowed_url("https://user@yokogawa.com/a", domains))
        self.assertFalse(common.allowed_url("file:///manual.pdf", domains))
        with self.assertRaises(ValueError):
            common.OfficialRedirect(domains).redirect_request(urllib.request.Request("https://yokogawa.com/"), None, 302, "", {}, "http://127.0.0.1/private")

    def test_link_parser_does_not_execute_scripts(self):
        parser = discovery.Links()
        parser.feed('<h1>Safety Manager</h1><script>evil()</script><a href="a.pdf"><b>Hardware</b> Reference</a>')
        self.assertEqual(parser.links[0]["label"], "Hardware Reference")
        self.assertEqual(parser.heading, ["Safety Manager"])

    def test_discovery_follows_only_document_pages_and_reports_budget(self):
        parser = discovery.Links()
        parser.feed('<h1>M580</h1><a href="/download/document/A/">Manual</a><a href="/news">News</a><a href="https://other.test/manual.pdf">Mirror</a><a href="/a.pdf">M580 manual</a>')
        product = {"id": "m580", "seed_pages": ["https://www.se.com/faq"]}
        with patch.object(discovery, "fetch_links", return_value=(product["seed_pages"][0], parser)) as fetch:
            result = discovery.discover(product, ["se.com"], page_budget=1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["pending_pages"], ["https://www.se.com/download/document/A/"])
        self.assertFalse(result["complete"])

    def test_empty_or_denied_seed_does_not_report_success(self):
        product = {"id": "p", "seed_pages": ["https://www.se.com/a"]}
        with patch.object(discovery, "fetch_links", return_value=(product["seed_pages"][0], discovery.Links())):
            self.assertFalse(discovery.discover(product, ["se.com"])["complete"])
        with patch.object(discovery, "fetch_links", side_effect=ValueError("challenge")):
            self.assertFalse(discovery.discover(product, ["se.com"])["complete"])

    def test_reference_patterns_and_page_text_normalization(self):
        cases = {"yokogawa": ("See IM 32Q06C10-31E", "IM 32Q06C10-31E"),
                 "schneider": ("EIO0000001583 / QGH60283", "EIO0000001583"),
                 "honeywell": ("EP-SM.MAN.6284", "EP-SM.MAN.6284"),
                 "siemens": ("A5E50811213-AC", "A5E50811213-AC")}
        for brand, (text, expected) in cases.items():
            self.assertEqual(references.extract(text, brand)[0][0], expected)
            self.assertEqual(references.extract("2026 123456 revision 2", brand), [])

    def test_reference_gap_comparison_does_not_collapse_languages(self):
        result = {"references": [{"document_number": "IM 32P06C10-01EN"}, {"document_number": "IM 32P06C10-01JA"}]}
        references.compare_catalog(result, {"items": [{"key": "a", "code": "IM32P06C10-01EN"}]})
        self.assertEqual(result["catalog_comparison"]["catalogued"], 1)
        self.assertEqual(result["references"][1]["catalog_status"], "not_in_catalog")

    def test_query_plan_covers_regional_hosts_and_document_numbers(self):
        watch.configure_brand("yokogawa")
        queries = watch.query_plan({"products": [{"id": "p", "keywords": ["ProSafe-RS"], "document_numbers": ["IM 32P06S10-01Z1"]}]})
        self.assertIn("site:yokogawa.co.jp", queries[0]["query"])
        self.assertIn('"IM 32P06S10-01Z1"', queries[-1]["query"])
        self.assertEqual(len(queries), 4)

    def test_public_empty_password_pdf_can_be_inspected(self):
        path = self.root / "public.pdf"
        path.write_bytes(b"fixture")
        reader = SimpleNamespace(is_encrypted=True, decrypt=lambda password: 1 if password == "" else 0,
            pages=[SimpleNamespace(extract_text=lambda: "IM 32P06S10-01Z1")])
        with patch.dict("sys.modules", {"pypdf": SimpleNamespace(PdfReader=lambda _: reader)}):
            result = references.inspect_pdf(path, "yokogawa")
        self.assertEqual(len(result["references"]), 1)
        self.assertEqual(result["references"][0]["pages"], [1])

    def test_password_required_pdf_is_not_cracked(self):
        reader = SimpleNamespace(is_encrypted=True, decrypt=lambda password: 0)
        with patch.dict("sys.modules", {"pypdf": SimpleNamespace(PdfReader=lambda _: reader)}):
            with self.assertRaisesRegex(ValueError, "Password-protected"):
                references.inspect_pdf(self.root / "private.pdf", "yokogawa")

    def test_verified_web_metadata_retains_other_attachments(self):
        previous = {"key": "a", "files": [{"download_url": "https://se.com/a.pdf", "filename": "real.pdf"},
                                            {"download_url": "https://se.com/b.pdf", "filename": "second.pdf"}]}
        incoming = {"key": "web-a", "metadata_verified": True, "version": "2", "files": [{"download_url": "https://se.com/a.pdf", "filename": "a.pdf"}]}
        merged = watch.merge_web_metadata(previous, incoming)
        self.assertEqual(merged["files"], previous["files"])
        self.assertEqual(merged["version"], "2")

    def test_failed_direct_fallback_stops_after_two_attempts(self):
        failure = urllib.error.URLError(ConnectionRefusedError())
        with patch.dict("os.environ", {"LIBRARY_NETWORK_MODE": "auto"}), \
             patch("urllib.request.getproxies", return_value={"https": "http://127.0.0.1:7892"}), \
             patch.object(common, "_open_request", side_effect=failure) as attempt:
            with self.assertRaises(urllib.error.URLError):
                common.open_url("https://example.org/")
        self.assertEqual(attempt.call_count, 2)

    def test_unsolicited_partial_content_cannot_complete(self):
        class Partial:
            status = 206
            def __enter__(self): return self
            def __exit__(self, *args): pass
        with patch.object(common, "open_url", return_value=Partial()):
            with self.assertRaisesRegex(ValueError, "206"):
                common.download_validated("https://example.org/manual.pdf", self.root / "manual.pdf", {})
        self.assertFalse((self.root / "manual.pdf").exists())

    def test_resume_never_calls_search_or_changes_catalog_observation(self):
        watch.configure_brand("honeywell")
        product = {"id": "p", "keywords": ["Safety Manager"], "seed_pages": ["https://honeywell.com/p"]}
        config = self.root / "config.json"
        common.atomic_json(config, {"products": [product]})
        catalog = {"vendor": "honeywell", "scope": product, "items": [], "generated_at": "2000-01-01"}
        common.atomic_json(self.root / "p" / "catalog.json", catalog)
        common.atomic_json(self.root / "p" / "latest-report.json", {"old": "discovery evidence"})
        with patch.object(watch, "discover", side_effect=AssertionError("Unexpected network discovery")), \
             patch.object(watch, "tavily_search", side_effect=AssertionError("Unexpected search")), \
             patch.object(watch, "download_catalog", return_value=([], 0, {"downloaded": 0, "skipped": 0})), \
             contextlib.redirect_stdout(io.StringIO()):
            code = watch.main(["resume", "--brand", "honeywell", "--config", str(config), "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(watch.read_json(self.root / "p" / "catalog.json"), catalog)
        self.assertEqual(watch.read_json(self.root / "p" / "latest-report.json"), {"old": "discovery evidence"})
        report = watch.read_json(self.root / "latest-resume-report.json")["products"][0]
        self.assertFalse(report["discovery_performed"])

    def test_rag_history_does_not_inherit_new_metadata(self):
        watch.configure_brand("honeywell")
        directory = self.root / "p"
        records = []
        for version in ("1", "2"):
            path = self.root / (version + ".pdf")
            payload = b"%PDF-1.7\n" + version.encode()
            path.write_bytes(payload)
            records.append({"url": "https://honeywell.com/m.pdf", "path": str(path), "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "version": version, "key": "k"})
        common.atomic_json(directory / "downloads" / ".honeywell_download_state.json", {"files": {"k": records[1]}, "history": [records[0]]})
        watch.export_rag(directory, {"items": [{"key": "k", "version": "2", "title": "Current title", "reference": "NEW", "files": [{"download_url": records[0]["url"]}]}]})
        rows = [json.loads(line) for line in (directory / "rag-index.jsonl").read_text().splitlines()]
        self.assertEqual(rows[1]["local_status"], "historical")
        self.assertIsNone(rows[1]["document_number"])
        self.assertIsNone(rows[1]["title"])
        self.assertEqual(len((directory / "rag-current.jsonl").read_text().splitlines()), 1)

    def test_pending_catalog_revision_excluded_from_current_index(self):
        watch.configure_brand("honeywell")
        path = self.root / "old.pdf"
        payload = b"%PDF-1.7\nold"
        path.write_bytes(payload)
        common.atomic_json(self.root / "downloads" / ".honeywell_download_state.json", {"files": {"k": {
            "key": "k", "url": "https://honeywell.com/m.pdf", "path": str(path), "version": "1",
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}}})
        watch.export_rag(self.root, {"items": [{"key": "k", "version": "2", "files": []}]})
        self.assertEqual((self.root / "rag-current.jsonl").read_text(), "")
        self.assertEqual(json.loads((self.root / "rag-index.jsonl").read_text())["local_status"], "catalog_revision_pending")

    def test_denied_endpoint_stops_alias_repetition(self):
        watch.configure_brand("schneider")
        product = {"id": "p", "keywords": ["M580", "Modicon M580"]}
        error = urllib.error.HTTPError("https://se.com/api", 403, "Forbidden", {}, None)
        args = argparse.Namespace(max_results=0, limit=0, search_only=True, revalidate=False)
        with patch.object(watch.LIBRARY, "search_library", side_effect=error) as search:
            report = watch.run_product(product, self.root, {}, args)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(report["official_sources"][1]["status"], "not_attempted_endpoint_denied")
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
