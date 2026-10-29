"""Keep published Yokogawa CLI defaults when integrating shared collector upgrades."""

import contextlib
import io
import unittest

import library_common as common
import yokogawa_library as library


class PublishedCompatibilityTests(unittest.TestCase):
    def test_direct_files_remain_the_default_for_download_and_sync(self):
        for command in ("download", "sync"):
            args = library.build_parser().parse_args([command, "--manifest", "m.json", "--dir", "files"])
            self.assertTrue(args.direct_only)
        page = {"detail_page_url": "https://www.yokogawa.com/detail", "download_skip_reason": "detail_page"}
        self.assertEqual(library.item_archive_url(page), ("", ""))

    def test_published_explicit_detail_flag_still_works(self):
        for command in ("download", "sync"):
            args = library.build_parser().parse_args([command, "--manifest", "m.json", "--dir", "files", "--include-detail-pages"])
            self.assertFalse(args.direct_only)

    def test_contradictory_download_flags_fail(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            library.build_parser().parse_args(["download", "--manifest", "m.json", "--dir", "files",
                                              "--include-detail-pages", "--direct-only"])

    def test_published_waf_markers_still_rejected(self):
        for marker in (b"AWS WAF", b"request blocked", b"Forbidden"):
            payload = b"<html>" + marker + b"</html>"
            with self.assertRaises(ValueError):
                common.validate_payload(payload, len(payload), ".html", "text/html")


if __name__ == "__main__":
    unittest.main(verbosity=2)
