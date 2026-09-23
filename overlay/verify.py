#!/usr/bin/env python3
"""Checks run on a finished MPVKit-lavfi build before anything is published.

  symbols   every filter in filters.txt is compiled into every slice and
            architecture of the Libavfilter.xcframework.zip being published
  manifest  the generated Package.swift points the Libmpv and FFmpeg binary
            targets at this repository's release and names no GPL targets
  smoke     the macOS mpv CLI runs the default ramus spectrum-tap graph over
            a sine and prints the expected run of ashowinfo lines
"""
from __future__ import annotations

import argparse
import array
import math
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from apply import UPSTREAM_RELEASES, read_filter_list

LGPL_TARGETS = (
    "Libmpv", "Libavcodec", "Libavdevice", "Libavformat",
    "Libavfilter", "Libavutil", "Libswresample", "Libswscale",
)
MIN_SLICES = 3  # iOS device, iOS simulator, macOS
TAP_BANKS = 2  # the tap prints one line per bank per frame
TAP_FPS = 60
SMOKE_SECONDS = 3.0
SMOKE_MIN_FRACTION = 0.8  # the tail after end of file is not drained
TAP_LINE = re.compile(r"Parsed_ashowinfo_\d+: n:\d+")
GRAPH_REJECTIONS = (
    "parsing the filter graph failed",
    "Audio filter initialized failed",
    "because it has failed",
)


class VerifyError(Exception):
    """A built artifact does not meet the release requirements."""


def missing_filters(symbols: set[str], filters: list[str]) -> list[str]:
    return [
        f for f in filters
        if not any(f"_ff_{kind}_{f}" in symbols for kind in ("af", "asink", "asrc"))
    ]


def parse_nm_names(output: str) -> set[str]:
    """Symbol names from `nm -j`, without its `archive(member.o):` headers."""
    return {
        line.strip() for line in output.splitlines()
        if line.strip() and not line.rstrip().endswith(":")
    }


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def check_symbols(zip_path: Path, filters: list[str]) -> list[str]:
    checked = []
    with tempfile.TemporaryDirectory() as tmp:
        # unzip (not zipfile) keeps the framework's Versions symlinks intact.
        subprocess.run(["unzip", "-q", str(zip_path), "-d", tmp], check=True)
        frameworks = list(Path(tmp).glob("*.xcframework"))
        if len(frameworks) != 1:
            raise VerifyError(f"{zip_path.name}: expected one .xcframework, found {len(frameworks)}")
        lib = frameworks[0].name.split(".")[0]
        binaries = sorted(frameworks[0].glob(f"*/{lib}.framework/{lib}"))
        if len(binaries) < MIN_SLICES:
            raise VerifyError(f"{zip_path.name}: expected {MIN_SLICES}+ slices, found {len(binaries)}")
        for binary in binaries:
            for arch in _run(["lipo", "-archs", str(binary)]).split():
                label = f"{binary.parent.parent.name}/{arch}"
                symbols = parse_nm_names(_run(["nm", "-j", "-arch", arch, str(binary)]))
                missing = missing_filters(symbols, filters)
                if missing:
                    raise VerifyError(f"{label} lacks {' '.join(missing)}")
                checked.append(label)
    return checked


def _binary_target(package: str, name: str) -> tuple[str, str] | None:
    match = re.search(
        r'\.binaryTarget\(\s*name:\s*"' + re.escape(name)
        + r'",\s*url:\s*"([^"]*)",\s*checksum:\s*"([^"]*)"',
        package,
    )
    return (match.group(1), match.group(2)) if match else None


def manifest_problems(package: str, repo: str, release: str) -> list[str]:
    problems = []
    if "-GPL" in package:
        problems.append("mentions a -GPL target")
    if UPSTREAM_RELEASES in package:
        problems.append("still points at mpvkit/MPVKit release downloads")
    for name in LGPL_TARGETS:
        found = _binary_target(package, name)
        want = f"https://github.com/{repo}/releases/download/{release}/{name}.xcframework.zip"
        if found is None:
            problems.append(f"no binaryTarget {name}")
        elif found[0] != want:
            problems.append(f"{name} url is {found[0]}, want {want}")
        elif not re.fullmatch(r"[0-9a-f]{64}", found[1]):
            problems.append(f"{name} checksum {found[1]!r} is not a sha256")
    return problems


def write_sine_wav(path: Path, seconds: float, rate: int = 44100, freq: float = 1000.0) -> None:
    samples = array.array("h")
    for i in range(int(seconds * rate)):
        value = int(12000 * math.sin(2 * math.pi * freq * i / rate))
        samples.append(value)
        samples.append(value)
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())


def count_tap_lines(output: str) -> int:
    return len(TAP_LINE.findall(output))


def expected_tap_lines(seconds: float) -> int:
    return int(TAP_BANKS * TAP_FPS * seconds)


def smoke_verdict(output: str, returncode: int, seconds: float) -> tuple[bool, str]:
    for message in GRAPH_REJECTIONS:
        if message in output:
            return False, f"mpv rejected the tap graph ({message!r})"
    if returncode != 0:
        return False, f"mpv exited {returncode}"
    got, want = count_tap_lines(output), expected_tap_lines(seconds)
    if got < SMOKE_MIN_FRACTION * want:
        return False, f"{got} ashowinfo lines, expected about {want}"
    return True, f"{got} ashowinfo lines (expected about {want})"


def run_smoke(mpv: Path, graph: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "sine.wav"
        write_sine_wav(wav, SMOKE_SECONDS)
        proc = subprocess.run(
            [str(mpv), "--no-config", "--no-video", "--ao=null", "--msg-level=all=v",
             f"--af=lavfi=[{graph.strip()}]", str(wav)],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
    ok, message = smoke_verdict(proc.stdout + proc.stderr, proc.returncode, SMOKE_SECONDS)
    if not ok:
        raise VerifyError(message)
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an MPVKit-lavfi build.")
    sub = parser.add_subparsers(dest="command", required=True)
    symbols = sub.add_parser("symbols")
    symbols.add_argument("--zip", required=True, type=Path)
    symbols.add_argument("--filters", required=True, type=Path)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("--package", required=True, type=Path)
    manifest.add_argument("--repo", required=True)
    manifest.add_argument("--release", required=True)
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--mpv", required=True, type=Path)
    smoke.add_argument("--graph", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "symbols":
            filters = read_filter_list(args.filters.read_text())
            checked = check_symbols(args.zip, filters)
            print(f"verify.py: {len(filters)} filters in {', '.join(checked)}")
        elif args.command == "manifest":
            problems = manifest_problems(args.package.read_text(), args.repo, args.release)
            if problems:
                raise VerifyError("Package.swift " + "; ".join(problems))
            print("verify.py: Package.swift ok")
        else:
            print(f"verify.py: smoke {run_smoke(args.mpv, args.graph.read_text())}")
    except (VerifyError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as err:
        print(f"verify.py: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
