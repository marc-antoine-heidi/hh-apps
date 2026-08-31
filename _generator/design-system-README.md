# Design-system site (storybook for the native theme)

Static site generated from the Swift token sources. Nothing is hand-written in HTML —
edit the generator, never `.context/design-system/*.html`.

```bash
python3 .context/build-design-system-site.py               # rebuild
python3 .context/check-design-system-site.py               # sweep for broken CSS/links
cd .context/design-system && python3 -m http.server 8817   # preview locally
python3 .context/publish-design-system-site.py             # rebuild + sweep + publish
```

**Live:** https://marc-antoine-heidi.github.io/hh-colors/ — public, served from
`marc-antoine-heidi/hh-colors` `main/` root. `--dry-run` shows the diff without pushing.

## The generator ships with the site

`.context/` is gitignored, so the toolchain is versioned in the Pages repo instead:
every publish copies it to `_generator/` alongside the HTML, under the same filenames.
The site and the thing that built it are one artefact — a published page can always be
traced to the exact generator that produced it, and the commit subject names the
`heidinative-ios` SHA it was built from.

Bootstrap a fresh workspace from it:

```bash
git clone --depth 1 git@github.com:marc-antoine-heidi/hh-colors.git /tmp/hh-colors
cp -R /tmp/hh-colors/_generator/. .context/
```

Two guards keep the pair honest: publishing aborts if a `.py` in `.context/` is absent
from `GENERATOR` (a tool that never reached the repo would leave the site unrebuildable),
and the licence sweep runs over the whole checkout rather than just the build output, so
`_generator/` can't smuggle a font binary out. Publishing from a workspace whose
generator differs from the published one is allowed — it prints which files it is
overwriting, the same way the site itself is last-write-wins.

## Editing copy in the browser

Prose is the one thing on this site a build cannot derive, so it is the one thing worth
editing in place. Add `?edit` to any URL:

- section headings, ledes, banners, the eyebrow and the principles become editable;
- `.ct` counts, `<code>` token names and a banner's fixed lead sentence are locked, and
  table cells are not in the selector at all — every value in them is swept from Swift,
  and a site whose numbers can be hand-edited is worth nothing;
- drafts survive a reload in `localStorage`, scoped per page;
- **Copy overrides** puts a JSON payload on the clipboard.

That payload is the whole point. This site is generated, so an edit that lives only in the
browser is wiped by the next build *and looks like it worked*. Paste it into
`.context/copy-overrides.json` to make it real:

```json
[{"page": "spacing.html",
  "was": "Padding, stacks and gaps. <code>space4</code> (16pt) is the default.",
  "now": "Every gap comes from this scale. <code>space4</code> (16pt) is the default."}]
```

Each override is keyed by the exact markup it replaces, and the build asserts that markup
appears **exactly once** on that page. So if the prose later changes in the generator, the
build fails and names the override instead of silently patching the wrong sentence or
dropping the edit. An override that matches no page is reported too.

Note `contentEditable` is a real attribute and lands in `innerHTML`, so the editor compares
and exports from a clone with those stripped — otherwise every payload carries the editor's
own markup and can never match the generated HTML.

## Exposure is used, never shipped

Page titles and the homepage hero are the brand display face, rendered to PNG by
`exposure_text()` with the real string in `alt`. That indirection exists purely because of
the licence below — a webfont or a subset would both be redistribution. Titles are short
and static, so the trade (no text selection) is acceptable; don't extend this to body copy.

The Text page is the deliberate exception for documentation: its multiline Exposure
examples are rasterized locally so line height and paragraph rhythm can be inspected without
publishing the font file. Equivalent Inter and monospaced examples remain selectable HTML.

## Icons

`icons.html` lists only glyphs the app actually references — the `CustomIcons` registry
plus any `Image.lucide("literal")` that bypassed it, which the page calls out separately
because `CustomIcons.swift` asks callers to prefer the registry. The catalogue holds the
whole Lucide set (~1589 imagesets), so listing the catalogue would document icons nobody
chose. **Both** `Lucide-Icons.xcassets` and `Assets.xcassets` must be searched: a few
glyphs (e.g. `external-link`) live in the main catalogue and resolve fine at runtime, so
searching one catalogue reports a working icon as broken.

## Font licensing — do not work around this

`Inter.ttf` is SIL OFL 1.1 and ships as a webfont with its licence notice.
**Exposure is licensed from 205TF and its licence forbids sharing the font file**, so the
builder rasterises Exposure specimens to PNG (`specimens/`) and the `.otf` is never
copied into the output. `publish-design-system-site.py` aborts if any non-Inter font
binary reaches the site. Keep that check.

## Inputs

| Source | Feeds |
|---|---|
| `DesignSystem/Sources/DesignSystem/Theme/HHColorPrimitives.swift` | Primitives |
| `DesignSystem/Sources/DesignSystem/Theme/HHColors.swift` | Semantics, all component previews |
| `DesignSystem/Sources/DesignSystem/Theme/HHFont.swift` | Fonts |
| `DesignSystem/Sources/DesignSystem/Theme/HHSpacing.swift` | Spacing, Sizing (own pages) |
| `DesignSystem/Sources/DesignSystem/Theme/HHRadius.swift` | Radius (own page) |
| `HeidiNative/Styles/ButtonStyles/*.swift` | Buttons — specs, states and previews |
| every `HeidiNative/**/*.swift` | Buttons — adoption, bypasses and the coverage table |
| `DesignSystem/Sources/DesignSystem/CustomIcons.swift` | Icons — the names the app uses |
| `HeidiNative/Lucide-Icons.xcassets`, `Assets.xcassets` | Icon glyphs (PDF → PNG via `sips`) |
| `HeidiNative/Resources/Fonts/*` | Type specimens (copied to `fonts/`) |
| `.context/legacy-tokens.json` | The before/after on Welcome |
| `.context/design-system-anatomy.png` | Anatomy diagram on Semantics |

## Stylesheet is content-hashed — don't "simplify" it back

Pages links `site.<hash>.css`, and `site.css` is kept as an identical copy. Both are
needed: the hash stops cached CSS pairing with newer markup, and the copy stops cached
*markup* (also `max-age=600`) requesting a path that no longer exists. Dropping either
produces a page that renders as bare HTML for readers who saw an earlier version — and
only for them, which is why it reads as "works for me". `check-design-system-site.py`
guards this; the publish script won't push if it fails.

## The Foundations table contract

**Tokens whose value needs explaining are documented in one table shape** — type,
spacing, radius, semantic colour. A row must read identically on every page, so a reader
learns the layout once. Build rows only through these four helpers:

- `ttable(cols, rows)` — the table. `cols` is `[(label, width%)]`.
- `tk(name)` — the token cell: the symbol a view actually types (`HHFont.heading1`).
- `pv(swatch, primary, meta)` — the swatch + value cell. `primary` is the resolved value
  (`48px Exposure Regular`, `Bark 950`, `16pt`); `meta` is the small grey line under it.
- `us(text)` — the prose cell. Backticks become `<code>`.

The **only** thing that varies per foundation is the swatch element inside `pv()`:

| Foundation | Swatch |
|---|---|
| Semantic colour | `<i class="chip" style="background:…">` |
| Radius | `.chip` with `border-radius` set to the token |
| Spacing | `<i class="mtrack"><i class="mbar" style="width:…">` |
| Sizing | `.mtrack` + `.mbox` sized to the token |
| Type | `<i class="fspec">Ag</i>` at the token's real size, weight and face |

Adding a foundation (Icons, motion, elevation…) means writing a new swatch and reusing
the four helpers — not a new table style.

**Primitives are the exception:** they are fixed hex in both themes, so the ramp strip
*is* the documentation and a table would only restate it in words. If a token's value is
fully legible from its swatch, don't table it.

## Page structure

`colors.html` carries Primitives, Semantics and Before / after as pill tabs, with the tab
in the URL hash (`colors.html#semantics`) so it is linkable. The old standalone
`primitives.html` / `semantics.html` URLs were shared publicly, so they remain as
redirects into the right tab — keep them.

The homepage is a **brand introduction**, not a project update: the hero and five ideas,
in the voice of heidihealth.com. Token counts, ticket numbers and the migration roadmap
are deliberately absent — `STAGE` is still in the generator but not rendered, because a
dated roadmap on the landing page is what made the old version read as a status report.

## Facts come from source, never from prose

Values are parsed, never retyped. Where the only available description is a Swift doc
comment, the redundant part (name, metrics, ComponentsKit mapping — each of which has its
own column) is stripped and the remaining caveat is kept. If a fact isn't derivable from
source, the cell stays empty rather than inventing one.

Seven build-time assertions keep the site honest:

- every nav destination is a page that gets written, so the sidebar can't 404;
- every component demo is routed in `ROUTE`, so a demo can't be silently dropped;
- every semantic or SwiftUI text style a button style asks for is in `SWIFT_TYPE`, so a new
  one can't render at a guessed size;
- every curated bespoke-button note resolves its `file:line` from a regex that must match
  its file exactly once (`bad_anchors`), so a renamed or deleted control breaks the build
  instead of leaving a stale line number on the page;
- the local packages (`Quill/Sources`, `Packages/`) still define no buttons, because the
  Buttons page says the whole surface is in `HeidiNative/`;
- no page's HTML mentions debug, checked again on the built output by
  `check-design-system-site.py`;
- every page in `AUDIT_PAGES` carries an `audit_note()` banner, so the sidebar pill can't
  promise a warning the page doesn't make.

## Debug never reaches the site — no exemptions

**Nothing that only exists in a debug build may appear on a page.** Not a debug screen, not
a control inside `#if DEBUG`, not a token named for debugging, not a count that includes
any of them. The site is read as permission to reuse a value; a debug value listed here is
a value someone will ship.

Three enforcement points, so it cannot leak back in by being added somewhere nobody edited:

| Point | What it does |
|---|---|
| `swift_sources(root)` | drops any file whose path has a `Debug` part (`DebugScreens/`, `FeatureFlagsDebug/`, `ChronicleDebugOverlay.swift`) |
| `read_swift(path)` / `blank_debug` | blanks every line inside a `#if DEBUG` branch, **keeping the line count** so `file:line` anchors stay correct; `#else` ends the blanking, since the non-DEBUG branch is the one that ships |
| `is_debug(name)` | drops a debug-named token at each parser — semantics, scales, fonts, icons, shadows, button styles |
| `assert_no_debug(...)` | fails the build if the word survives into any page's HTML |

`check-design-system-site.py` repeats the last one over the built output, which is what
catches a page written by an older generator. **Neither check takes an exemption list.** A
page that "documents debug on purpose" is how debug got onto the site the first time, and
one allowed page is enough to make a reader doubt the next one. If a count looks low after
a rebuild, that is the rule working: Buttons went 577 → 394 when the debug screens and the
`#if DEBUG` previews stopped counting as shipped buttons.

## Audit vs specification — tinted Negative

The site carries two kinds of thing and a reader must tell them apart *before* copying
anything: a value they may reuse, and a swept record of what the app happens to do today.
Audits are marked, specifications are not — absence is the default, so the marker stays
meaningful.

- `audit_note(text)` — the banner, one fixed lead sentence (*An audit, not a specification.*)
  so it reads identically on every page. Page-level.
- `AUDIT_TAG` — the pill next to an `<h2>`, for a single audit section inside a
  specification page (Shadows → *Built by hand*, Icons → *Referenced by string literal*).
- `AUDIT_PAGES` — pages whose whole subject is current usage (Buttons, Motion). They get the
  pill in the sidebar and on the Welcome table too, so the warning survives a direct link;
  a build assertion requires each of them to also carry the banner.

Both are tinted with the app's own Negative role (Red 100 / Red 800), taken from `ramps` at
build time rather than typed in — the colour the product uses to say *look at this*. This
is orthogonal to `STATUS` (live / WIP / to do): status says how finished a page is, audit
says whether what it lists is approved.

## Buttons is an audit, and says so

Unlike the foundations, `buttons.html` documents a surface that is **not** yet systematic:
it was written ahead of the button refactor. Four tabs — the shared styles rendered in
every state they implement, the controls that carry their own chrome, the ways call sites
bypass the system, and a per-file coverage table. Everything except the bespoke notes is
swept from source at build time, so the numbers move on their own; the page opens with the
audit banner rather than claiming to be a spec.

When the refactor lands, this page inverts: the gaps table becomes the spec, and the
bespoke inventory should shrink toward nothing.

## Pages not yet written

`toolbars`, `sheets`, `empty-state`, `tabs`, `toasts` and the three `rows-*` pages are
still stubs — title, lede and a "Not documented yet" box naming what belongs there.
Replace the `stub(...)` call with real content: `ttable` for foundations, `two_up(...)`
for a light/dark component preview. `colors`, `fonts`, `spacing`, `radius`, `sizing`,
`shadows`, `icons`, `avatars` and `buttons` are written.

**Parked demos.** `ROUTE[name] = None` marks a built demo with no page in the IA yet —
nine of them right now (Avatars, Toasts, Session list, Settings sheet, Pills,
Alerts, Recording orb, Evidence chat, Text hierarchy). The markup is still generated and
the build **prints the parked list on every run**, so nothing is lost and nothing is
silent. To place one: set `ROUTE[name]` to a page and use `demos[page]` as its content.

`Text hierarchy` is parked deliberately for a different reason — it demonstrates the
foreground colour roles, so it belongs with colour, not on Fonts.
