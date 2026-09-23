#!/usr/bin/env python3
"""Title and notes for one MPVKit-lavfi GitHub release."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def component_version(swift: str, case: str) -> str:
    """The version string main.swift gives a Library case (first match wins,
    which is the ``version`` switch)."""
    match = re.search(r"case \." + re.escape(case) + r'\b[^"]*?"([^"]+)"', swift)
    if not match:
        raise ValueError(f"no version for .{case} in main.swift")
    return match.group(1)


def _names(names: list[str]) -> str:
    return ", ".join(f"`{n}`" for n in names)


def render(*, upstream_tag: str, upstream_sha: str, release: str, repo: str,
           swift: str, report: dict) -> tuple[str, str]:
    mpv = component_version(swift, "libmpv")
    ffmpeg = component_version(swift, "FFmpeg")
    added = report.get("added", [])
    present = report.get("already_present", [])
    package = repo.split("/", 1)[1]

    title = f"{release} · mpv {mpv} · FFmpeg {ffmpeg}"
    lines: list[str] = []
    if not added:
        lines += [
            f"> **Redundant:** upstream MPVKit `{upstream_tag}` already enables every "
            "filter this repository adds. Switch back to "
            "[mpvkit/MPVKit](https://github.com/mpvkit/MPVKit).",
            "",
        ]
    lines += [
        f"Rebuild of [mpvkit/MPVKit `{upstream_tag}`]"
        f"(https://github.com/mpvkit/MPVKit/releases/tag/{upstream_tag}) "
        f"(upstream commit `{upstream_sha[:12]}`) with extra FFmpeg audio filters enabled.",
        "",
        f"- mpv: [`{mpv}`](https://github.com/mpv-player/mpv/tree/{mpv})",
        f"- FFmpeg: [`{ffmpeg}`](https://github.com/FFmpeg/FFmpeg/tree/{ffmpeg})",
        f"- Filters added: {_names(added) or 'none'}",
    ]
    if present:
        lines.append(f"- Already enabled upstream: {_names(present)}")
    lines += [
        "- Variant: LGPL only; slices for iOS, iOS Simulator and macOS",
        "",
        "Swift Package Manager:",
        "",
        "```swift",
        f'.package(url: "https://github.com/{repo}.git", exact: "{release}")',
        f'.product(name: "MPVKit", package: "{package}")',
        "```",
        "",
        "The build scripts used are this tag's tree. FFmpeg and mpv sources are "
        "the upstream tags linked above.",
    ]
    return title, "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render MPVKit-lavfi release notes.")
    parser.add_argument("--upstream-tag", required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--main-swift", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    title, body = render(
        upstream_tag=args.upstream_tag,
        upstream_sha=args.upstream_sha,
        release=args.release,
        repo=args.repo,
        swift=args.main_swift.read_text(),
        report=json.loads(args.report.read_text()),
    )
    args.out.write_text(body)
    print(title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
