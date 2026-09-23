from __future__ import annotations

import os
import tempfile
import unittest
import wave
from pathlib import Path

import verify

OVERLAY = Path(__file__).resolve().parents[1]
SHA = "a" * 64


def manifest(repo="owner/fork", release="1.0.0", extra="", url_for=None, checksum=SHA):
    blocks = []
    for name in verify.LGPL_TARGETS:
        url = (url_for or {}).get(name, f"https://github.com/{repo}/releases/download/{release}/{name}.xcframework.zip")
        blocks.append(
            f'        .binaryTarget(\n            name: "{name}",\n'
            f'            url: "{url}",\n            checksum: "{checksum}"\n        ),'
        )
    return "let package = Package(\n    targets: [\n" + "\n".join(blocks) + extra + "\n    ]\n)\n"


class SymbolsTest(unittest.TestCase):
    def test_missing_filters_accepts_af_and_asink_symbols(self):
        symbols = {"_ff_af_bandpass", "_ff_asink_anullsink", "_ff_af_aformat"}
        self.assertEqual(
            verify.missing_filters(symbols, ["bandpass", "anullsink", "join"]), ["join"]
        )

    def test_parse_nm_names_drops_member_headers(self):
        out = "\n/x/Libavfilter(af_biquads.o):\n_ff_af_bandpass\n_ff_af_lowpass\n\n"
        self.assertEqual(verify.parse_nm_names(out), {"_ff_af_bandpass", "_ff_af_lowpass"})


class ManifestTest(unittest.TestCase):
    def test_good_manifest_has_no_problems(self):
        self.assertEqual(verify.manifest_problems(manifest(), "owner/fork", "1.0.0"), [])

    def test_gpl_and_upstream_urls_are_problems(self):
        bad = manifest(extra='\n        .binaryTarget(name: "Libmpv-GPL", url: "'
                             + verify.UPSTREAM_RELEASES + 'x", checksum: "")')
        problems = verify.manifest_problems(bad, "owner/fork", "1.0.0")
        self.assertTrue(any("GPL" in p for p in problems))
        self.assertTrue(any("mpvkit/MPVKit" in p for p in problems))

    def test_wrong_release_url_is_a_problem(self):
        bad = manifest(url_for={"Libavfilter": "https://github.com/owner/fork/releases/download/0.9/Libavfilter.xcframework.zip"})
        problems = verify.manifest_problems(bad, "owner/fork", "1.0.0")
        self.assertEqual(len(problems), 1)
        self.assertIn("Libavfilter", problems[0])

    def test_missing_target_and_bad_checksum_are_problems(self):
        text = manifest(checksum="").replace('name: "Libswscale"', 'name: "Other"')
        problems = verify.manifest_problems(text, "owner/fork", "1.0.0")
        self.assertTrue(any("no binaryTarget Libswscale" in p for p in problems))
        self.assertTrue(any("checksum" in p for p in problems))


class SmokeTest(unittest.TestCase):
    LINE = "[ffmpeg] Parsed_ashowinfo_{i}: n:{n} pts:{n} pts_time:0.1 fmt:s16p\n"

    def output(self, count: int) -> str:
        return "".join(self.LINE.format(i=12 + (n % 2), n=n) for n in range(count))

    def test_expected_is_two_banks_at_sixty_fps(self):
        self.assertEqual(verify.expected_tap_lines(3.0), 360)

    def test_counts_only_frame_lines(self):
        side = "[ffmpeg] Parsed_ashowinfo_12:   side data - replaygain\n"
        self.assertEqual(verify.count_tap_lines(self.output(5) + side), 5)

    def test_enough_lines_pass(self):
        ok, _ = verify.smoke_verdict(self.output(300), 0, 3.0)
        self.assertTrue(ok)

    def test_too_few_lines_fail(self):
        ok, msg = verify.smoke_verdict(self.output(100), 0, 3.0)
        self.assertFalse(ok)
        self.assertIn("100", msg)

    def test_rejected_graph_fails_even_with_exit_0(self):
        out = self.output(360) + "[lavfi] parsing the filter graph failed\n"
        ok, msg = verify.smoke_verdict(out, 0, 3.0)
        self.assertFalse(ok)
        self.assertIn("rejected", msg)

    def test_disabled_filter_fails_even_with_exit_0(self):
        out = "[af] Disabling filter lavfi.00 because it has failed.\n"
        self.assertFalse(verify.smoke_verdict(out, 0, 3.0)[0])

    def test_nonzero_exit_fails(self):
        self.assertFalse(verify.smoke_verdict(self.output(360), 2, 3.0)[0])

    def test_sine_wav_shape(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.wav"
            verify.write_sine_wav(path, 0.5)
            with wave.open(str(path)) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()),
                                 (2, 2, 44100, 22050))


@unittest.skipUnless(os.environ.get("MPV_BIN"), "set MPV_BIN to an mpv CLI built with the filters")
class RealMpvTest(unittest.TestCase):
    def test_default_graph_runs(self):
        graph = (OVERLAY / "smoke" / "tap-default.lavfi").read_text()
        print(verify.run_smoke(Path(os.environ["MPV_BIN"]), graph))


if __name__ == "__main__":
    unittest.main()
