#!/usr/bin/env python3
"""Release naming and existence checks for the follow-upstream workflow.

  releases.py name <upstream-tag> [suffix]   print the release name
  releases.py state <owner/name> <release>   print "exists" or "missing"

Only a 404 from the API counts as "missing". Any other failure is an error:
publishing replaces a tag that has no release, so mistaking a network or
auth failure for "missing" could move the tag of a published release.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

TAG = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*")
SUFFIX = re.compile(r"(-[0-9A-Za-z][0-9A-Za-z.]*)?")


class ReleaseError(Exception):
    """A release name is unusable or its state could not be determined."""


def release_name(tag: str, suffix: str) -> str:
    if not TAG.fullmatch(tag) or ".." in tag:
        raise ReleaseError(f"not a usable upstream tag: {tag!r}")
    if not SUFFIX.fullmatch(suffix):
        raise ReleaseError(f"suffix must look like -r2: {suffix!r}")
    return tag + suffix


def classify(returncode: int, output: str) -> str:
    if returncode == 0:
        return "exists"
    if "HTTP 404" in output:
        return "missing"
    detail = output.strip() or f"gh exited {returncode}"
    raise ReleaseError(f"could not determine release state: {detail}")


def release_state(repo: str, name: str) -> str:
    proc = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/tags/{name}", "--jq", ".id"],
        capture_output=True,
        text=True,
    )
    return classify(proc.returncode, proc.stdout + proc.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MPVKit-lavfi release helpers.")
    sub = parser.add_subparsers(dest="command", required=True)
    # Suffixes start with "-" (e.g. -r2); a non-dash prefix character keeps
    # argparse from reading them as options.
    name = sub.add_parser(
        "name", help="print the release name for an upstream tag", prefix_chars="+"
    )
    name.add_argument("tag")
    name.add_argument("suffix", nargs="?", default="")
    state = sub.add_parser("state", help="print whether a release exists")
    state.add_argument("repo")
    state.add_argument("release")
    args = parser.parse_args(argv)
    try:
        if args.command == "name":
            print(release_name(args.tag, args.suffix))
        else:
            print(release_state(args.repo, release_name(args.release, "")))
    except ReleaseError as err:
        print(f"releases.py: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
