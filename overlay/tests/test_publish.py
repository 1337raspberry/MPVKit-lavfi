from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

OVERLAY = Path(__file__).resolve().parents[1]
PUBLISH = OVERLAY / "publish.sh"
REPO = "owner/fork"
TOKEN = "test-token"

MAIN_SWIFT = """\
enum Library: String, CaseIterable {
    case libmpv, FFmpeg
    var version: String {
        switch self {
        case .libmpv:
            return "v0.41.0"
        case .FFmpeg:
            return "n8.1.2"
        }
    }
}
"""

# Stands in for gh: `gh api .../releases/tags/<R>` answers from a marker
# file, `gh release create` records its arguments.
FAKE_GH = """\
#!/usr/bin/env bash
state="$FAKE_GH_DIR"
case "$1" in
  api)
    if [ -e "$state/release-exists" ]; then echo 123; exit 0; fi
    echo 'gh: Not Found (HTTP 404)' >&2; exit 1 ;;
  release)
    printf '%s\\n' "$@" > "$state/release-args"; exit 0 ;;
esac
echo "unexpected gh call: $*" >&2; exit 2
"""


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


class PublishTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.work = root / "work"
        self.tree = self.work / "upstream"
        self.remote = root / "remote.git"
        self.bin = root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

        ident = {
            "GIT_AUTHOR_NAME": "Upstream", "GIT_AUTHOR_EMAIL": "upstream@example.com",
            "GIT_COMMITTER_NAME": "Upstream", "GIT_COMMITTER_EMAIL": "upstream@example.com",
        }
        setup_env = {**os.environ, **ident}
        # An upstream checkout as `git clone --branch <tag>` leaves it: the
        # tag's commit checked out and the tag itself present locally.
        files = {
            ".github/workflows/ci.yml": "on: push\n",
            "Package.swift": "// upstream manifest\n",
            "Sources/BuildScripts/XCFrameworkBuild/main.swift": MAIN_SWIFT,
            ".gitignore": "dist/\n",
        }
        for rel, text in files.items():
            (self.tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.tree / rel).write_text(text)
        git(self.tree.parent, "init", "-q", "-b", "main", str(self.tree))
        git(self.tree, "add", "-A", env=setup_env)
        git(self.tree, "commit", "-q", "-m", "upstream 1.0.0", env=setup_env)
        git(self.tree, "tag", "1.0.0")
        (self.work / "upstream-sha").write_text(git(self.tree, "rev-parse", "HEAD") + "\n")
        (self.work / "apply-report.json").write_text('{"added": ["join"], "already_present": []}\n')

        # What build.sh leaves behind: an overlay edit, the generated
        # manifest and the release assets.
        (self.tree / "Package.swift").write_text("// generated manifest\n")
        release = self.tree / "dist" / "release"
        release.mkdir(parents=True)
        (release / "Libmpv.xcframework.zip").write_text("zip")
        (release / "Libmpv.xcframework.checksum.txt").write_text("a" * 64 + "\n")

        git(root, "init", "-q", "--bare", str(self.remote))
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_DIR": str(root),
            "GH_TOKEN": TOKEN,
            # Send publish.sh's GitHub remote to the local bare repository.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.remote}.insteadOf",
            "GIT_CONFIG_VALUE_0": f"https://x-access-token:{TOKEN}@github.com/{REPO}.git",
        }
        self.root = root

    def tearDown(self):
        self._tmp.cleanup()

    def publish(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(PUBLISH), "1.0.0", "1.0.0", REPO, str(self.work)],
            capture_output=True, text=True, env=self.env,
        )

    def remote_tag(self) -> str:
        return git(self.remote, "rev-parse", "--verify", "--quiet", "refs/tags/1.0.0^{commit}")

    def test_publishes_a_parentless_snapshot_tag_and_release(self):
        proc = self.publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        commit = self.remote_tag()
        self.assertEqual(git(self.remote, "rev-list", "--parents", "-n", "1", commit), commit)
        files = git(self.remote, "ls-tree", "-r", "--name-only", commit).splitlines()
        self.assertNotIn(".github/workflows/ci.yml", files)
        self.assertFalse(any(f.startswith("dist/") for f in files))
        self.assertEqual(git(self.remote, "show", f"{commit}:Package.swift"), "// generated manifest")
        self.assertEqual(git(self.remote, "log", "-1", "--format=%s|%an", commit),
                         "mpvkit 1.0.0 + lavfi audio filters|github-actions[bot]")
        args = (self.root / "release-args").read_text().splitlines()
        self.assertIn("--verify-tag", args)
        self.assertIn("dist/release/Libmpv.xcframework.zip", args)
        self.assertIn("dist/release/Libmpv.xcframework.checksum.txt", args)

    def test_replaces_a_tag_left_without_a_release(self):
        orphan = git(self.tree, "rev-parse", "HEAD")
        git(self.tree, "push", "-q", str(self.remote), f"{orphan}:refs/tags/1.0.0")
        proc = self.publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotEqual(self.remote_tag(), orphan)

    def test_refuses_when_the_release_exists(self):
        (self.root / "release-exists").touch()
        proc = self.publish()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("already exists", proc.stderr)
        self.assertEqual(git(self.remote, "tag", "--list"), "")


if __name__ == "__main__":
    unittest.main()
