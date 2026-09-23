#!/usr/bin/env bash
# Publish a release that build.sh produced.
#
#   overlay/publish.sh <upstream-tag> <release> <owner/repo> <workdir>
#
# Needs GH_TOKEN with contents:write on <owner/repo>. The release commit is a
# parentless snapshot of upstream's tracked files at <upstream-tag>, minus
# .github/, plus the overlay edits and the generated Package.swift. It
# carries no upstream history and no workflow files, so upstream's scheduled
# workflows never land in this repository.
set -euo pipefail

tag=$1 release=$2 repo=$3 work=$4
here="$(cd "$(dirname "$0")" && pwd)"
tree="$work/upstream"
sha="$(cat "$work/upstream-sha")"
remote="https://x-access-token:${GH_TOKEN}@github.com/${repo}.git"

state="$(python3 "$here/releases.py" state "$repo" "$release")"
if [ "$state" != missing ]; then
  echo "publish.sh: release $release already exists; nothing to publish" >&2
  exit 1
fi

cd "$tree"
git rm -r --quiet --cached .github
git add -u
tree_id="$(git write-tree)"
export GIT_AUTHOR_NAME='github-actions[bot]'
export GIT_AUTHOR_EMAIL='41898282+github-actions[bot]@users.noreply.github.com'
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
commit="$(git commit-tree "$tree_id" -m "mpvkit $tag + lavfi audio filters")"

if git ls-remote --exit-code --tags "$remote" "refs/tags/$release" > /dev/null; then
  # The release is confirmed missing above, so this tag is left over from a
  # publish that failed after pushing it. Nothing can depend on it: its
  # binary URLs never resolved.
  git push --quiet "$remote" ":refs/tags/$release"
fi
# Push the commit straight to the tag ref: the upstream clone already has a
# local tag of the same name (upstream's own), which must stay untouched.
git push --quiet "$remote" "$commit:refs/tags/$release"

title="$(python3 "$here/notes.py" --upstream-tag "$tag" --upstream-sha "$sha" \
  --release "$release" --repo "$repo" \
  --main-swift "$tree/Sources/BuildScripts/XCFrameworkBuild/main.swift" \
  --report "$work/apply-report.json" --out "$work/notes.md")"
gh release create "$release" --repo "$repo" --verify-tag --title "$title" \
  --notes-file "$work/notes.md" dist/release/*.zip dist/release/*.txt
