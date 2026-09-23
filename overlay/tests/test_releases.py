from __future__ import annotations

import unittest

import releases


class ReleaseNameTest(unittest.TestCase):
    def test_tag_alone(self):
        self.assertEqual(releases.release_name("1.0.0", ""), "1.0.0")

    def test_tag_with_suffix(self):
        self.assertEqual(releases.release_name("1.0.0", "-r2"), "1.0.0-r2")

    def test_upstream_prerelease_style_tag(self):
        self.assertEqual(releases.release_name("0.41.0-n8.1.2", ""), "0.41.0-n8.1.2")

    def test_rejects_unsafe_tags(self):
        for bad in ("", "../1.0.0", "1.0.0; rm -rf /", "1.0 .0", "-1.0.0", "1.0.0/x", "$(id)"):
            with self.subTest(bad=bad), self.assertRaises(releases.ReleaseError):
                releases.release_name(bad, "")

    def test_rejects_unsafe_suffixes(self):
        for bad in ("r2", "-", "-r2;id", "-r 2", "/r2", "-r2/x", "--r2"):
            with self.subTest(bad=bad), self.assertRaises(releases.ReleaseError):
                releases.release_name("1.0.0", bad)


class ClassifyTest(unittest.TestCase):
    def test_success_means_exists(self):
        self.assertEqual(releases.classify(0, "123456\n"), "exists")

    def test_404_means_missing(self):
        self.assertEqual(releases.classify(1, "gh: Not Found (HTTP 404)\n"), "missing")

    def test_other_failures_raise(self):
        for output in ("gh: Bad credentials (HTTP 401)", "gh: Server Error (HTTP 502)",
                       "error connecting to api.github.com", ""):
            with self.subTest(output=output), self.assertRaises(releases.ReleaseError):
                releases.classify(1, output)


class CliTest(unittest.TestCase):
    def test_name_prints_release(self):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = releases.main(["name", "1.0.0", "-r2"])
        self.assertEqual((rc, out.getvalue()), (0, "1.0.0-r2\n"))

    def test_name_rejection_exits_1(self):
        import contextlib, io
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(releases.main(["name", "../x"]), 1)


if __name__ == "__main__":
    unittest.main()
