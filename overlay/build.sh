#!/usr/bin/env bash
# Build and verify one MPVKit-lavfi release, locally or in CI.
#
#   overlay/build.sh <upstream-tag> <release> <owner/repo> <workdir>
#
# Clones upstream MPVKit at <upstream-tag>, applies the overlay, builds the
# LGPL iOS, iOS Simulator and macOS slices with upstream's own build
# scripts, then verifies the artifacts. Leaves the patched tree (with the
# generated Package.swift at its root) in <workdir>/upstream for publish.sh.
set -euo pipefail

tag=$1 release=$2 repo=$3 work=$4
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$work"
work="$(cd "$work" && pwd)"
tree="$work/upstream"

rm -rf "$tree"
git clone --quiet --depth 1 --branch "$tag" https://github.com/mpvkit/MPVKit.git "$tree"
git -C "$tree" rev-parse HEAD > "$work/upstream-sha"

# Unit tests, including the one that applies the overlay to this tag's files.
MPVKIT_TREE="$tree" python3 -m unittest discover -s "$here/tests" -t "$here"

python3 "$here/apply.py" --tree "$tree" --filters "$here/filters.txt" \
  --repo "$repo" --report "$work/apply-report.json"

# Upstream builds with meson 1.4.2; keep it off the system Python.
venv="$work/venv"
if [ ! -x "$venv/bin/meson" ]; then
  python3 -m venv "$venv"
  "$venv/bin/pip" install --quiet 'meson==1.4.2'
fi
export PATH="$venv/bin:$PATH"

(cd "$tree" && make build platform=ios,macos "version=$release")

rel="$tree/dist/release"
python3 "$here/verify.py" symbols --zip "$rel/Libavfilter.xcframework.zip" \
  --filters "$here/filters.txt"
cp "$rel/Package.swift" "$tree/Package.swift"
python3 "$here/verify.py" manifest --package "$tree/Package.swift" \
  --repo "$repo" --release "$release"
(cd "$tree" && swift package dump-package > /dev/null)

mpv="$(find "$tree/dist" -path '*/macos/thin/arm64/bin/mpv' -type f | head -n 1)"
if [ -z "$mpv" ]; then
  echo "build.sh: no macOS arm64 mpv binary under $tree/dist" >&2
  exit 1
fi
python3 "$here/verify.py" smoke --mpv "$mpv" --graph "$here/smoke/tap-default.lavfi"
