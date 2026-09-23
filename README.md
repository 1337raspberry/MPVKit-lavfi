# MPVKit-lavfi

[MPVKit](https://github.com/mpvkit/MPVKit) rebuilt with extra FFmpeg audio
filters, for apps that run lavfi analysis graphs through libmpv on iOS.

Upstream MPVKit configures FFmpeg with `--disable-filters` and an allowlist.
This repository enables the filters in
[`overlay/filters.txt`](overlay/filters.txt) on top of that list and changes
nothing else. It was made for the live spectrum visualiser in
[ramus](https://github.com/1337raspberry/ramus).

## How it works

- A weekly workflow checks upstream's latest stable release. When this
  repository has no release of that name yet, it clones upstream at the tag,
  applies [`overlay/apply.py`](overlay/apply.py), and builds with upstream's
  own `make build platform=ios,macos`.
- Before publishing, it checks that every filter is compiled into every slice,
  that the package manifest points at this repository's release, and that the
  macOS `mpv` binary runs a real analysis graph.
- Each release is one snapshot commit (upstream's files at the tag, the
  overlay edits and the generated `Package.swift`), tagged with upstream's
  version.
- Only the LGPL variant is built, with slices for iOS, the iOS Simulator and
  macOS. Dependencies other than FFmpeg and mpv are upstream's prebuilt
  binaries.

## Use it

```swift
.package(url: "https://github.com/1337raspberry/MPVKit-lavfi.git", exact: "1.0.0")
```

```swift
.product(name: "MPVKit", package: "MPVKit-lavfi")
```

Pin exact versions. A rebuild of the same upstream version gets a suffix
(`1.0.0-r2`); published tags never move.

## Licence

LGPL-3.0, as upstream. Each release tag contains the exact build scripts
used; FFmpeg and mpv sources are the upstream tags named in its release notes.
All credit for the build system goes to the MPVKit authors.
