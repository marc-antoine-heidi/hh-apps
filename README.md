# Heidi native design system

[Live site](https://marc-antoine-heidi.github.io/hh-apps/index.html).
GitHub Pages serves the committed HTML from `main`. Edit `_generator/` and native
fixtures, then rebuild; do not edit generated HTML or token values by hand.

## Refresh from iOS

Requirements: macOS, Xcode, XcodeGen, Python 3 and Pillow. Initialize the iOS
checkout's submodules. Choose an explicit simulator; captures use synthetic data.

```bash
xcrun simctl list devices available
python3 scripts/sync-ios.py --ios-repo /path/to/HeidiNative-iOS --device SIMULATOR_UDID
python3 scripts/build-site.py --ios-repo /path/to/HeidiNative-iOS
python3 -m http.server 8817
```

The export compiles the local `DesignSystem` package with the app's exact fonts
and asset catalogs. It exports actual Swift token values and captures public
components plus typography in five environments: light, dark, accessibility
text (AX1), right-to-left, and 768pt wide. Width changes use the same simulator;
they do not establish parity with iPad system chrome. Native captures establish
appearance at the recorded iOS version, not interaction or VoiceOver behavior.

`lib/ios/source.generated.json` records the iOS revision, source/resource/fixture
fingerprints and resolved package revisions. `public/ios/native/` holds native
PNG captures; `lib/ios/tokens.generated.json` contains compiled values. Font
software stays local: only Inter may be published; Exposure appears as rasters.

The site rebuild checks source freshness, capture integrity and agreement between
its parsed foundation values and compiled Swift. Added public components require
a specimen in `scripts/ios-preview/`; new token families require an export
contract. Named development-only values are excluded from the public catalogue.
Existing adoption audits and screen illustrations remain explicitly separate
from native package capture coverage. Notification content is preserved in
`_generator/notifications.html` because it was previously absent from the builder.

## Verify or publish

```bash
python3 scripts/sync-ios.py --check --ios-repo /path/to/HeidiNative-iOS
python3 scripts/sync-ios.py --verify
python3 _generator/check-design-system-site.py
xcrun swift-format lint --strict --recursive scripts/ios-preview
```

The portable checks run without Xcode or a private iOS clone. To enable GitHub
Actions, copy `_generator/design-system-integrity.workflow-example.yml` to
`.github/workflows/design-system-integrity.yml` using credentials with the
`workflow` scope. The current publishing token does not have that scope.
Publish verified updates directly to `main`; this site does not use draft PRs
or a separate approval step. Check light/dark and accessibility specimens locally
and retain the source revision in the export. Run the publishing helper from
`main` after refreshing the captures:

```bash
python3 _generator/publish-design-system-site.py --ios-repo /path/to/HeidiNative-iOS --publish
```

Older hashed CSS files remain available for cached HTML. Native image URLs include
their content hash to prevent new metadata pairing with an older cached capture.
The [generator guide](_generator/design-system-README.md) describes the existing
site structure, editorial overrides, font licensing and source audit rules.
