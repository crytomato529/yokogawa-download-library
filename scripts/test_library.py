"""Offline regressions for download integrity, resume and source merging."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.server
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import ssl
import urllib.request
from pathlib import Path
from unittest.mock import patch

import library_common as common
import manual_watch as watch


LIBRARY = watch.LIBRARY
YOKOGAWA = watch.VENDOR == "yokogawa"


class Handler(http.server.BaseHTTPRequestHandler):
    revision = 1

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == "/empty.pdf":
            self.send_response(204)
            self.end_headers()
            return
        if self.path == "/html.pdf":
            body = b"<html>Login required</html>"
            content_type = "text/html"
        elif self.path == "/invalid.pdf":
            body = b"This is not a PDF"
            content_type = "application/pdf"
        else:
            tag = f'"revision-{self.revision}"'
            if self.headers.get("If-None-Match") == tag:
                self.send_response(304)
                self.end_headers()
                return
            body = b"%PDF-1.7\n" + self.path.encode() + str(self.revision).encode()
            content_type = "application/pdf"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", f'"revision-{self.revision}"')
        self.end_headers()
        self.wfile.write(body)


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cls.network_patch = patch("library_common.urllib.request.urlopen", opener.open)
        cls.network_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.network_patch.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manifest = self.root / "manifest.json"
        self.downloads = self.root / "downloads"
        Handler.revision = 1
        common._direct_after_proxy_failure = False
        common._certificate_bundle = None

    def tearDown(self):
        self.temporary.cleanup()

    def item(self, identity, path=None, version="1", title=None):
        url = self.base + (path or f"/{identity}.pdf")
        if YOKOGAWA:
            return {"id": identity, "key": identity, "code": identity, "name": title or "Test product",
                    "category": "Instruction Manual", "edition": version, "file_ext": "pdf", "direct_download_url": url}
        return {"key": identity, "reference": identity, "title": title or "Test product", "version": version,
                "document_type": "1555855-User guide", "files": [{"download_url": url, "extension": "pdf", "filename": identity + ".pdf"}]}

    def download(self, items, **kwargs):
        common.atomic_json(self.manifest, {"items": items})
        args = argparse.Namespace(manifest=str(self.manifest), dir=str(self.downloads), state="", limit=0,
                                  force=False, revalidate=False, direct_only=True)
        for key, value in kwargs.items():
            setattr(args, key, value)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = LIBRARY.command_download(args)
        return code, json.loads((self.downloads / f".{watch.VENDOR}_download_state.json").read_text())

    def test_two_then_next_two_then_complete(self):
        items = [self.item(str(i)) for i in range(5)]
        self.assertEqual(len(self.download(items, limit=2)[1]["files"]), 2)
        self.assertEqual(len(self.download(items, limit=2)[1]["files"]), 4)
        code, state = self.download(items)
        self.assertEqual(code, 0)
        self.assertEqual(len(state["files"]), 5)
        report = json.loads((self.downloads / "download_report.json").read_text())
        self.assertEqual(report["downloaded"], 1)
        self.assertEqual(report["skipped"], 4)

    def test_bad_responses_cannot_complete(self):
        for name in ("empty", "html", "invalid"):
            code, state = self.download([self.item(name, f"/{name}.pdf")])
            self.assertEqual(code, 1)
            self.assertEqual(state["files"], {})
            self.assertTrue(state["errors"])
        self.assertFalse(list(self.downloads.glob("*.part")))

    def test_same_url_new_metadata_keeps_old_file(self):
        _, first = self.download([self.item("same", version="1")])
        old_path = Path(next(iter(first["files"].values()))["path"])
        _, second = self.download([self.item("same", version="2")])
        new_path = Path(next(iter(second["files"].values()))["path"])
        self.assertNotEqual(old_path, new_path)
        self.assertTrue(old_path.is_file())

    def test_same_size_corruption_is_repaired(self):
        _, state = self.download([self.item("same")])
        record = next(iter(state["files"].values()))
        Path(record["path"]).write_bytes(b"x" * record["bytes"])
        _, repaired = self.download([self.item("same")])
        self.assertTrue(common.valid_record(next(iter(repaired["files"].values())), record["url"]))

    def test_conditional_revalidation_and_silent_replacement(self):
        _, state = self.download([self.item("same")])
        old_path = Path(next(iter(state["files"].values()))["path"])
        self.download([self.item("same")], revalidate=True)
        self.assertEqual(json.loads((self.downloads / "download_report.json").read_text())["downloaded"], 0)
        Handler.revision = 2
        _, state = self.download([self.item("same")], revalidate=True)
        new_path = Path(next(iter(state["files"].values()))["path"])
        self.assertNotEqual(old_path, new_path)
        self.assertTrue(old_path.is_file())

    def test_filename_collision_keeps_both_contents(self):
        first, second = self.item("one"), self.item("two")
        if YOKOGAWA:
            second["code"] = first["code"]
        else:
            second["reference"] = first["reference"]
        _, state = self.download([first, second])
        paths = [record["path"] for record in state["files"].values()]
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(Path(path).is_file() for path in paths))
        self.download([first, second])
        self.assertEqual(json.loads((self.downloads / "download_report.json").read_text())["skipped"], 2)

    def test_partial_snapshot_preserves_complete_inventory(self):
        old = {"generated_at": "old", "query": {"keyword": "x"}, "search_complete": True, "items": [1, 2]}
        new = {"generated_at": "new", "query": old["query"], "search_complete": False, "items": [1]}
        common.atomic_json(self.manifest, old)
        self.assertFalse(common.save_snapshot(self.manifest, old, new))
        self.assertEqual(json.loads(self.manifest.read_text()), old)
        self.assertTrue(self.manifest.with_name("manifest_partial.json").is_file())
        with self.assertRaises(ValueError):
            common.save_snapshot(self.manifest, old, {**new, "query": {"keyword": "different"}})

    def test_web_relevance_trust_and_restrictions(self):
        product = {"id": "test", "keywords": ["Test product"]}
        domain = watch.OFFICIAL_DOMAINS[0]
        official = {"url": f"https://files.{domain}/manual.pdf", "title": "Test product manual"}
        self.assertIsNotNone(watch.native_web_item(official, product)[0])
        self.assertIsNone(watch.native_web_item({**official, "title": "Different product"}, product)[0])
        self.assertIsNone(watch.native_web_item({**official, "login_required": True}, product)[0])
        mirror = {**official, "url": f"https://{domain}.evil.example/manual.pdf"}
        self.assertIsNone(watch.native_web_item(mirror, product)[0])
        self.assertIsNotNone(watch.native_web_item({**mirror, "verified": True}, product)[0])
        extensionless = {**official, "download_url": f"https://files.{domain}/files?ref=123", "file_ext": "pdf", "verified": True}
        self.assertIsNotNone(watch.native_web_item(extensionless, product)[0])

    def test_watch_preserves_omitted_items_on_api_failure(self):
        product = {"id": "test", "keywords": ["Test product"]}
        args = argparse.Namespace(max_results=0, limit=0, search_only=True, revalidate=False)
        manifest = {"count": 1, "total_reported": 1, "search_complete": True, "items": [self.item("known")]}
        with patch.object(LIBRARY, "search_library", return_value=manifest):
            watch.run_product(product, self.root, {"results": []}, args)
        with patch.object(LIBRARY, "search_library", side_effect=RuntimeError("Blocked")):
            report = watch.run_product(product, self.root, {"results": []}, args)
        self.assertEqual(report["catalog_count"], 1)
        self.assertEqual(report["not_observed"], ["known"])
        self.assertFalse(report["ok"])

    def test_page_order_changes_do_not_hide_new_files(self):
        item = self.item("known")
        newer = json.loads(json.dumps(item))
        if YOKOGAWA:
            newer["edition"] = "2"
        else:
            newer["files"].append({"download_url": self.base + "/new.pdf", "extension": "pdf"})
        diff = LIBRARY.compare_manifests({"items": [item]}, {"items": [newer]})
        self.assertEqual(diff["changed_count"], 1)

    def test_legacy_zero_byte_state_is_never_current(self):
        dest = self.root / "empty.pdf"
        dest.touch()
        record = {"status": "completed", "url": "https://example.org/empty.pdf", "path": str(dest),
                  "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        self.assertFalse(common.valid_record(record, record["url"]))

    def test_rag_index_preserves_versions_and_rejects_corruption(self):
        directory = self.root / "test"
        self.downloads = directory / "downloads"
        _, state = self.download([self.item("same", version="1")])
        _, state = self.download([self.item("same", version="2")])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(watch.export_rag(directory, {"items": [self.item("same", version="2")]}), 2)
        rows = [json.loads(line) for line in (directory / "rag-index.jsonl").read_text().splitlines()]
        self.assertEqual({row["version"] for row in rows}, {"1", "2"})
        old_path = Path(state["history"][0]["path"])
        old_path.write_bytes(b"x" * old_path.stat().st_size)
        self.assertEqual(watch.export_rag(directory, {"items": [self.item("same", version="2")]}), 1)

    def test_known_official_url_is_not_duplicated_when_api_fails(self):
        product = {"id": "test", "keywords": ["Test product"]}
        item = self.item("known", title="Test product manual")
        args = argparse.Namespace(max_results=0, limit=0, search_only=True, revalidate=False)
        manifest = {"count": 1, "total_reported": 1, "search_complete": True, "items": [item]}
        with patch.object(LIBRARY, "search_library", return_value=manifest):
            watch.run_product(product, self.root, {"results": []}, args)
        url = next(iter(watch.item_urls(item)))
        result = {"product": "test", "url": url, "title": "Test product manual", "verified": True}
        with patch.object(LIBRARY, "search_library", side_effect=RuntimeError("Blocked")):
            report = watch.run_product(product, self.root, {"results": [result]}, args)
        self.assertEqual(report["catalog_count"], 1)
        self.assertEqual(report["not_observed"], [])

    def test_query_expansion_keeps_catalog_but_locale_change_rejected(self):
        product = {"id": "test", "keywords": ["Test product"]}
        args = argparse.Namespace(max_results=0, limit=0, search_only=True, revalidate=False)
        manifest = {"count": 1, "total_reported": 1, "search_complete": True, "items": [self.item("known")]}
        with patch.object(LIBRARY, "search_library", return_value=manifest):
            watch.run_product(product, self.root, {"results": []}, args)
            report = watch.run_product({**product, "extra_queries": ["known manual number"]}, self.root, {"results": []}, args)
            self.assertTrue(report["scope_changed"])
            self.assertEqual(report["catalog_count"], 1)
            with self.assertRaises(ValueError):
                watch.run_product({**product, "library_args": ["--language", "en"]}, self.root, {"results": []}, args)

    def test_versioned_filename_handles_missing_and_letter_versions(self):
        item = self.item("R1", title="A/B:C*D", version="SV2.73")
        filename = LIBRARY.filename_for_item(item) if YOKOGAWA else LIBRARY.filename_for(item, item["files"][0])
        self.assertIn("SV2.73", filename)
        self.assertIn("A_B_C_D", filename)
        self.assertTrue(filename.endswith(".pdf"))
        self.assertNotIn(".pdf.pdf", filename)
        item = self.item("R1", title="A" * 250, version="42")
        filename = LIBRARY.filename_for_item(item) if YOKOGAWA else LIBRARY.filename_for(item, item["files"][0])
        self.assertIn("42.pdf", filename)

    def test_stale_web_results_do_not_count_as_fresh_collection(self):
        product = {"id": "test", "keywords": ["Test product"]}
        args = argparse.Namespace(max_results=0, limit=0, search_only=True, revalidate=False)
        manifest = {"count": 0, "total_reported": 0, "search_complete": True, "items": []}
        web = {"generated_at": "2000-01-01T00:00:00Z", "executed_queries": watch.query_plan({"products": [product]}), "results": []}
        with patch.object(LIBRARY, "search_library", return_value=manifest):
            report = watch.run_product(product, self.root, web, args)
        self.assertFalse(report["web_results_fresh"])
        self.assertFalse(report["ok"])

    def test_watcher_downloads_pdf_not_firmware_by_default(self):
        pdf = self.item("manual")
        firmware = self.item("firmware", "/firmware.zip")
        if YOKOGAWA:
            firmware["file_ext"] = "zip"
        else:
            firmware["files"][0].update(extension="zip", filename="firmware.zip")
        self.assertEqual(watch.download_candidates([pdf, firmware], ["pdf"]), [pdf])
        self.assertEqual(len(watch.download_candidates([pdf, firmware], ["pdf", "zip"])), 2)

    def test_verified_same_url_web_revision_updates_catalog(self):
        product = {"id": "test", "keywords": ["Test product"]}
        args = argparse.Namespace(max_results=0, limit=0, search_only=True, revalidate=False)
        original = {"product": "test", "url": "https://example.org/manual.pdf", "title": "Test product manual",
                    "verified": True, "version": "1"}
        with patch.object(LIBRARY, "search_library", side_effect=RuntimeError("Blocked")):
            watch.run_product(product, self.root, {"results": [original]}, args)
            report = watch.run_product(product, self.root, {"results": [{**original, "version": "2"}]}, args)
        catalog = json.loads((self.root / "test" / "catalog.json").read_text())
        self.assertEqual(len(catalog["items"]), 1)
        self.assertEqual(catalog["items"][0].get("edition") if YOKOGAWA else catalog["items"][0].get("version"), "2")
        self.assertEqual(len(report["changed"]), 1)

    def test_unverified_web_metadata_cannot_replace_official_revision(self):
        previous = {**self.item("native"), "source_tier": "official"}
        incoming = {**self.item("web-other", version="999"), "metadata_verified": False}
        merged = watch.merge_web_metadata(previous, incoming)
        self.assertEqual(merged["key"], "native")
        self.assertEqual(merged.get("edition") if YOKOGAWA else merged.get("version"), "1")

    def test_fresh_global_stamp_does_not_refresh_old_query(self):
        web = {"generated_at": watch.now()}
        self.assertFalse(watch.fresh_query({"searched_at": "2000-01-01T00:00:00Z"}, web, 24))
        self.assertFalse(watch.fresh_query({"searched_at": ""}, web, 24))
        self.assertTrue(watch.fresh_query({"searched_at": watch.now()}, web, 24))

    def test_unavailable_local_proxy_has_one_direct_fallback(self):
        request = urllib.request.Request("https://example.org/manual.pdf")
        with patch.dict("os.environ", {"LIBRARY_NETWORK_MODE": "auto"}), \
             patch("urllib.request.getproxies", return_value={"https": "http://127.0.0.1:7892"}), \
             patch("urllib.request.urlopen", side_effect=urllib.error.URLError(ConnectionRefusedError())) as primary, \
             patch("urllib.request.build_opener") as direct:
            direct.return_value.open.return_value = "response"
            self.assertEqual(common.open_url(request), "response")
            self.assertEqual(common.open_url(request), "response")
            self.assertEqual(primary.call_count, 1)

    def test_remote_http_denial_never_switches_network(self):
        request = urllib.request.Request("https://example.org/manual.pdf")
        error = urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        with patch.dict("os.environ", {"LIBRARY_NETWORK_MODE": "auto"}), \
             patch("urllib.request.urlopen", side_effect=error), patch("urllib.request.build_opener") as direct:
            with self.assertRaises(urllib.error.HTTPError):
                common.open_url(request)
            direct.assert_not_called()

    def test_proxy_mutation_does_not_leak_to_direct_retry(self):
        request = urllib.request.Request("https://example.org/manual.pdf")
        def refuse(mutated, **kwargs):
            mutated.set_proxy("127.0.0.1:7892", "http")
            mutated.add_header("Proxy-Authorization", "proxy-only-fixture")
            raise urllib.error.URLError(ConnectionRefusedError())
        with patch.dict("os.environ", {"LIBRARY_NETWORK_MODE": "auto"}), \
             patch("urllib.request.getproxies", return_value={"https": "http://127.0.0.1:7892"}), \
             patch("urllib.request.urlopen", side_effect=refuse), patch("urllib.request.build_opener") as direct:
            common.open_url(request)
            retried = direct.return_value.open.call_args.args[0]
            self.assertEqual(retried.host, "example.org")
            self.assertNotIn("Proxy-authorization", retried.headers)

    def test_revalidation_keeps_original_download_timestamp(self):
        _, before = self.download([self.item("same")])
        timestamp = next(iter(before["files"].values()))["downloaded_at"]
        _, after = self.download([self.item("same")], revalidate=True)
        record = next(iter(after["files"].values()))
        self.assertEqual(record["downloaded_at"], timestamp)
        self.assertIn("checked_at", record)

    def test_certificate_fallback_keeps_verification_and_is_bounded(self):
        failure = urllib.error.URLError(ssl.SSLCertVerificationError("fixture CA failure"))
        with patch.object(common, "_load_certifi_bundle", return_value="fixture-ca.pem"), \
             patch.object(common, "_open_request", side_effect=[failure, "verified response"]) as attempt:
            self.assertEqual(common.open_url("https://example.org/manual.pdf"), "verified response")
            self.assertEqual(attempt.call_count, 2)
            self.assertEqual(common.certificate_status(), "certifi")
        common._certificate_bundle = None
        with patch.object(common, "_load_certifi_bundle", return_value="fixture-ca.pem"), \
             patch.object(common, "_open_request", side_effect=failure) as attempt:
            with self.assertRaises(urllib.error.URLError):
                common.open_url("https://example.org/manual.pdf")
            self.assertEqual(attempt.call_count, 2)

    def test_custom_ca_configuration_is_respected(self):
        with patch.dict("os.environ", {"SSL_CERT_FILE": "user-ca.pem"}):
            self.assertIsNone(common._load_certifi_bundle())


if __name__ == "__main__":
    unittest.main(verbosity=2)
