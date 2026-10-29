"""Verify web-only brand labels, state isolation, metadata refresh and resume."""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manual_watch as watch
import test_library as fixtures


class BrandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.RegressionTests.setUpClass()
        cls.base = fixtures.RegressionTests.base

    @classmethod
    def tearDownClass(cls):
        fixtures.RegressionTests.tearDownClass()

    def setUp(self):
        self.original_brand = watch.VENDOR
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        watch.configure_brand(self.original_brand)
        self.temp.cleanup()

    def collect(self, brand, version="1"):
        watch.configure_brand(brand)
        product = {"id": "test-product", "keywords": ["Test product"]}
        web = {"generated_at": watch.now(), "executed_queries": watch.query_plan({"products": [product]}),
               "results": [{"product": product["id"], "url": self.base + "/manual.pdf", "title": "Test product manual",
                            "document_number": "R1", "document_type": "Manual", "verified": True, "version": version}]}
        args = argparse.Namespace(max_results=0, limit=1, search_only=False, revalidate=False)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return watch.run_product(product, self.root, web, args)

    def test_honeywell_download_then_resume_and_new_version(self):
        first = self.collect("honeywell")
        self.assertTrue(first["ok"])
        self.assertEqual(first["official_enumeration"], "not_implemented")
        self.assertEqual(first["source_mode"], "web_search")
        self.assertEqual(first["download_summary"]["downloaded"], 1)
        second = self.collect("honeywell")
        self.assertEqual(second["download_summary"]["skipped"], 1)
        third = self.collect("honeywell", "2")
        self.assertEqual(third["download_summary"]["downloaded"], 1)
        self.assertEqual(third["rag_file_count"], 2)
        state_dir = self.root / "test-product" / "downloads"
        self.assertTrue((state_dir / ".honeywell_download_state.json").is_file())
        self.assertFalse((state_dir / ".schneider_download_state.json").exists())
        rows = [json.loads(line) for line in (self.root / "test-product" / "rag-index.jsonl").read_text().splitlines()]
        self.assertEqual({row["vendor"] for row in rows}, {"honeywell"})

    def test_siemens_has_own_state_and_rag_vendor(self):
        report = self.collect("siemens")
        self.assertTrue(report["ok"])
        self.assertEqual(report["vendor"], "siemens")
        self.assertTrue((self.root / "test-product" / "downloads" / ".siemens_download_state.json").is_file())

    def test_brand_switch_cannot_overwrite_another_catalog(self):
        self.collect("honeywell")
        with self.assertRaises(ValueError):
            self.collect("siemens")
        catalog = json.loads((self.root / "test-product" / "catalog.json").read_text())
        self.assertEqual(catalog["vendor"], "honeywell")

    def test_official_domain_boundaries(self):
        watch.configure_brand("honeywell")
        self.assertTrue(watch.is_official("https://prod-edam.honeywell.com/manual.pdf"))
        self.assertFalse(watch.is_official("https://honeywell.com.evil.example/manual.pdf"))
        watch.configure_brand("siemens")
        self.assertTrue(watch.is_official("https://cache.industry.siemens.com/manual.pdf"))
        self.assertFalse(watch.is_official("https://siemens.com.evil.example/manual.pdf"))

    def test_one_failed_product_does_not_abort_later_products(self):
        config = self.root / "config.json"
        config.write_text(json.dumps({"products": [{"id": "bad", "keywords": ["bad"]},
                                                  {"id": "good", "keywords": ["good"]}]}))
        result = {"product": "good", "ok": True, "catalog_count": 0, "added": [], "changed": [], "web_coverage": "partial_or_not_run"}
        with patch.object(watch, "run_product", side_effect=[ValueError("Bad local state"), result]), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = watch.main(["run", "--brand", "honeywell", "--config", str(config), "--root", str(self.root)])
        self.assertEqual(code, 1)
        report = json.loads((self.root / "latest-report.json").read_text())
        self.assertEqual(len(report["products"]), 2)
        self.assertEqual(report["products"][1]["product"], "good")
        self.assertFalse((self.root / ".manual-watch.lock").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
