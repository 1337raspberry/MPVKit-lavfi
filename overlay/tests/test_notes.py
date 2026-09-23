from __future__ import annotations

import unittest

import notes

SWIFT = """\
enum Library: String, CaseIterable {
    case libmpv, FFmpeg, libass
    var version: String {
        switch self {
        case .libmpv:
            return "v0.41.0"
        case .FFmpeg:
            return "n9.0.0"
        case .libass:
            return "0.17.5"
        }
    }
    var url: String {
        switch self {
        case .libmpv:
            return "https://github.com/mpv-player/mpv"
        }
    }
}
"""

ARGS = dict(upstream_tag="1.0.0", upstream_sha="0123456789abcdef0123", release="1.0.0",
            repo="owner/MPVKit-lavfi", swift=SWIFT)


class ComponentVersionTest(unittest.TestCase):
    def test_reads_the_version_switch(self):
        self.assertEqual(notes.component_version(SWIFT, "libmpv"), "v0.41.0")
        self.assertEqual(notes.component_version(SWIFT, "FFmpeg"), "n9.0.0")

    def test_unknown_case_raises(self):
        with self.assertRaises(ValueError):
            notes.component_version(SWIFT, "libfoo")


class RenderTest(unittest.TestCase):
    def test_title_and_body(self):
        title, body = notes.render(report={"added": ["asplit", "join"], "already_present": []}, **ARGS)
        self.assertEqual(title, "1.0.0 · mpv v0.41.0 · FFmpeg n9.0.0")
        self.assertIn("https://github.com/mpvkit/MPVKit/releases/tag/1.0.0", body)
        self.assertIn("`0123456789ab`", body)
        self.assertIn("Filters added: `asplit`, `join`", body)
        self.assertIn('.package(url: "https://github.com/owner/MPVKit-lavfi.git", exact: "1.0.0")', body)
        self.assertIn('.product(name: "MPVKit", package: "MPVKit-lavfi")', body)
        self.assertNotIn("Redundant", body)

    def test_redundant_banner_when_nothing_was_added(self):
        _, body = notes.render(report={"added": [], "already_present": ["asplit"]}, **ARGS)
        self.assertTrue(body.startswith("> **Redundant:**"))
        self.assertIn("Already enabled upstream: `asplit`", body)


if __name__ == "__main__":
    unittest.main()
