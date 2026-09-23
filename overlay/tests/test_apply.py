from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import apply

OVERLAY = Path(__file__).resolve().parents[1]
FILTERS = OVERLAY / "filters.txt"

LIBS = ["Libmpv", "Libavcodec", "Libavdevice", "Libavformat",
        "Libavfilter", "Libavutil", "Libswresample", "Libswscale"]
URLS = "\n".join(
    f'            url: "{apply.UPSTREAM_RELEASES}\\(v)/{lib}.xcframework.zip",' for lib in LIBS
)
MAIN = f"""\
enum Library {{
    var targets: [String] {{
{URLS}
    }}
}}
private let ffmpegConfiguers = [
        "--disable-filters",
        "--enable-filter=aformat", "--enable-filter=anull", "--enable-filter=lut*",
        "--enable-filter=volume",
]
"""

TEMPLATE = """\
let package = Package(
    name: "MPVKit",
    products: [
        .library(
            name: "MPVKit",
            targets: ["_MPVKit"]
        ),
        .library(
            name: "MPVKit-GPL",
            targets: ["_MPVKit-GPL"]
        ),
    ],
    targets: [
        .target(
            name: "_MPVKit",
            dependencies: [
                "Libmpv", "_FFmpeg",
                .target(name: "Libluajit", condition: .when(platforms: [.macOS])),
            ],
            linkerSettings: [
                .linkedFramework("AVFoundation"),
            ]
        ),
        .target(
            name: "_MPVKit-GPL",
            dependencies: [
                "Libmpv-GPL", "_FFmpeg-GPL",
                .target(name: "Libluajit", condition: .when(platforms: [.macOS])),
            ],
            path: "Sources/_MPVKit-GPL"
        ),
        .target(
            name: "_FFmpeg-GPL",
            dependencies: ["Libavcodec-GPL"],
            path: "Sources/_FFmpeg-GPL"
        ),

        .binaryTarget(
            name: "Libmpv-GPL",
            url: "\\(Libmpv-GPL_url)",
            checksum: "\\(Libmpv-GPL_checksum)"
        ),
        .binaryTarget(
            name: "Libavcodec-GPL",
            url: "\\(Libavcodec-GPL_url)",
            checksum: "\\(Libavcodec-GPL_checksum)"
        ),
        //AUTO_GENERATE_TARGETS_BEGIN//
        //AUTO_GENERATE_TARGETS_END//
    ]
)
"""


class ReadFilterListTest(unittest.TestCase):
    def test_skips_comments_and_blank_lines(self):
        self.assertEqual(apply.read_filter_list("# c\n\nasplit\n  join  # x\n"), ["asplit", "join"])

    def test_shipped_list_is_the_ten_tap_filters(self):
        self.assertEqual(
            apply.read_filter_list(FILTERS.read_text()),
            ["asplit", "asetnsamples", "channelsplit", "bandpass", "join",
             "amultiply", "lowpass", "aeval", "ashowinfo", "anullsink"],
        )


class AddFiltersTest(unittest.TestCase):
    def test_inserts_after_anchor_with_its_indent_in_order(self):
        text, added, present = apply.add_filters(MAIN, ["asplit", "join"])
        self.assertEqual(added, ["asplit", "join"])
        self.assertEqual(present, [])
        self.assertIn(
            '        "--disable-filters",\n'
            '        "--enable-filter=asplit",\n'
            '        "--enable-filter=join",\n'
            '        "--enable-filter=aformat",',
            text,
        )

    def test_skips_names_enabled_exactly_or_by_glob(self):
        text, added, present = apply.add_filters(MAIN, ["anull", "lutrgb", "join"])
        self.assertEqual(added, ["join"])
        self.assertEqual(present, ["anull", "lutrgb"])
        self.assertEqual(text.count('"--enable-filter=anull"'), 1)

    def test_all_present_leaves_text_unchanged(self):
        text, added, present = apply.add_filters(MAIN, ["aformat", "volume"])
        self.assertEqual(text, MAIN)
        self.assertEqual(added, [])
        self.assertEqual(present, ["aformat", "volume"])

    def test_missing_anchor_fails(self):
        with self.assertRaises(apply.OverlayError):
            apply.add_filters(MAIN.replace('"--disable-filters",', ""), ["join"])

    def test_duplicated_anchor_fails(self):
        doubled = MAIN + '        "--disable-filters",\n'
        with self.assertRaises(apply.OverlayError):
            apply.add_filters(doubled, ["join"])


class RepointReleaseUrlsTest(unittest.TestCase):
    def test_replaces_all_eight(self):
        text = apply.repoint_release_urls(MAIN, "owner/fork")
        self.assertNotIn(apply.UPSTREAM_RELEASES, text)
        self.assertEqual(text.count("https://github.com/owner/fork/releases/download/"), 8)

    def test_wrong_count_fails(self):
        with self.assertRaises(apply.OverlayError):
            apply.repoint_release_urls(MAIN + apply.UPSTREAM_RELEASES, "owner/fork")

    def test_rejects_a_slug_that_is_not_owner_slash_name(self):
        for bad in ("owner", "owner/fork/extra", "owner/fo rk", "../x", ""):
            with self.subTest(bad=bad), self.assertRaises(apply.OverlayError):
                apply.repoint_release_urls(MAIN, bad)


class DropGplTest(unittest.TestCase):
    def test_removes_every_gpl_block_and_keeps_the_rest(self):
        text = apply.drop_gpl(TEMPLATE)
        self.assertNotIn("-GPL", text)
        self.assertIn('name: "MPVKit",', text)
        self.assertIn('name: "_MPVKit",', text)
        self.assertIn('.target(name: "Libluajit", condition: .when(platforms: [.macOS])),', text)
        self.assertIn("//AUTO_GENERATE_TARGETS_END//", text)

    def test_removes_gpl_binary_targets_upstream_adds_later(self):
        extra = TEMPLATE.replace(
            "        //AUTO_GENERATE_TARGETS_BEGIN//",
            '        .binaryTarget(\n            name: "Libsmbclient-GPL",\n'
            '            url: "\\(Libsmbclient-GPL_url)",\n'
            '            checksum: "\\(Libsmbclient-GPL_checksum)"\n        ),\n'
            "        //AUTO_GENERATE_TARGETS_BEGIN//",
        )
        self.assertNotIn("-GPL", apply.drop_gpl(extra))

    def test_missing_required_gpl_block_fails(self):
        no_ffmpeg_gpl = TEMPLATE.replace('name: "_FFmpeg-GPL"', 'name: "_Other-GPL"')
        with self.assertRaises(apply.OverlayError):
            apply.drop_gpl(no_ffmpeg_gpl)

    def test_gpl_mention_outside_a_block_fails(self):
        with self.assertRaises(apply.OverlayError):
            apply.drop_gpl(TEMPLATE + "// see MPVKit-GPL\n")


class MainTest(unittest.TestCase):
    def _tree(self, root: Path, main: str = MAIN, template: str = TEMPLATE) -> Path:
        tree = root / "tree"
        (tree / apply.MAIN_SWIFT).parent.mkdir(parents=True)
        (tree / apply.PACKAGE_TEMPLATE).parent.mkdir(parents=True)
        (tree / apply.MAIN_SWIFT).write_text(main)
        (tree / apply.PACKAGE_TEMPLATE).write_text(template)
        return tree

    def test_writes_both_files_and_the_report(self):
        with tempfile.TemporaryDirectory() as d:
            tree = self._tree(Path(d))
            report = Path(d) / "report.json"
            rc = apply.main(["--tree", str(tree), "--filters", str(FILTERS),
                             "--repo", "owner/fork", "--report", str(report)])
            self.assertEqual(rc, 0)
            swift = (tree / apply.MAIN_SWIFT).read_text()
            self.assertIn('"--enable-filter=ashowinfo",', swift)
            self.assertNotIn(apply.UPSTREAM_RELEASES, swift)
            self.assertNotIn("-GPL", (tree / apply.PACKAGE_TEMPLATE).read_text())
            self.assertEqual(len(json.loads(report.read_text())["added"]), 10)

    def test_failure_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            broken = TEMPLATE.replace('name: "MPVKit-GPL"', 'name: "Renamed"')
            tree = self._tree(Path(d), template=broken)
            report = Path(d) / "report.json"
            rc = apply.main(["--tree", str(tree), "--filters", str(FILTERS),
                             "--repo", "owner/fork", "--report", str(report)])
            self.assertEqual(rc, 1)
            self.assertEqual((tree / apply.MAIN_SWIFT).read_text(), MAIN)
            self.assertFalse(report.exists())


@unittest.skipUnless(os.environ.get("MPVKIT_TREE"), "set MPVKIT_TREE to an upstream MPVKit checkout")
class UpstreamTreeTest(unittest.TestCase):
    def test_overlay_applies_to_the_real_upstream_files(self):
        src = Path(os.environ["MPVKIT_TREE"])
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "tree"
            for rel in (apply.MAIN_SWIFT, apply.PACKAGE_TEMPLATE):
                (tree / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src / rel, tree / rel)
            report = Path(d) / "report.json"
            rc = apply.main(["--tree", str(tree), "--filters", str(FILTERS),
                             "--repo", "owner/fork", "--report", str(report)])
            self.assertEqual(rc, 0)
            swift = (tree / apply.MAIN_SWIFT).read_text()
            enabled = apply.enabled_filters(swift)
            import fnmatch
            for name in apply.read_filter_list(FILTERS.read_text()):
                self.assertTrue(any(fnmatch.fnmatchcase(name, p) for p in enabled), name)
            self.assertNotIn(apply.UPSTREAM_RELEASES, swift)
            self.assertNotIn("-GPL", (tree / apply.PACKAGE_TEMPLATE).read_text())


if __name__ == "__main__":
    unittest.main()
