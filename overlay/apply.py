#!/usr/bin/env python3
"""Apply the MPVKit-lavfi overlay to an upstream MPVKit checkout.

Three edits, each asserting the text it relies on so that an upstream
restructure fails the build instead of silently producing an unmodified
package:

1. enable the extra FFmpeg filters listed in filters.txt;
2. point the Libmpv and FFmpeg binary-target URLs at this repository's
   releases;
3. remove the GPL product, targets and binary targets from the package
   template, since only the LGPL variant is built.

Every edit is computed before anything is written, so a failure leaves the
tree untouched. A JSON report of the filters added (and those upstream
already enables) is written for the release notes.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

MAIN_SWIFT = Path("Sources/BuildScripts/XCFrameworkBuild/main.swift")
PACKAGE_TEMPLATE = Path("docs/Package.template.swift")

FILTER_ANCHOR = '"--disable-filters",'
UPSTREAM_RELEASES = "https://github.com/mpvkit/MPVKit/releases/download/"
# Libmpv plus the seven FFmpeg libraries MPVKit builds from source.
EXPECTED_RELEASE_URLS = 8
REPO_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

GPL_BLOCK = re.compile(
    r'^[ \t]*\.(library|target|binaryTarget)\(\s*name:\s*"([^"]*-GPL)"', re.MULTILINE
)
REQUIRED_GPL_BLOCKS = {
    ("library", "MPVKit-GPL"),
    ("target", "_MPVKit-GPL"),
    ("target", "_FFmpeg-GPL"),
}
BLOCK_TAIL = re.compile(r",?[ \t]*\n?")


class OverlayError(Exception):
    """Text the overlay relies on is missing, duplicated or malformed."""


def read_filter_list(text: str) -> list[str]:
    names = []
    for raw in text.splitlines():
        name = raw.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def enabled_filters(swift: str) -> list[str]:
    """Every pattern passed as --enable-filter=... anywhere in main.swift."""
    return re.findall(r'--enable-filter=([^"\s,]+)', swift)


def add_filters(swift: str, wanted: list[str]) -> tuple[str, list[str], list[str]]:
    """Insert an --enable-filter line per wanted filter after --disable-filters.

    A wanted name counts as already enabled when any existing pattern
    matches it (upstream uses globs such as ``lut*``). Returns the new text,
    the names added and the names already enabled.
    """
    lines = swift.splitlines(keepends=True)
    anchors = [i for i, line in enumerate(lines) if FILTER_ANCHOR in line]
    if len(anchors) != 1:
        raise OverlayError(
            f"expected one {FILTER_ANCHOR} line in main.swift, found {len(anchors)}"
        )
    existing = enabled_filters(swift)
    present = [n for n in wanted if any(fnmatch.fnmatchcase(n, p) for p in existing)]
    added = [n for n in wanted if n not in present]
    if added:
        anchor = lines[anchors[0]]
        indent = anchor[: len(anchor) - len(anchor.lstrip())]
        lines.insert(
            anchors[0] + 1,
            "".join(f'{indent}"--enable-filter={n}",\n' for n in added),
        )
    return "".join(lines), added, present


def repoint_release_urls(swift: str, repo: str) -> str:
    if not REPO_SLUG.fullmatch(repo) or ".." in repo:
        raise OverlayError(f"not an owner/name repository slug: {repo!r}")
    count = swift.count(UPSTREAM_RELEASES)
    if count != EXPECTED_RELEASE_URLS:
        raise OverlayError(
            f"expected {EXPECTED_RELEASE_URLS} {UPSTREAM_RELEASES} URLs in main.swift, found {count}"
        )
    return swift.replace(UPSTREAM_RELEASES, f"https://github.com/{repo}/releases/download/")


def _block_end(text: str, open_paren: int) -> int:
    """Index just past the call opened at open_paren, its comma and newline."""
    depth = 0
    for i in range(open_paren, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return BLOCK_TAIL.match(text, i + 1).end()
    raise OverlayError("unbalanced parentheses in the package template")


def drop_gpl(template: str) -> str:
    found = [(m.group(1), m.group(2), m.start()) for m in GPL_BLOCK.finditer(template)]
    missing = REQUIRED_GPL_BLOCKS - {(kind, name) for kind, name, _ in found}
    if missing:
        names = ", ".join(f".{kind}({name})" for kind, name in sorted(missing))
        raise OverlayError(f"package template no longer has {names}")
    for _, _, start in reversed(found):
        end = _block_end(template, template.index("(", start))
        template = template[:start] + template[end:]
    if "-GPL" in template:
        raise OverlayError("GPL references remain in the package template after removal")
    return template


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the MPVKit-lavfi overlay.")
    parser.add_argument("--tree", required=True, type=Path, help="upstream MPVKit checkout")
    parser.add_argument("--filters", required=True, type=Path, help="filters.txt")
    parser.add_argument("--repo", required=True, help="owner/name hosting the release binaries")
    parser.add_argument("--report", required=True, type=Path, help="JSON report to write")
    args = parser.parse_args(argv)

    main_path = args.tree / MAIN_SWIFT
    template_path = args.tree / PACKAGE_TEMPLATE
    try:
        wanted = read_filter_list(args.filters.read_text())
        if not wanted:
            raise OverlayError(f"{args.filters} lists no filters")
        swift, added, present = add_filters(main_path.read_text(), wanted)
        swift = repoint_release_urls(swift, args.repo)
        template = drop_gpl(template_path.read_text())
    except (OverlayError, OSError) as err:
        print(f"apply.py: {err}", file=sys.stderr)
        return 1

    main_path.write_text(swift)
    template_path.write_text(template)
    args.report.write_text(
        json.dumps({"added": added, "already_present": present}, indent=2) + "\n"
    )
    print(f"apply.py: added {len(added)} filter(s): {' '.join(added) or '(none)'}")
    if present:
        print(f"apply.py: already enabled upstream: {' '.join(present)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
