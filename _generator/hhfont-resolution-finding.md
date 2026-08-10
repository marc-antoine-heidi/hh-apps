# HHFont: 9 tokens don't render what their doc comment claims

Verified against the pinned ComponentsKit revision while looking at `fonts.html`.
Relevant to `build-design-system-site.py`'s `UNIVERSAL` map, which is currently
sourced from the HHFont doc comments and labelled "ComponentsKit sizes" — those
are the *intended* values, not the ones the app resolves.

## The chain

1. `HHFont.paragraph1` = `dynamicFont(from: UniversalFont.lgBody, relativeTo: .body)`
   (`HHFont.swift:155`)
2. `UniversalFont.lgBody` = `Theme.current.layout.typography.body.large`
   (ComponentsKit `UniversalFont.swift:181`)
3. `Theme.current = Theme.heidi` (`HeidiNativeApp.swift:956`,
   `ThemeChangeObserver.swift:35`)
4. `Theme.heidi` never assigns `layout.typography` — the block is commented out at
   `HHTheme.swift:163` ("ComponentKit does not support dynamic fonts"), so the
   ComponentsKit default applies.
5. ComponentsKit 1.7.1 (pinned rev `0bfa4ff3`) `Theme/Layout.swift:259-280`:
   `body.large = .system(size: 18, weight: .regular)`.
6. `dynamicFont`'s `.system` case calls `.scalingSystemFont`, which is
   `UIFont.systemFont(ofSize:weight:)` (`Font+Additions.swift:79`) — SF Pro.

So `HHFont.paragraph1` renders **SF Pro 18 Regular**, not Inter 16 Regular.

## Resolution table

Every token routed through `UniversalFont` gets SF Pro, not Inter; 7 of the 8
`UniversalFont` entries also land on a different size.

| UniversalFont | Doc comment claims | Actually resolves to |
|---|---|---|
| `lgHeadline` | 20 Inter Semibold | **SF Pro 24 Semibold** |
| `lgButton`   | 16 Inter Medium   | **SF Pro 20 Medium** |
| `lgBody`     | 16 Inter Regular  | **SF Pro 18 Regular** |
| `mdButton`   | 14 Inter Medium   | **SF Pro 16 Medium** |
| `mdBody`     | 14 Inter Regular  | **SF Pro 16 Regular** |
| `smButton`   | 12 Inter Medium   | **SF Pro 14 Medium** |
| `smBody`     | 12 Inter Regular  | **SF Pro 14 Regular** |
| `smCaption`  | 10 Inter Regular  | SF Pro 10 Regular (size matches, family doesn't) |

Affected HHFont tokens and their call-site counts (grep over `HeidiNative/**/*.swift`,
excluding `HHFont.swift`): `paragraph2` 130, `paragraph1` 116, `caption` 100,
`paragraph1Bold` 48, `captionBold` 40, `paragraph2Bold` 27, `heading5` 10,
`footnote` 6, `footnoteBold` 3 — **≈480 call sites**.

Unaffected (explicit `.custom(...)`, so they really are Exposure/Inter):
`heading1` 48, `heading1_5` 36, `heading2` 30, `heading3` 24 (Exposure-10-Regular);
`heading4` 20 and `paragraph1SemiBold` 16 (Inter-Regular_SemiBold); all `markdown*`.

## Second-order drift: SwiftUI vs UIKit spellings disagree

The `*UIFont` counterparts are hand-written rather than routed through
`UniversalFont`, so the two spellings of the same token differ:

| Token pair | SwiftUI | UIKit |
|---|---|---|
| `paragraph1` / `paragraph1UIFont` | SF Pro 18 Regular | Inter-Regular 16 |
| `paragraph1Bold` / `paragraph1BoldUIFont` | SF Pro 20 Medium | Inter-Regular_Medium 16 |
| `paragraph2` / `paragraph2UIFont` | SF Pro 16 Regular | SF Pro 14 Regular |

## Suggestion for the page

This is the type-ramp equivalent of the colour page's "four systems competing"
story, and it's the argument for APP-9455. Rather than printing the doc-comment
values as fact, the page could show **Documented** and **Renders as** columns with
a drift tag, and note the single root cause: `layout.typography` is commented out
in `HHTheme.swift`, so nine tokens silently fall through to ComponentsKit defaults.
