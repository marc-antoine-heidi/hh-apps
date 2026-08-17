#!/usr/bin/env python3
"""Generates the Heidi design-system site from the Swift token sources.

Re-run after changing HHColors.swift or HHColorPrimitives.swift:
    python3 .context/build-design-system-site.py
"""
import json, re, pathlib, html, hashlib, random

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / ".context/design-system"
THEME = ROOT / "HeidiNative/Common/Theme"

# ------------------------------------------------------- debug never reaches the site
# The site documents what ships. Debug-only material — the debug screens, the feature-flag
# tools, anything behind `#if DEBUG`, a token named for debugging — is not a value anyone
# may reuse, and publishing it invites exactly that. It is excluded at three points, so a
# new debug screen or token cannot leak in by being added somewhere nobody edited: the
# corpus (`swift_sources`, `read_swift`), the token parsers (`is_debug`), and an assertion
# over the finished HTML (`assert_no_debug`).
DEBUG_RE = re.compile(r"debug", re.I)


def is_debug(name):
    return bool(DEBUG_RE.search(name))


def blank_debug(txt):
    """Blank every line inside a `#if DEBUG` branch, keeping the line count.

    Lines are blanked rather than deleted because pages resolve `file:line` anchors against
    these strings — removing a line would silently move every anchor below it. `#else` ends
    the blanking: the branch that is not DEBUG is the one that ships."""
    out, depth, skip = [], 0, None
    for raw in txt.splitlines(keepends=True):
        s = raw.lstrip()
        eol = raw[len(raw.rstrip("\r\n")):]     # blanking keeps the line, not its content
        if s.startswith("#if"):
            depth += 1
            if skip is None and re.match(r"#if\s+DEBUG\b", s):
                skip = depth
            out.append(eol if skip else raw)
        elif s.startswith("#endif"):
            out.append(eol if skip else raw)
            if skip == depth:
                skip = None
            depth -= 1
        elif s.startswith(("#else", "#elseif")) and skip == depth:
            skip = None
            out.append(eol)
        else:
            out.append(eol if skip else raw)
    return "".join(out)


def swift_sources(root):
    """Every shipped Swift file under `root`, in path order. Debug files are not shipped."""
    return sorted(p for p in root.rglob("*.swift")
                  if not any(is_debug(part) for part in p.relative_to(root).parts))


def read_swift(path):
    return blank_debug(path.read_text())


def assert_no_debug(name, markup):
    hits = sorted({m.group(0) for m in re.finditer(r"[\w./]*[Dd]ebug[\w./]*", markup)})
    assert not hits, f"{name}: debug-only material reached the site — {hits}"


# ---------------------------------------------------------------- parse
prim_src = read_swift(THEME / "HHColorPrimitives.swift")
sem_src = read_swift(THEME / "HHColors.swift")

ramps = {}
for m in re.finditer(r"enum (HH\w+) \{(.*?)\n\}", prim_src, re.S):
    stops = re.findall(r'static let (s\d+) = HHColorPair\.primitive\("([0-9A-Fa-f]{6})"\)', m.group(2))
    if stops:
        ramps[m.group(1)] = stops

BASE = {}
for m in re.finditer(r"enum (HH\w+) \{(.*?)\n\}", prim_src, re.S):
    lines = m.group(2).split("\n")
    for i, l in enumerate(lines):
        if "BASE" in l:
            for j in range(i, min(i + 3, len(lines))):
                s = re.search(r"static let (s\d+)", lines[j])
                if s:
                    BASE[m.group(1)] = s.group(1)
                    break


def resolve(tok):
    tok = tok.strip().rstrip(",")
    if tok in (".white", "HHColorPair.white"):
        return "FFFFFF", "white"
    if tok in (".black", "HHColorPair.black"):
        return "000000", "black"
    m = re.match(r"(HH\w+)\.(s\d+)$", tok)
    if m:
        for s, h in ramps.get(m.group(1), []):
            if s == m.group(2):
                return h, f"{m.group(1)[2:]} {m.group(2)[1:]}"
    return None, tok


body = sem_src[sem_src.index("enum HHColors {"):]
sems, section = [], ""
for line in body.splitlines():
    ms = re.match(r"\s*// MARK: - (\w+)", line)
    if ms:
        section = ms.group(1)
    m = re.match(r"\s*static let (\w+) = (.*)$", line)
    if not m:
        continue
    name, rest = m.group(1), m.group(2)
    if is_debug(name):
        continue
    one = re.match(r"HHColorPair\.themed\(light: ([\w.]+), dark: ([\w.]+)\)", rest)
    if one:
        lh, ln = resolve(one.group(1)); dh, dn = resolve(one.group(2))
        sems.append(dict(section=section, name=name, lh=lh, dh=dh, la=1.0, da=1.0, ln=ln, dn=dn))
        continue
    if rest.startswith("HHColorPair.themed("):
        blk = re.search(r"static let " + name + r" = HHColorPair\.themed\((.*?)\n    \)", body, re.S).group(1)
        lm = re.search(r"light: ([\w.]+)", blk); dm = re.search(r"dark: ([\w.]+)", blk)
        la = re.search(r"lightAlpha: ([\d.]+)", blk); da = re.search(r"darkAlpha: ([\d.]+)", blk)
        al = re.search(r"\balpha: ([\d.]+)", blk)
        lh, ln = resolve(lm.group(1)); dh, dn = resolve(dm.group(1))
        A = lambda x: float(x.group(1)) if x else 1.0
        sems.append(dict(section=section, name=name, lh=lh, dh=dh,
                         la=A(al) if al else A(la), da=A(al) if al else A(da), ln=ln, dn=dn))
        continue
    h, n = resolve(rest)
    if h:
        sems.append(dict(section=section, name=name, lh=h, dh=h, la=1.0, da=1.0, ln=n, dn=n))


def rgba(hx, a):
    return f"rgba({int(hx[0:2],16)},{int(hx[2:4],16)},{int(hx[4:6],16)},{a:g})"


def theme_vars(mode):
    return "\n".join(
        f"  --{s['name']}: {rgba(s['lh'] if mode=='light' else s['dh'], s['la'] if mode=='light' else s['da'])};"
        for s in sems)


FONTDIR = ROOT / "HeidiNative/Resources/Fonts"
# The app tracks Exposure display type at -1pt on the 48pt heading and -1.2 on the 48pt
# wordmark; as a ratio that is ~-0.021em, which is what scales correctly across sizes.
# Inter text sits near -0.03em (-0.5 at 16pt, -0.6 at 20pt).
TRACK_DISPLAY = -0.021
TRACK_TEXT = -0.03

# Rasters are named for the heading that wants them, so a heading that stops being Exposure
# leaves its PNG behind — and publish copies whatever is in here. Wiped here, at import,
# rather than next to the page-writing loop: page content is built at module level, so a
# body raster (the manifesto) is drawn long before that loop runs and a late wipe deleted it.
import shutil as _shutil; _shutil.rmtree(OUT / "titles", ignore_errors=True)


def exposure_text(text, size, slug, fill=(33, 18, 23, 255)):
    """Render a display string in Exposure to PNG. Page titles use the brand face, but the
    205TF licence forbids shipping the font, so the glyphs ship as an image and the real
    string stays in the alt attribute for accessibility, search and copy-paste fallback.

    Drawn glyph by glyph because Pillow has no letter-spacing: the cumulative prefix width
    keeps the font's own kerning, and the per-index offset applies the tracking on top.

    The canvas is sized from the face's ascent/descent, never from the string's ink bounds.
    Cropping to ink makes a string with no descender ("No custom values") shorter than one
    with ("Fix as you go"); scaling both to the same CSS height then renders the first at a
    visibly larger point size. Constant canvas height per point size is what keeps a row of
    headings looking like one size, so the height travels with the image."""
    from PIL import Image, ImageDraw, ImageFont
    scale = 3
    px = size * scale
    face = ImageFont.truetype(str(FONTDIR / "Exposure[-10].otf"), px)
    track = TRACK_DISPLAY * px
    ascent, descent = face.getmetrics()
    pad = 2 * scale
    # Trim the first glyph's left side bearing so the ink lines up with body text.
    lsb = face.getbbox(text[0])[0] if text else 0
    width = round(face.getlength(text) + track * (len(text) - 1) - lsb) + pad * 2
    img = Image.new("RGBA", (width, ascent + descent + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for i, ch in enumerate(text):
        x = pad + face.getlength(text[:i]) + track * i - lsb
        # Default "la" anchor puts the ascender line at y, so every string shares a baseline.
        draw.text((x, pad), ch, font=face, fill=fill)
    (OUT / "titles").mkdir(parents=True, exist_ok=True)
    img.save(OUT / "titles" / f"{slug}.png")
    # max-width is the raster's own 1x width, so it never scales past its drawn size. It
    # changes nothing on its own; it is the ceiling the hero's width:100% needs.
    #
    # The string ships twice: once as pixels, once as text. Alt text alone is not in the
    # document — a reader cannot select a heading, copy a section, or find it with Cmd-F,
    # and a selection dragged across a page silently drops every heading it crosses. The
    # span is the real text, clipped rather than removed so it stays in the flow and in the
    # selection. With it present the raster is decoration, so alt is empty and the image is
    # hidden from assistive tech instead of announcing the same words twice.
    return (f'<img class="h1img" src="titles/{slug}.png" '
            f'style="height:{round(img.height / scale, 1)}px;'
            f'max-width:{round(img.width / scale)}px" '
            f'width="{round(img.width / scale)}" height="{round(img.height / scale)}" '
            f'alt="" aria-hidden="true">'
            f'<span class="rtxt">{html.escape(text)}</span>')


# ------------------------------------------------------------ audit vs specification
# Two kinds of thing live on this site and a reader has to tell them apart before copying
# anything: a value they may reuse, and a swept record of what the app happens to do today.
# The second kind is tinted with the app's own Negative role — the colour the product uses
# to say "look at this". Pages whose *whole* subject is current usage go in AUDIT_PAGES
# and carry the banner; the sidebar shows status only, so the banner is the whole signal. This is orthogonal to STATUS: status says how far the refactor has
# got, the banner says whether what the page lists is approved.
AUDIT_PAGES = {"buttons.html", "motion.html"}

def audit_note(reason):
    """The banner that separates an audit from a target. The lead-in is shared so the two
    pages read as the same kind of thing; the sentence after it is why *this* page is one."""
    return f'<div class="note audit"><b>An audit, not a target.</b> {reason}</div>'


def design_note(text):
    """A third kind of page: neither swept from source nor approved values, but a Figma
    export of what is *intended*. Every other page can promise it matches the build because
    it is parsed from the build; this one cannot, and has to say so in the same breath."""
    return ('<div class="note design"><b>A design, not the current build.</b> '
            f'{text} These frames are exported from Figma by hand. Nothing verifies them '
            'against the app. Each frame carries its export date.</div>')


# Brand copy is the third thing here that cannot be parsed from the app: it is transcribed
# from Notion and the Brand Book. Same honesty as design_note — say where it came from and
# when, because nothing in the build can tell a reader it has gone stale.

# Lucide external-link, inlined for the same reason as CHEV: this runs before lucide_svg()
# exists, and it is three paths.
DL_ICON = ('<svg viewBox="0 0 24 24" width="20" height="20" fill="none" '
           'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
           'stroke-linejoin="round" aria-hidden="true"><path d="M12 15V3"/>'
           '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
           '<path d="m7 10 5 5 5-5"/></svg>')

EXT_ICON = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/>'
            '<path d="M10 14 21 3"/>'
            '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h6"/></svg>')

# Pages that open with a banner instead of a page title.
# A "video" page still needs its class to paint the poster frame as the background: that is
# what shows while the file loads, when autoplay is refused, and under reduced motion.
HERO = {"index.html": {"class": "h-photo", "badge": "&#8984; iOS", "video": "hero.mp4",
                       "poster": "hero-poster.jpg"},
        # The whole page is transcribed from this deck, so the banner links to it. Anyone
        # who doubts a line here should be one click from the original.
        # Lede above the title here only: it reads as the line the wordmark answers, and
        # "By your side" is the payoff rather than the setup.
        # Neither clip here needs a hold: measured the same way as index, who-we-are.mp4
        # holds a 7.13:1 1st-percentile floor across its loop and who-we-are-2.mp4 a 6.57:1,
        # varying by under 0.3 from end to end rather than falling off part-way through.
        # who-we-are-2.mp4 is 3:2 against the banner's 2.4:1, so cover crops ~38% of its
        # height — framed for it, both faces sit inside the band that survives.
        "who-we-are.html": {"class": "h-brand", "lede_above": True,
                            # List order is play order; the numbers are only filenames, so
                            # -3 leading is not a mistake. Added first rather than renaming
                            # the other two, which would have detached the per-clip contrast
                            # measurements above from the files they were taken on.
                            "video": ["who-we-are-3.mp4", "who-we-are.mp4",
                                      "who-we-are-2.mp4"],
                            "poster": "who-we-are-poster.jpg",
                            "action": ("Brand Book",
                                       "https://docs.google.com/presentation/d/"
                                       "1fhi16soG1c8_pP2NA7sNImmntd7roicNFQ2w6qE_9ws/edit"
                                       "?slide=id.g37a38d41b41_0_231"
                                       "#slide=id.g37a38d41b41_0_231")},
        # Three clips, cycling: consult room, the operations desk, then the front desk the
        # archetypes below open on. All run 5.04s and none needs a hold — measured the same way
        # as the Welcome pair, the 1st-percentile contrast for white over the title band holds
        # flat for each whole loop (5.01-5.09 for who-we-serve-manager, 2.50-2.55 for
        # who-we-serve-2, 2.33-2.37 for who-we-serve) rather than falling off a cliff the way
        # hero-2 does. Two of the three are 3:2 against the first's 2:1, so cover crops them
        # ~30% vertically, which is what keeps their bright monitors outside the text band.
        # Re-measure if any is replaced.
        #
        # The filenames are not in play order: `-2` was here before the manager clip was
        # inserted ahead of it, and renaming a published asset to renumber it would break the
        # cache for no gain. This list is what orders them.
        # Same one-click-to-the-source reason as Who we are: the archetypes on this page are
        # transcribed from that Notion doc.
        "who-we-serve.html": {"class": "h-serve",
                              "video": ["who-we-serve.mp4", "who-we-serve-manager.mp4",
                                        "who-we-serve-2.mp4"],
                              "poster": "who-we-serve-poster.jpg",
                              "action": ("Customer archetypes",
                                         "https://app.notion.com/p/heidihealth/"
                                         "Heidi-User-Archetypes-"
                                         "332ca630286e81f6bbacda73f10ba56f")}}

# A hero whose asset has not been shot yet still has to render. Anything missing from
# .context/ is dropped from the config here rather than crashing the copy step or emitting a
# <video> with no source, and its class falls back to the wash.
for _p, _cfg in HERO.items():
    for _k in ("video", "poster"):
        _v = _cfg.get(_k)
        if not _v:
            continue
        # A hero may name several clips to alternate between, so a value is either one
        # filename or a list of them. Keep the ones that exist; drop the key only when none
        # do, so one missing clip does not silently take the whole banner back to the wash.
        _names = [_v] if isinstance(_v, str) else list(_v)
        _present = [_n for _n in _names if (ROOT / ".context" / _n).exists()]
        if not _present:
            _cfg.pop(_k)
        elif isinstance(_v, str):
            _cfg[_k] = _present[0]
        else:
            _cfg[_k] = _present
HERO_FALLBACK = [c["class"] for c in HERO.values() if not c.get("poster")]


# ---------------------------------------------------------------- shell
# (section, [(href, label, [(href, label), ...]), ...]) — sections are labels only, never links.
SCREENS = [
    ("onboarding", "Onboarding",
     "Everything before the first note: unlocking the app, signing in, and the one-time "
     "welcome. The only part of the product a signed-out person can see.",
     [("splash", "Splash and app lock", "SplashScreen"),
      ("sign-in", "Sign in", "UnifiedLoginView"),
      ("carousel", "Welcome carousel", "OnboardingCarousel")]),
    ("scribe", "Scribe",
     "The core loop: the list of consults, the recorder, and the note that comes out of "
     "it. Where a clinician spends almost all of their time.",
     [("sessions", "Sessions", "HHSessionListView"),
      ("recording", "Recording", "HHSessionView"),
      ("note", "Session note", "HHSessionDetailView")]),
    ("evidence", "Evidence",
     "Ask Heidi: the clinical question-and-answer surface, reachable from its own tab and "
     "from inside a note.",
     [("ask", "Ask Heidi", "EvidenceView"),
      ("history", "Chat history", "ChatHistoryView")]),
    ("remote", "Remote",
     "Heidi Remote, the hardware capture device. Pairing and device state are the two "
     "screens a clinician actually returns to.",
     [("device", "Device detail", "ChronicleDetailView"),
      ("pairing", "Pairing", "ChronicleSetupView")]),
    ("work", "Work",
     "The agent surface: the home shell it launches from, and the chat where a run is "
     "followed and approved.",
     [("home", "Home shell", "HomeShellView"),
      ("chat", "Work chat", "WorkChatView"),
      ("runs", "Runs", "WorkChatListView")]),
    ("notifications", "Notifications",
     "Approvals are the notification surface. The app has no notification settings screen "
     "of its own, it defers to the system.",
     [("inbox", "Inbox", "InboxView"),
      ("review", "Approval review", "InboxReviewView")]),
]


NAV = [
    ("Brand", [
        ("who-we-are.html", "Who we are"),
        ("who-we-serve.html", "Who we serve"),
        ("assets.html", "Assets"),
    ]),
    ("Foundations", [
        ("colors.html", "Colors"),
        ("fonts.html", "Text"),
        ("spacing.html", "Spacing"),
        ("radius.html", "Radius"),
        ("sizing.html", "Sizing"),
        ("shadows.html", "Shadows"),
        ("motion.html", "Motion"),
        ("icons.html", "Icons"),
    ]),
    ("Components", [
        ("buttons.html", "Buttons"),
        ("avatars.html", "Avatars"),
        ("toasts.html", "Toasts"),
        ("toolbars.html", "Toolbars (top)"),
        ("sheets.html", "Sheets"),
        ("empty-state.html", "Empty state"),
        ("tabs.html", "Tabs"),
        ("rows.html", "Rows"),
    ]),
    # Built from SCREENS so a new group cannot be added to the pages and forgotten here.
    ("Screens", [(f"screens-{s}.html", t) for s, t, _, _ in SCREENS]),
]

# Read off NAV rather than listed a second time: a page moved into Brand picks up the
# no-count rule by being moved, not by someone remembering to update a list.
_BRAND_PAGES = {href for section, pages in NAV if section == "Brand" for href, _ in pages}

# The nav is one level, but these pages still exist and are reached from their parent's
# cards — without this they would leave the sidebar with nothing lit.
PARENT = {"rows-sessions.html": "rows.html", "rows-settings.html": "rows.html",
          "rows-actions.html": "rows.html"}

# How far the app has been refactored onto a token: a dot before the sidebar label, a pill
# on the page itself. The default is per nav section, so a new page inherits its section's
# status rather than silently claiming to be in sync; STATUS names only the exceptions.
STATUS_LABEL = {"live": "In sync", "wip": "WIP", "todo": "Out of sync"}
# The dot is a claim about the code, not the page: green means call sites have moved onto
# the token, not that the page is written. Welcome's legend is generated from this, so a
# new status cannot ship without an explanation of what its colour means.
STATUS_MEANING = {"live": "In sync with refactors",
                  "wip": "In progress, close",
                  "todo": "Out of sync, needs refactor"}
assert STATUS_LABEL.keys() == STATUS_MEANING.keys(), "every status needs a legend entry"
# Brand carries no status: the dot is a claim about how far the app has been refactored onto
# a token, and there is no token to refactor onto in a vision statement. None means no dot
# and no pill, rather than a colour that would have to be read as a lie.
# Screens are the same case: a capture of a shipped screen is not on the refactor journey.
SECTION_STATUS = {"Brand": None, "Foundations": "todo", "Components": "todo",
                  "Screens": None}
STATUS = {"colors.html": "live", "icons.html": "live", "sheets.html": "wip"}


def status_of(href):
    """Status key for a page, or None for pages outside the nav (the Welcome hero)."""
    href = PARENT.get(href, href)
    if href in STATUS:
        return STATUS[href]
    for section, items in NAV:
        if any(h == href for h, _ in items):
            return SECTION_STATUS[section]
    return None


def dot(href):
    """The status dot, for the sections that carry one.

    Nothing is emitted where there is no status: a placeholder held the slot so every label
    lined up, but it reserved 15px of leading space in front of a label with nothing leading
    it. Brand items now start at the padding edge; they sit left of the Foundations labels,
    which is the honest reading — those have a dot and these do not.
    """
    st = status_of(href)
    return f'<i class="dot {st}"></i>' if st else ""


def status_pill(st):
    return f'<span class="pstat {st}"><i></i>{STATUS_LABEL[st]}</span>'


def pstat(href):
    """The dot-and-label pill. Takes a link target, so an in-page anchor resolves too."""
    st = status_of(href.split("#")[0])
    return status_pill(st) if st else ""


def dswitch():
    """The design-system switcher: current platform ticked, the rest inert until they exist."""
    items = ""
    for name, live in SYSTEMS:
        cls, mark = ("dswitem", '<i class="dswtick">&#10003;</i>') if live else \
                    ("dswitem off", '<em class="dswsoon">Soon</em>')
        cur = ' aria-current="true"' if live else ' aria-disabled="true"'
        items += f'<span class="{cls}"{cur}>{name}{mark}</span>'
    return (f'<details class="dsw"><summary title="Switch design system">'
            f'<span class="rtxt">Switch design system</span>{CHEV_DOWN}</summary>'
            f'<div class="dswmenu">{items}</div></details>')


def sidenav(active):
    # The chevron is its own control beside the wordmark rather than wrapping it: the brand
    # is also the Welcome link, and one target cannot both navigate and open a menu.
    # <details> so the disclosure needs no script.
    out = [f'<div class="brandrow">'
           f'<a class="brand{" on" if active == "index.html" else ""}" href="index.html">'
           f'<i class="mark"></i><span class="btxt"><b>{BRAND}</b>'
           f'<i>{BRAND_SUB}</i></span></a>'
           f'{dswitch()}</div>']
    for section, items in NAV:
        out.append(f'<div class="navsec">{section}</div><ul>')
        for href, label in items:
            # The active pill takes the colour of the status it is showing, and so does the
            # hover — s-{status} rides on every item, active or not, so one generated rule
            # can paint both states from one pair of tokens. Pages with no status (the brand
            # pages) fall through to the default Bark fill, for hover and active alike.
            st = status_of(href)
            here = href in (active, PARENT.get(active))
            cls = ([f"s-{st}"] if st else []) + (["on"] if here else []) \
                + ([f"on-{st}"] if here and st else [])
            attr = f' class="{" ".join(cls)}"' if cls else ""
            out.append(f'<li><a href="{href}"{attr}>{dot(href)}{label}</a></li>')
        out.append("</ul>")
    # Last, and sticky: it is a key to the dots above it, not a nav destination.
    out.append('<div class="stleg">'
               + "".join(f'<span title="{STATUS_MEANING[st]}">'
                         f'<i class="dot {st}"></i>{STATUS_LABEL[st]}</span>'
                         for st in STATUS_LABEL)
               + '</div>')
    return "".join(out)


BRAND = "HH Design System"
# The platform qualifier is a second line in the sidebar, not part of the name itself, so
# it stays out of BRAND — which also feeds <title> and the homepage hero raster. It is also
# the switcher's current entry, so the two read the same way round: "Native iOS", not
# "iOS-Native".
BRAND_SUB = "Native iOS"

# The design systems the switcher offers. (label, shipped) — "HH" is dropped from each label
# because the wordmark directly above already says it, and a menu that repeats it three times
# reads as three products rather than three platforms of one.
SYSTEMS = [("Native iOS", True), ("Native Android", False), ("Web", False)]
assert sum(live for _, live in SYSTEMS) == 1, "exactly one design system is the current one"

CHEV_DOWN = ('<svg viewBox="0 0 24 24" width="16" height="16" fill="none" '
             'stroke="currentColor" stroke-width="2.25" stroke-linecap="round" '
             'stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>')


def slugify(text):
    """Filename-safe id for a rasterised heading."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


VOID_TAGS = {"img", "input", "br", "hr", "meta", "link", "source", "col", "area", "embed"}
TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>")


def top_level(markup):
    """Yield (start, end, tagname, attrs) for each depth-0 element in markup.

    A regex walk is enough because everything here is generated by this file: no comments,
    no CDATA, no unclosed tags, and attribute values never contain a raw '>'.
    """
    depth = start = 0
    tag = attrs = ""
    for m in TAG_RE.finditer(markup):
        close, name, at, selfclose = m.groups()
        if close:
            depth -= 1
            if depth == 0:
                yield start, m.end(), tag, attrs
        elif name.lower() in VOID_TAGS or selfclose:
            if depth == 0:
                yield m.start(), m.end(), name, at
        else:
            if depth == 0:
                start, tag, attrs = m.start(), name, at
            depth += 1


def wrap_heads(markup):
    """Put each heading and its lede in a .shead, so the divider has something to hang on.

    For the cards that merge several groups (the colour ramps, the semantic roles) the
    headings are h3 and sit mid-card, so sectionise never sees them.
    """
    nodes = list(top_level(markup))
    out, prev, i = [], 0, 0
    while i < len(nodes):
        s, _, tag, _ = nodes[i]
        if tag.lower() not in ("h2", "h3"):
            i += 1
            continue
        i += 1
        while i < len(nodes) and 'class="lede sub"' in nodes[i][3]:
            i += 1
        end = nodes[i - 1][1]
        out.append(markup[prev:s] + f'<div class="shead">{markup[s:end]}</div>')
        prev = end
    out.append(markup[prev:])
    return "".join(out)


def sectionise(markup):
    """Wrap each h2 section — heading, lede and content — in a white card.

    The heading block opens the card, with no rule under it. Anything before the first h2
    (tab strip, note box, anatomy diagram) is page preamble and is left alone. Tab panels
    are recursed into, because their h2s are one level down and would otherwise be missed.
    """
    nodes = list(top_level(markup))

    if any("tabpanel" in a for _, _, _, a in nodes):
        parts, prev = [], 0
        for s, e, _, attrs in nodes:
            if "tabpanel" not in attrs:
                continue
            el = markup[s:e]
            open_end, close_start = el.index(">") + 1, el.rindex("</")
            parts.append(markup[prev:s] + el[:open_end]
                         + sectionise(el[open_end:close_start]) + el[close_start:])
            prev = e
        parts.append(markup[prev:])
        markup = "".join(parts)
        nodes = list(top_level(markup))

    if not any(t.lower() == "h2" for _, _, t, _ in nodes):
        return markup

    out = []
    # Preamble: everything up to the first h2 is page furniture, not a section.
    first = next(n for n, (_, _, t, _) in enumerate(nodes) if t.lower() == "h2")
    out.append(markup[:nodes[first][0]])

    i = first
    while i < len(nodes):
        head_start = nodes[i][0]
        i += 1
        # A lede introduces the section, so it belongs in the heading block above the rule.
        while i < len(nodes) and 'class="lede sub"' in nodes[i][3]:
            i += 1
        head = markup[head_start:nodes[i - 1][1]]
        body_start = i
        while i < len(nodes) and nodes[i][2].lower() != "h2":
            i += 1
        body = markup[nodes[body_start][0]:nodes[i - 1][1]] if i > body_start else ""
        out.append(f'<div class="scard"><div class="shead">{head}</div>{body}</div>')
    return "".join(out)


# ------------------------------------------------------------------ copy editing
# Prose on this site is the one thing a build cannot derive, so it is the one thing worth
# editing in place. Reached with ?edit — never on for a reader.
#
# The hard part is not the editing, it is that this site is generated: an edit that lives
# only in the browser is wiped by the next build, and worse, looks like it worked. So edit
# mode is a drafting surface that ends in a clipboard payload, and copy-overrides.json is
# where an edit becomes real. Each override is keyed by the exact markup it replaces, so if
# the underlying prose changes in the generator the build fails instead of applying the
# override to the wrong sentence or dropping it in silence.
#
# Derived children stay locked: .ct counts, <code> token names and the fixed lead sentence
# of a banner are contentEditable=false inside an otherwise editable block. Table cells are
# not in the selector at all — every value in them is swept from Swift, and a site whose
# numbers can be hand-edited is worth nothing.
# h2 is out: the label is an Exposure raster now, so there is no text in the DOM to put
# a caret in. Heading copy is still editable — via copy-overrides.json, which is applied
# before the raster is drawn. h3 is still live text, so it stays.
EDITABLE_SEL = ".shead h3, .lede, .prin p, .note, .eyebrow"

OVERRIDES_FILE = ROOT / ".context/copy-overrides.json"
OVERRIDES = json.loads(OVERRIDES_FILE.read_text()) if OVERRIDES_FILE.exists() else []
_applied = set()


def apply_overrides(name, markup):
    """Swap in edited copy, refusing anything whose original is no longer on the page."""
    for i, o in enumerate(OVERRIDES):
        if o["page"] != name:
            continue
        n = markup.count(o["was"])
        assert n == 1, (f'copy override {i} for {name} matches its "was" {n} times, not once '
                        f'— the prose it replaces has changed in the generator, so the edit '
                        f'has to be re-made against the new text: {o["was"][:70]!r}')
        markup = markup.replace(o["was"], o["now"])
        _applied.add(i)
    return markup

REVEAL_JS = """<script>
(function(){
 var els=[].slice.call(document.querySelectorAll('.reveal'));
 if(!els.length||!('IntersectionObserver'in window))return;
 if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
 document.documentElement.classList.add('reveal-on');
 var io=new IntersectionObserver(function(es){
   es.forEach(function(e){
     e.target.classList.toggle('in',e.isIntersecting);});
 },{rootMargin:'0px 0px -6% 0px',threshold:0.04});
 els.forEach(function(el){io.observe(el);});
})();
</script>"""


# The banner media travels at 80% of page speed: the page moves content up by y, so the
# media has to move DOWN by 0.2y relative to its own container to lag behind.
#
# Two constraints pull against each other. Running 80% for the whole time a 480px banner is
# on screen needs ~100px of travel, and the media can only travel as far as the overscan the
# CSS reserves — so more parallax means a more cropped frame. And the resting frame is the
# one people actually look at, so the crop at rest has to be even top and bottom rather than
# all on one edge.
#
# So: the media starts centred (translate 0, 50px hidden above and below) and drifts down to
# +50. That is a true 80% for the first 250px of scroll — the top half of the banner leaving
# — and holds after that, by which point most of it is already gone. The alternative was to
# start at one extreme and get 80% throughout, at the cost of cropping 100px off the top of
# every resting banner.
PARALLAX_PX = 50

# The cross-fade between a hero's clips, shared by the CSS transition and the JS lead-in so
# the outgoing clip is still moving while the incoming one appears. One number, or the fade
# and the cut drift apart and the loop shows a frozen last frame.
HERO_FADE_MS = 900
HERO_LOOP_JS = """<script>
(function(){
 var c=[].slice.call(document.querySelectorAll('.hero .hclip'));
 if(c.length<2)return;
 /* Reduced motion hides .hbg outright, so there is nothing to cycle and the poster the
    class background paints is what shows. */
 if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
 var FADE=%(fade)d,i=0,timer=null;
 /* One pending timer, re-armed at each switch, rather than a switch driven by `timeupdate`
    and `ended`. Those looked like the obvious triggers and are not: they fire repeatedly,
    they keep firing on a clip that is already fading out, and a rewound clip emits one more
    carrying its old position. Each of those re-entered the switch, and two clips would end
    up with a pause queued against them and nothing left to restart either -- a banner frozen
    on a still. Elapsed time is the only thing the transition actually depends on. */
 function arm(){
  clearTimeout(timer);
  var v=c[i];
  /* A clip that has not reported its length yet cannot be scheduled against. */
  if(!isFinite(v.duration)||!v.duration){
   v.addEventListener('loadedmetadata',arm,{once:true});
   return;
  }
  var left=(v.duration-v.currentTime)*1000-FADE;
  timer=setTimeout(next,left>50?left:50);
 }
 function settle(){
  for(var n=0;n<c.length;n++){
   if(n===i){
    if(c[n].paused){var p2=c[n].play();if(p2&&p2['catch'])p2['catch'](function(){});}
   }else{
    c[n].pause();
    /* Only when it has actually moved: assigning currentTime dispatches a seek. */
    if(c[n].currentTime)c[n].currentTime=0;
   }
  }
 }
 function next(){
  var cur=c[i],nxt=c[(i+1)%%c.length];
  var pr=nxt.play();
  if(pr&&pr['catch'])pr['catch'](function(){});
  nxt.classList.add('on');
  cur.classList.remove('on');
  i=(i+1)%%c.length;
  /* Once the fade is over, restate the whole invariant rather than pausing the one clip
     this call happened to replace: index i is playing, every other clip is paused at 0.
     Written as a settle step because it is idempotent -- a stray or duplicated switch can
     leave a clip paused while it is the visible one, and a banner frozen on a still is the
     one failure here nobody would report as a bug. Pausing is also what must wait for the
     fade; doing it at the swap would freeze a frame that is still half-visible. */
  setTimeout(settle,FADE);
  arm();
 }
 arm();
 /* A watchdog, because play() can be refused and this code cannot tell the difference: the
    promise rejects, the rejection is swallowed, and the clip stays paused while it is the
    one on screen. Settling once per second means the worst case is a second of stillness
    rather than a banner that never moves again. Idempotent, so the cost is two reads. */
 setInterval(settle,1000);
})();
</script>""" % {"fade": HERO_FADE_MS}
COPY_JS = """<script>
(function(){
 var tmr;
 /* One element for both jobs: it is the aria-live region and the visible toast, so a
    screen reader and a sighted user are told the same thing at the same moment. */
 function flash(el,txt){
   var live=document.getElementById('copied');
   if(!live)return;
   var lbl=live.querySelector('.ctxt');
   if(lbl)lbl.textContent='Copied';
   live.classList.add('on');
   clearTimeout(tmr);
   tmr=setTimeout(function(){live.classList.remove('on');},3000);
 }
 /* Fallback for anything that refuses the async clipboard (older Safari, a non-secure
    origin, a denied permission). Feedback only fires on a copy that actually happened. */
 function legacy(txt){
   var ta=document.createElement('textarea');
   ta.value=txt; ta.setAttribute('readonly','');
   ta.style.cssText='position:fixed;top:-100px;opacity:0';
   document.body.appendChild(ta); ta.select();
   var ok=false; try{ok=document.execCommand('copy');}catch(e){}
   document.body.removeChild(ta); return ok;
 }
 document.addEventListener('click',function(e){
   var el=e.target.closest('.tok'); if(!el)return;
   var txt=el.textContent.trim(); if(!txt)return;
   if(navigator.clipboard&&navigator.clipboard.writeText){
     navigator.clipboard.writeText(txt).then(function(){flash(el,txt);},
                                            function(){if(legacy(txt))flash(el,txt);});
   }else if(legacy(txt))flash(el,txt);
 });
})();
</script>"""

# The sidebar is its own scroll container (sticky, overflow-y:auto against the viewport), so
# every navigation re-renders it at the top. It overflows by ~300px at 1440x900, which is
# enough that a reader working through Components loses their place on each page they open.
#
# This one is injected directly after the <nav>, not with the scripts at the end of body: the
# restore has to happen before the much longer <main> is parsed, or the nav paints at zero and
# the correction reads as a jump rather than as continuity.
#
# sessionStorage rather than local, and one key for the whole site rather than the per-path
# key COPY_JS uses: the position belongs to this tab's browsing and has to survive a
# navigation, which is exactly what a per-path key would not do.
SIDE_SCROLL_JS = """<script>
(function(){
 var K='hhside',n=document.querySelector('.side');
 if(!n)return;
 /* Blocked storage throws on access rather than returning null, and a nav that cannot
    remember its position still has to scroll. */
 try{var v=sessionStorage.getItem(K);if(v)n.scrollTop=+v}catch(e){}
 var f=0;
 n.addEventListener('scroll',function(){
  if(f)return;
  /* One write per frame: scroll fires far more often than that and the write is synchronous. */
  f=requestAnimationFrame(function(){f=0;try{sessionStorage.setItem(K,n.scrollTop)}catch(e){}});
 },{passive:true});
})();
</script>"""

PARALLAX_JS = """<script>
(function(){
 var m=[].slice.call(document.querySelectorAll('.hbg')),
     s=[].slice.call(document.querySelectorAll('.mstar')),
     w=[].slice.call(document.querySelectorAll('.mani'));
 if(!m.length&&!s.length&&!w.length)return;
 if(matchMedia('(prefers-reduced-motion:reduce)').matches)return;
 var MAX=%d,queued=false;
 function place(){
  queued=false;
  var y=window.pageYOffset;
  var d=Math.min(y*0.2,MAX);
  for(var i=0;i<m.length;i++)m[i].style.transform='translate3d(0,'+d.toFixed(1)+'px,0)';
  /* 50%% of page speed: the star lags the card it sits in, so it drifts down through the
     manifesto as you read. Apparent speed is (1 - k) x page speed for a transform of
     -mid*k, so k = +0.5 gives 0.5x — the sign is what decides whether it runs ahead of the
     page or trails it.
     Measured from the card's own position, not from pageYOffset: the manifesto is well
     down the page, so a factor of the absolute scroll would have the star hundreds of
     pixels outside it before it was ever on screen. Clamped so it stays in the card at any
     viewport height — at this rate it reaches the clamp quickly and rides it. */
  var vh=window.innerHeight;
  for(var j=0;j<s.length;j++){
    var r=s[j].parentNode.getBoundingClientRect();
    /* Distance from the card's centre to the viewport's, so the sweep is centred on the
       card's pass rather than on absolute page position. */
    var mid=r.top+r.height/2-vh/2;
    /* Clamp to the room the card has, not a fixed number: the star is centred, so it can
       travel half the card less its own half and an inset. A hardcoded 70 pinned it at the
       limit for the entire scroll, which is why it never appeared to move. */
    var lim=Math.max(0,r.height/2-s[j].offsetHeight/2-24);
    var e=Math.max(-lim,Math.min(lim,mid*0.5));
    /* One full turn across the card's whole pass, on the same progress the wash below
       uses: 0 as the card's top edge reaches the bottom of the viewport, 360 once its
       bottom edge has cleared the top. Tied to the card rather than to pageYOffset for the
       same reason the drift is — an absolute-scroll factor would have spun it for hundreds
       of pixels before it was ever on screen. */
    var t=Math.max(0,Math.min(1,(vh-r.top)/(vh+r.height)))*360;
    s[j].style.transform='translate3d(0,'+e.toFixed(1)+'px,0) rotate('+t.toFixed(1)+'deg)';
  }
  /* 0 as the card's top edge reaches the bottom of the viewport, 1 once its bottom edge
     has reached the top: the wash fills as the card travels, not as the page does. */
  for(var k=0;k<w.length;k++){
    var q=w[k].getBoundingClientRect();
    var pr=(vh-q.top)/(vh+q.height);
    w[k].style.setProperty('--fill',Math.max(0,Math.min(1,pr)).toFixed(3));
  }
 }
 addEventListener('scroll',function(){
  if(!queued){queued=true;requestAnimationFrame(place);}},{passive:true});
 place();
})();
</script>""" % PARALLAX_PX


EDIT_JS = """<script>
(function(){
 if(!/[?&]edit(=|&|$)/.test(location.search))return;
 var SEL=%r,KEY='hhcopy:'+location.pathname,
     store=JSON.parse(localStorage.getItem(KEY)||'{}'),reg=[];
 document.body.classList.add('editing');
 // contentEditable is a real attribute, so it lands in innerHTML. Compare and export from
 // a stripped clone, or every string carries the editor's own markup into the payload and
 // can never match the generated HTML it is meant to replace.
 function clean(el){
  var c=el.cloneNode(true);
  c.querySelectorAll('[contenteditable]').forEach(function(n){
    n.removeAttribute('contenteditable');});
  return c.innerHTML.trim();
 }
 function lock(el){
  el.querySelectorAll('.ct,code,b').forEach(function(c){c.contentEditable='false';});
 }
 document.querySelectorAll(SEL).forEach(function(el){
  var was=clean(el);
  el.dataset.was=was;
  if(store[was]!==undefined&&store[was]!==was)el.innerHTML=store[was];
  el.contentEditable='true';el.spellcheck=true;lock(el);
  reg.push(el);
 });
 var bar=document.createElement('div');bar.className='ebar';document.body.appendChild(bar);
 function changed(){return reg.filter(function(el){
   return clean(el)!==el.dataset.was;});}
 function draw(){
  var n=changed().length;
  bar.innerHTML='<b>'+n+'</b> change'+(n===1?'':'s')+
   ' <button data-a="copy">Copy overrides</button><button data-a="reset">Reset</button>';
 }
 function save(){
  var s={};changed().forEach(function(el){s[el.dataset.was]=clean(el);});
  localStorage.setItem(KEY,JSON.stringify(s));draw();
 }
 document.addEventListener('input',function(e){if(e.target.isContentEditable)save();});
 bar.addEventListener('click',function(e){
  var a=e.target.dataset&&e.target.dataset.a;if(!a)return;
  if(a==='reset'){localStorage.removeItem(KEY);location.reload();return;}
  var page=location.pathname.split('/').pop()||'index.html',
      out=changed().map(function(el){
        return {page:page,was:el.dataset.was,now:clean(el)};});
  navigator.clipboard.writeText(JSON.stringify(out,null,2)).then(function(){
    bar.querySelector('button').textContent='Copied \\u2713';
    setTimeout(draw,1400);});
 });
 draw();
})();
</script>""" % EDITABLE_SEL


# Headings are set in the brand face like the page titles, which means rasterising them:
# Exposure is licensed from 205TF and cannot ship as a webfont. One pass over the finished
# markup rather than 24 edits at the call sites, so no heading can be missed.
#
# Only the label becomes an image. The .ct count stays live text — it is swept data, it has
# to stay selectable, and it is set in Inter on purpose. The real string travels in `alt`,
# so find-in-page, search engines and screen readers still see the heading.
#
# 205TF ships no semibold and the face has no weight axis (Exposure-10-Regular and -Italic
# are the whole set), so "semibold" is not available to render. Faux-bolding by stroking the
# glyphs was rejected: it is not a weight the design system owns.
H2_PX = 36


# Foundations pages take their section heads at h3, as live text. The Exposure raster is
# reserved for the pages that read as brand writing — Welcome, Who we are, Who we serve —
# and the Colors primitives tab already set the pattern with `.shead h3` per ramp.
H3_HEAD_PAGES = {h for section, items in NAV if section == "Foundations" for h, _ in items}


def demote_h2(markup):
    """h2 section heads to h3, label left as text rather than swapped for a raster."""
    return re.sub(r"<h2([^>]*)>(.*?)</h2>", r"<h3\1>\2</h3>", markup, flags=re.S)


def exposure_h2(markup):
    """Swap each h2's label for an Exposure raster, keeping the count as HTML."""
    out, prev = [], 0
    for m in re.finditer(r"<h2([^>]*)>(.*?)</h2>", markup, re.S):
        inner = m.group(2)
        label, _, tail = inner.partition('<span class="ct"')
        tail = f'<span class="ct"{tail}' if tail else ""
        text = html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        if not text:
            continue
        # A heading that sits on a photograph is drawn white: the raster bakes its ink, so
        # CSS cannot recolour it after the fact. Its slug carries the ink, or the two
        # variants of one string would overwrite each other's PNG.
        white = "onimg" in m.group(1)
        # Same text on two pages shares one PNG; the hash keeps the name stable and unique
        # where slugify would collide (two pages both have a "Primary" heading).
        slug = "h2-" + hashlib.sha1(text.encode()).hexdigest()[:10] + ("-w" if white else "")
        img = exposure_text(text, H2_PX, slug,
                            (255, 255, 255, 255) if white else (33, 18, 23, 255)
                            ).replace('class="h1img"', 'class="h2img"')
        out.append(markup[prev:m.start()] + f"<h2{m.group(1)}>{img}{tail}</h2>")
        prev = m.end()
    out.append(markup[prev:])
    return "".join(out)


def page(active, title, lede, content, extra_css="", head=True):
    nav = sidenav(active)
    carded = sectionise(content)
    # sectionise only inserts wrappers; if the scan ever mis-reads a tag it would drop or
    # duplicate markup, and a silently truncated page is the worst failure this site has.
    assert TAG_RE.sub("", carded) == TAG_RE.sub("", content), f"sectionise lost text on {active}"
    # Only the wrappers this pass inserted — a page may hand-roll its own (Primitives does).
    added = sum(carded.count(w) - content.count(w)
                for w in ('<div class="scard">', '<div class="shead">'))
    assert len(TAG_RE.findall(carded)) == len(TAG_RE.findall(content)) + 2 * added, \
        f"sectionise unbalanced tags on {active}"
    content = carded
    doc_title = title if title == BRAND else f"{title} · {BRAND}"
    # A hero page reverses out over a dark fill, and the title is a raster — CSS cannot
    # recolour it, so it is drawn white rather than inverted after the fact.
    hero = HERO.get(active)
    slug = "t-" + active.replace(".html", "")
    # 80 on a hero: it is a banner, not the 48px page-title scale every other h1 shares.
    h1 = exposure_text(title, 80 if hero else 48, slug,
                       (255, 255, 255, 255) if hero else
                       (33, 18, 23, 255)) if head else ""
    # Banner text carries TextXL; a page lede keeps the body scale it has always had. A page
    # may have no lede at all — an empty <p class="lede"> would still spend its 30px margin.
    lede_html = f'<p class="lede{" textxl" if hero else ""}">{lede}</p>' if lede else ""
    phead_html = (f'<div class="phead{" nolede" if not lede else ""}">'
                  f'<h1>{h1}</h1>{pstat(active)}</div>') if head else ""
    above = bool(hero and hero.get("lede_above"))
    head_html = (lede_html + phead_html) if above else (phead_html + lede_html)
    hero_js = ""
    if hero:
        # muted+playsinline are what make autoplay permissible at all; poster is the same
        # frame the CSS background carries, so there is no jump when playback starts.
        if hero.get("video"):
            _clips = hero["video"]
            _clips = [_clips] if isinstance(_clips, str) else list(_clips)
            # One clip loops itself in the element and needs no script. Two or more
            # cannot: `loop` suppresses `ended`, so HERO_LOOP_JS drives the cycle and
            # the attribute comes off. Several <source> elements would NOT alternate --
            # the browser reads those as format fallbacks and plays only the first it
            # can decode, which looks like a playlist and silently is not. Only the
            # first clip autoplays and carries the poster; the rest are faded in
            # already playing, so a poster on them would flash.
            solo = len(_clips) == 1
            hero_js = "" if solo else HERO_LOOP_JS
            bg = "".join(
                f'<video class="hbg{"" if solo else (" hclip on" if n == 0 else " hclip")}" '
                f'{"autoplay muted loop" if solo else ("autoplay muted" if n == 0 else "muted")} '
                f'playsinline preload="auto"'
                + (f' poster="{hero["poster"]}"' if n == 0 and hero.get("poster") else "")
                + ' aria-hidden="true">'
                f'<source src="{c}" type="video/mp4"></video>'
                for n, c in enumerate(_clips))
        elif hero.get("poster"):
            # A still banner gets the poster as an element too, not just as the class
            # background: the parallax translates an element, and a background cannot be
            # moved independently of the box it fills.
            bg = (f'<img class="hbg" src="{hero["poster"]}" alt="" aria-hidden="true">')
        else:
            bg = ""
        badge = f'<em class="hbadge">{hero["badge"]}</em>' if hero.get("badge") else ""
        # rel=noopener because target=_blank without it hands the new tab a handle on this
        # window; the glyph leads the label so the jump is legible before the words are read.
        act = (f'<a class="hbtn" href="{hero["action"][1]}" target="_blank" rel="noopener">'
               f'{EXT_ICON}{hero["action"][0]}</a>') if hero.get("action") else ""
        # The banner's bottom edge is one row: copy on the left, action on the right, both
        # sitting on the baseline. The action stays last in source order so it is also last
        # in the tab order, whichever side it renders on.
        head_html = (f'<header class="hero {hero["class"]}'
                     f'{" lede-above" if hero.get("lede_above") else ""}">{bg}{badge}'
                     f'<div class="hrow"><div class="hcopy">{head_html}</div>'
                     f'{act}</div></header>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{doc_title}</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="stylesheet" href="{CSS_HREF}">
<style>.light{{{theme_vars('light')}}} .dark{{{theme_vars('dark')}}}{extra_css}</style>
</head><body>
<input type="checkbox" id="navtog" hidden>
<div class="mtop"><label for="navtog" class="navbtn" aria-label="Menu">
<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"
stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></label>
<a class="mbrand" href="index.html"><i class="mark"></i><b>{BRAND}</b></a>
{dswitch()}</div>
<nav class="side">{nav}</nav>{SIDE_SCROLL_JS}
<label for="navtog" class="navdim"></label>
<main>{head_html}{content}</main>
<p id="copied" class="sr" role="status" aria-live="polite">{COPY_ICON}<span class="ctxt"></span></p>
{REVEAL_JS}{PARALLAX_JS}{hero_js}{EDIT_JS}{COPY_JS}
</body></html>"""


# Inter is OFL-1.1, so it ships as a webfont. Exposure (205TF) forbids sharing the font
# software, so its specimens are rasterised at build time and the .otf is never published.
CSS = """@font-face{font-family:Inter;src:url(fonts/Inter.ttf);font-weight:100 900;font-display:swap}
*{box-sizing:border-box}
/* The whole page is this one flex row: panel, gutter, content. The gutter is the row's gap
   and nothing here restates the panel's width. The gap is 8px tighter than the trailing
   window margin on purpose — the panel already carries 16px of its own padding, so an equal
   gap read wider on the left than on the right. */
body{margin:0;background:#F9F4F1;color:#211217;
font:15px/1.55 ui-sans-serif,-apple-system,"SF Pro Text",system-ui,sans-serif;
letter-spacing:-.03em;display:flex;align-items:flex-start;gap:16px;padding:4px 24px 0 4px}
b,strong{font-weight:500}
/* Everything that is code is mono. Only a live token is chipped, and .tok is only ever
   emitted in a table's first column — so the fill means "this is the symbol to type",
   and a snippet, file path or literal quoted in prose cannot be mistaken for one. */
/* One size and weight for every token label, whatever it sits in: the sub-label line
   was 11px prose with a 12px token in it, which read as two different type systems. */
code,.tok{font:11px ui-monospace,"SF Mono",Menlo,monospace}
/* Click copies the label; see COPY_JS. The pointer and the hover fill are the affordance,
   so they belong to the same selector that can actually be clicked. */
.tok{background:rgba({_BARK_RGB},.06);border-radius:5px;padding:2px 5px;cursor:pointer}
.tok:hover{background:rgba({_BARK_RGB},.11)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
/* Copy toast. Bottom centre, 140ms in and out — long enough to read as a movement, short
   enough that it is gone before you look for it. It is the .sr live region until a copy
   happens, so `position` and the clip have to be overridden here, not merely added to. */
#copied.on{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);
width:auto;height:auto;clip:auto;overflow:visible;z-index:20;
margin:0;padding:9px 15px;border-radius:999px;pointer-events:none;
background:#211217;color:#fff;font-size:13.5px;font-weight:500;display:inline-flex;align-items:center;gap:7px;
box-shadow:0 8px 24px rgba(33,18,23,.24);
animation:toastin .14s cubic-bezier(.2,.8,.2,1)}
@keyframes toastin{from{opacity:0;transform:translate(-50%,6px)}
to{opacity:1;transform:translateX(-50%)}}
/* currentColor, so the glyph is the same white as the label rather than a
   second near-white of its own. */
#copied svg{width:15px;height:15px;stroke-width:2.5;flex:0 0 auto}
@media(prefers-reduced-motion:reduce){#copied.on{animation:none}}
/* side nav — sticky rather than fixed so it holds a track in the row and cannot overlap
   the content. Leading and top padding are 8 against the trailing 16: the panel sits tight
   into the corner, so its first item clears the window by 12px rather than 20, and the brand
   deliberately rides 8px above the h1 it used to line up with. */
.side{position:sticky;top:4px;flex:0 0 240px;max-height:calc(100vh - 8px);overflow-y:auto;
z-index:9;padding:8px 16px 16px 8px}
/* One declaration for every item, brand included — it is the Welcome entry and lights up
   like any other. Stadium rather than a fixed radius because the brand is two lines and
   47px tall against the others' 33px: at any fixed value the tall item reads as a rounded
   rectangle while the short ones read as pills. A stadium is the only radius that renders
   the same shape at both heights, in every state, on every page. */
.side a{border-radius:999px}
/* The wordmark and the switcher share a row; the gap that used to sit under the wordmark
   belongs to the row now, or the menu would open 20px away from its own control. */
.brandrow{display:flex;align-items:center;gap:2px;margin-bottom:20px}
.side .brand{flex:1;min-width:0;display:flex;align-items:center;gap:10px;
text-decoration:none;color:#211217;
font-size:13.5px;font-weight:500;line-height:1.25;padding:7px 14px}
/* design-system switcher */
.dsw{position:relative;flex:0 0 auto}
.dsw summary{list-style:none;cursor:pointer;display:flex;align-items:center;
justify-content:center;width:26px;height:26px;border-radius:999px;color:#755760}
.dsw summary::-webkit-details-marker{display:none}
.dsw summary:hover{background:#F0DFD1;color:#211217}
.dsw summary svg{transition:transform .16s}
.dsw[open] summary{color:#211217}
.dsw[open] summary svg{transform:rotate(180deg)}
/* Right-aligned to the chevron, not the panel: it reads as belonging to the control that
   opened it. z-index clears the sticky status key at the foot of the panel. */
.dswmenu{position:absolute;top:calc(100% + 7px);right:0;z-index:12;min-width:210px;
padding:6px;background:#fff;border-radius:16px;border:1px solid rgba(33,18,23,.07);
box-shadow:0 12px 32px rgba(33,18,23,.16)}
.dswitem{display:flex;align-items:center;justify-content:space-between;gap:10px;
padding:8px 11px;border-radius:999px;font-size:13.5px;font-weight:500;color:#211217;
white-space:nowrap}
/* Not a link and not a button: there is nothing to navigate to yet. Greyed and
   not-allowed says so without pretending to be clickable. */
.dswitem.off{color:#A98993;cursor:not-allowed}
.dswtick{font-style:normal;color:#2E9B5B}
.dswsoon{font-style:normal;font-size:9.5px;font-weight:500;text-transform:uppercase;
letter-spacing:.06em;color:#755760;background:#F0DFD1;padding:3px 7px;border-radius:999px}
/* Masked rather than an <img> so the mark takes a token colour rather than the flat fill
   baked into the file. */
.mark{width:26px;height:26px;flex:0 0 auto;background:#4C2934;
-webkit-mask:url(logo.svg) center/contain no-repeat;mask:url(logo.svg) center/contain no-repeat}
.side .brand .btxt{display:flex;flex-direction:column;gap:1px;min-width:0}
.side .brand b{font-weight:500}
.side .brand i{font-style:normal;font-size:12px;font-weight:400;color:#755760}
.navsec{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.07em;
color:#A98993;padding:0 14px;margin:0 0 6px}
.side ul{list-style:none;margin:0 0 22px;padding:0}
.side ul:last-child{margin-bottom:0}
/* Flex, not block: a label that wraps ("Toolbars (top)") must not run under its dot. */
.side a:not(.brand){display:flex;align-items:center;gap:8px;text-decoration:none;
color:#755760;font-size:13.5px;font-weight:500;padding:6px 14px}
.side a .dot{flex:0 0 auto}
/* Hover and active fills are generated from the shared Sand/Bark state pair further down. */
.side a.par{color:#211217}
.side .sub{margin:2px 0 4px;padding-left:11px;border-left:1px solid rgba(33,18,23,.1)}
.side .sub a{font-size:13px;font-weight:400;padding:5px 14px}
/* status — dot in the nav, pill on the page, same three hues in both. */
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.dot.live{background:#2E9B5B} .dot.wip{background:#DF9E22} .dot.todo{background:#D45B5B}
/* Holds the slot for a page with no status, so every label starts at the same x. */
/* Wraps because the title is a fixed-width raster: on a phone it would otherwise push the
   pill off-page instead of giving way to it. The auto margin keeps the pill right-aligned
   once wrapped, where space-between has nothing left to distribute. */
.phead{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}
/* With no lede under it the title would sit on the first card; this is the gap the lede's
   own bottom margin used to provide. */
.phead.nolede{margin-bottom:26px}
/* The page header's pill is drawn at twice the base scale — every dimension doubled, so it
   stays the same pill. The base size below is the table cell's, where it labels a row. */
.phead .pstat{margin-left:auto;font-size:16px;gap:8px;padding:6px 14px 6px 12px}
.phead .pstat i{width:10px;height:10px}
.pstat{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;font-size:11.5px;
font-weight:500;padding:4px 11px 4px 9px;border-radius:99px;white-space:nowrap}
.pstat i{width:7px;height:7px;border-radius:50%;background:currentColor;flex:0 0 auto}
.pstat.live{background:#D8EEDC;color:#1B6B3F} .pstat.wip{background:#F7E5C2;color:#666100}
.stcell .pstat{font-size:11px;padding:3px 10px 3px 8px}
/* The Status column's key, in the foot of the card whose column it explains. Legend scale,
   not table scale: the pills are the smallest thing on the page that still reads as the
   pill it maps to. */
/* status key — sticky to the foot of the panel, opaque so the nav scrolls behind it
   rather than through it. The meanings are the title attributes. */
.stleg{position:sticky;bottom:-16px;z-index:2;margin:18px -16px -16px;padding:9px 16px 11px;
background:#F9F4F1;border-top:1px solid rgba(33,18,23,.08);
display:flex;flex-wrap:wrap;gap:3px 10px}
.stleg span{display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:500;
letter-spacing:0;color:#A98993;cursor:default}
.stleg .dot{width:6px;height:6px}
/* No horizontal padding and no auto margin: the row's gap and the body's trailing margin
   are the only things setting the measure, so there is one number to change, not three.
   The cap only bites past ~1450px, where filling the window would stretch the tables. */
main{flex:1;min-width:0;max-width:1180px;padding:16px 0 56px}
/* display type ships as Exposure rasters — see exposure_text() */
h1 .h1img{display:block;width:auto;margin-left:-2px}
/* Height is pinned because these PNGs are 3x for retina — with width/height:auto the
   intrinsic (3x) size wins over the HTML attributes and the hero renders triple size. */
/* The heading string, present for selection, copy and Cmd-F. Clipped rather than
   display:none or width:0 — both of those take it out of the selection too, which is the
   whole point of it being here. Zero height so it costs no layout. */
.rtxt{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
clip-path:inset(50%);white-space:nowrap;border:0}
/* icon grid */
.igrid{display:grid;grid-template-columns:repeat(auto-fill,48px);gap:8px;margin:0 0 8px}
.icell{position:relative;width:48px;height:48px;display:flex;align-items:center;
justify-content:center;border-radius:11px;background:#fff;
cursor:default;outline:none;color:#4C2934}
.icell:hover,.icell:focus{background:#F6ECE4}
.icell svg{width:24px;height:24px;display:block;stroke-width:2}
.itip{position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);
background:#211217;color:#fff;font-size:11px;line-height:1.35;white-space:nowrap;
padding:5px 8px;border-radius:7px;opacity:0;pointer-events:none;transition:opacity .12s;z-index:5}
.icell:hover .itip,.icell:focus .itip{opacity:1}
/* page-level tabs (Colors) — pills, matching the section tabs this page used to carry */
.ptabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 22px}
.ptabs a{text-decoration:none;font-size:12.5px;font-weight:500;color:#755760;
padding:6px 12px;border-radius:999px;background:#F4E7DD}
.ptabs a:hover{background:#EADFD6;color:#211217}
.ptabs a[aria-selected=true]{background:#4C2934;color:#fff}
.tabpanel[hidden]{display:none}
/* principles (welcome) — carded like a sectionised block, with its label in the head.
   Hairlines between principles rather than gaps: inside a card, whitespace alone reads as
   uneven padding. */
.prin{margin:0;padding:17px 0}
.prin+.prin{border-top:1px solid rgba(33,18,23,.05)}
.shead+.prin{padding-top:0}
/* The card's own padding closes it out; a row's would double up. */
.prin:last-child{padding-bottom:0}
.prin h3{margin:0 0 5px}
.prin p{margin:0;font-size:14px;line-height:1.55;color:#755760;max-width:720px}
.avrow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px 8px;
align-items:start}
.avcell{display:flex;flex-direction:column;align-items:center;gap:8px;min-width:0}
.avcell em{font-style:normal;font-size:10.5px;line-height:1.35;text-align:center;
color:var(--foregroundTertiary)}
.avx{border-radius:50%;display:flex;align-items:center;justify-content:center;flex:0 0 auto;
font-weight:400;font-family:ui-rounded,"SF Pro Rounded",ui-sans-serif,system-ui,sans-serif}
.shwell{display:flex;align-items:center;justify-content:center;width:76px;height:60px;
border-radius:10px;background:#F4E7DD;flex:0 0 auto}
.shsw{width:40px;height:40px;border-radius:9px;background:#fff}
.stub{border:1px dashed rgba(33,18,23,.18);border-radius:12px;padding:20px 22px;color:#755760}
.stub b{display:block;color:#211217;font-size:14.5px;margin-bottom:4px}
.stub p{margin:0;font-size:14px;line-height:1.55;color:#755760;max-width:720px}
/* Welcome's closing image. Card radius so it belongs to the page, but no card around it —
   it is the punchline, not a section. */
.closer{margin:32px 0 0}
.closer img{display:block;width:100%;height:auto;border-radius:32px}
/* burger — only below the sidebar breakpoint */
.navbtn,.navdim,.mtop{display:none}
@media(max-width:900px){
/* The panel leaves the row and becomes an overlay, so the row collapses to one column. */
body{display:block;padding:0 20px}
/* Needs a surface of its own here, unlike on desktop where it sits on the page: over the
   scrim it is the only opaque thing between the labels and the content behind them.
   Must clear the left inset too, or the panel stays partly on screen when closed. */
.side{position:fixed;top:56px;left:4px;bottom:4px;width:240px;max-height:none;
background:#F9F4F1;border-radius:14px;box-shadow:0 12px 40px rgba(33,18,23,.22);
transform:translateX(calc(-100% - 4px));transition:transform .18s ease}
#navtog:checked~.side{transform:none}
main{max-width:none}
/* The wordmark and its switcher have to be reachable without opening the drawer, so they
   ride in a bar with the burger. The drawer's own brandrow stands down rather than
   repeating the title two inches away, and .mbrand keeps the link to Welcome. */
.mtop{display:flex;align-items:center;gap:10px;position:fixed;top:0;left:0;right:0;z-index:11;
padding:8px 12px;background:rgba(249,244,241,.92);backdrop-filter:blur(10px);
border-bottom:1px solid rgba(33,18,23,.08)}
.navbtn{display:flex;position:static;align-items:center;
justify-content:center;width:34px;height:34px;border-radius:9px;color:#211217;cursor:pointer;
background:transparent;border:1px solid rgba(33,18,23,.1);flex:0 0 auto}
.mbrand{flex:1;min-width:0;display:flex;align-items:center;gap:8px;text-decoration:none;
color:#211217;font-size:13.5px;font-weight:500;white-space:nowrap;overflow:hidden}
.brandrow{display:none}
#navtog:checked~.navdim{display:block;position:fixed;inset:0;z-index:8;background:rgba(33,18,23,.4)}
main{padding-top:58px}
}
/* Line breaking. Two rules rather than a property per component, so a new block inherits
   the right one by being a heading or a paragraph.
   balance evens the line lengths of short display text — headings, ledes, pull quotes, the
   claim in a stat row. Browsers stop applying it past about six lines, so it is wasted on
   running copy and would leave a long paragraph unnecessarily narrow.
   pretty is the body-copy counterpart: it leaves the measure alone and only works the last
   lines, so a paragraph never ends on a single word. Both are ignored where unsupported,
   which costs nothing but the wrapping we have today. */
h1,h2,h3,h4,.lede,.pull,.bstat b,.val h3,.val .vsub,.stub b,.arch blockquote,
.textxl,.textXL,.prim,.toast b,.alert b,.stile figcaption b,.reg b,
.ddpair p{text-wrap:balance}
p,li,dd,figcaption,.us,.note,.hx,.tksub,.afacts p,.afacts li{text-wrap:pretty}
h1{font-size:48px;font-weight:500;margin:0 0 5px;letter-spacing:-.021em}
.lede{color:#755760;font-size:14px;line-height:1.55;margin:0 0 30px;max-width:720px}
.lede.sub{margin:-4px 0 12px}
/* The label itself is an Exposure raster (see exposure_h2), so font-size here only
   governs the .ct count beside it and the alt text if the image fails. flex-end rather
   than baseline: an image's baseline is its bottom edge, and the raster carries the
   face's descent as padding, which would drop the count below the heading. */
h2{font-size:32px;font-weight:500;color:#211217;letter-spacing:-.03em;
margin:34px 0 11px;display:flex;align-items:flex-end;gap:9px}
h2 .h2img{display:block;width:auto;margin-left:-2px}
h2 .ct{font-size:20px;line-height:1.6}
h3{font-size:20px;font-weight:500;color:#211217;letter-spacing:-.03em;
margin:22px 0 8px;display:flex;align-items:baseline;gap:8px}
.ct{opacity:.35;font-weight:400}
em.tag{font-style:normal;font-size:9px;text-transform:uppercase;letter-spacing:.06em;
padding:2px 6px;border-radius:4px;font-weight:500}
.new{background:#CCE1CE;color:#143C1A}
/* primitives */
.scale{display:flex;gap:1px;flex-wrap:nowrap;margin-bottom:20px}
.sw{flex:1 1 0;min-width:0;height:66px;border-radius:0;padding:7px 8px;overflow:hidden;
display:flex;flex-direction:column;justify-content:space-between}
.sw b{font-size:11.5px;font-weight:500} .sw code{opacity:.9}
/* Every h2's content is carded by sectionise() — see that function for what stays out. */
/* One number drives the vertical rhythm of every section: card padding, the gap between
   cards, and the space around a heading block. Change --sy and the whole page breathes
   together instead of three values drifting apart. */
:root{--sy:40px}
.scard{background:#fff;border-radius:32px;padding:var(--sy) 32px;margin:var(--sy) 0}
.shead{margin:var(--sy) 0 32px}
.shead>:first-child{margin-top:0}
.shead>:last-child{margin-bottom:0}
/* A heading with nothing under it would leave the card padded out below it. */
.shead:last-child{margin-bottom:0}
/* Primitives: a swatch strip is its own label, so a rule per ramp is noise. */
.nodiv .shead{border-bottom:0;padding-bottom:0;margin:32px 0 18px}
/* The card's padding is the gutter now, so a child's own trailing margin would read as
   uneven bottom padding. */
.scard>:last-child{margin-bottom:0}
.scard>:first-child{margin-top:0}
/* tables */
/* Fixed layout so the declared widths are what render: with auto layout the browser
   re-sizes columns per table from its content, so two tables with the same spec on
   the same page still landed on different column edges. */
table{width:100%;table-layout:fixed;border-collapse:collapse;margin-bottom:8px}
/* Every ttable declares its column widths as percentages; fixed layout is what makes them
   authoritative rather than hints. Under auto layout a cell is sized by its content's
   min-content width, and a code panel of 90-character paths reports that width even though
   it is a scroll container — which is how one opened Where cell pushed the table past the
   page. Fixed sizing is also what lets the panel's own overflow-x do its job. */
table.tt{table-layout:fixed}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#A98993;
font-weight:500;padding:0 10px 9px 0}
td{padding:9px 10px 9px 0;vertical-align:middle;white-space:nowrap}
tbody tr+tr td{border-top:1px solid rgba(33,18,23,.05)}
td:first-child,th:first-child{padding-left:0}
.tk{font-weight:500;font-size:13.5px;white-space:normal;word-break:break-word}
/* Foundation rows: a leading Lucide glyph, and the whole row as one target. The anchor is
   stretched over the row with an ::after rather than wrapping every cell in a link — that
   keeps one <a> per row for a screen reader while giving the pointer the full width.
   The row needs a positioned ancestor for that to anchor against; <tr> is not reliably
   positionable across browsers, so each cell is the containing block and the ::after is
   sized against the row via a tall inset. */
.fico{display:inline-flex;vertical-align:-3px;margin-right:9px;color:#A98993}
.fico svg{width:16px;height:16px;stroke-width:1.75}
tbody tr:has(.rowlink){cursor:pointer}
/* The hover fill wraps the row instead of butting against its text: the table is pulled out
   by --rowbleed on each side and the edge cells padded back by the same amount, so the copy
   keeps the card's measure while the fill runs wider than it. One value for the bleed and
   the radius — the fill turns its corner exactly where it clears the text. Radius needs
   separate borders; a collapsed table drops border-radius on its cells. */
table:has(.rowlink){--rowbleed:12px;border-collapse:separate;border-spacing:0;
margin-left:calc(-1*var(--rowbleed));width:calc(100% + var(--rowbleed)*2)}
table:has(.rowlink) td:first-child,table:has(.rowlink) th:first-child{
padding-left:var(--rowbleed)}
table:has(.rowlink) td:last-child,table:has(.rowlink) th:last-child{
padding-right:calc(10px + var(--rowbleed))}
tbody tr:has(.rowlink):hover td{background:#FBF7F4}
tbody tr:has(.rowlink):hover td:first-child{
border-radius:var(--rowbleed) 0 0 var(--rowbleed)}
tbody tr:has(.rowlink):hover td:last-child{
border-radius:0 var(--rowbleed) var(--rowbleed) 0}
/* The 1px rule would cut across the corners it meets — on the hovered row and on the one
   under it, which owns the line below. */
tbody tr:has(.rowlink):hover td,tbody tr:has(.rowlink):hover+tr td{border-top-color:transparent}
tbody tr:has(.rowlink):hover .fico{color:#4C2934}
tbody tr:has(.rowlink) td{position:relative}
.rowlink::after{content:"";position:absolute;inset:0;width:100vw;z-index:1}
.tk a{color:#211217;text-decoration:none;border-bottom:1px solid rgba(33,18,23,.22)}
.tk a:hover{border-bottom-color:#4C2934}
.tksub{display:block;font-weight:400;font-size:11px;color:#A98993}
.us{color:#755760;font-size:12.5px;white-space:normal}
/* Fixed layout means a column cannot grow to fit, so a long unbroken symbol like
   Color(uiColor:UIColor.systemGroupedBackground) must be allowed to break or it
   spills across the next column. */
.us code{color:#755760;overflow-wrap:anywhere}
.unused{font-style:normal;color:#A98993}
/* per-foundation swatches — same cell anatomy, different preview */
/* Minimums, not fixed sizes: the box aligns the labels across rows, and a specimen taller
   or wider than it grows the row rather than being squeezed into it. A fixed 40px height
   drew the 48px Exposure raster — 50px tall — at 40 and stretched the glyphs. */
.fspec{font-style:normal;line-height:1;color:#211217;min-width:44px;flex:0 0 auto;
display:flex;align-items:center;justify-content:center;min-height:40px}
/* The raster carries its own 1x size in its width attribute, so it is left to govern: a
   CSS width — even `auto` — outranks the attribute and would draw the 3x file at 3x.
   height:auto only releases the height attribute, leaving the ratio to the width. */
.fspec img{display:block;max-width:100%;height:auto}
/* The heading rows' value is the specimen. Scales down rather than overflowing: the size
   it claims is written into the words, so a narrow window shrinks the drawing, not the
   fact. height:auto keeps the raster's own ratio once width gives way. */
.fval{display:block;max-width:100%;height:auto;line-height:1.1;color:#211217;
letter-spacing:-.02em}
.mtrack{flex:0 0 auto;width:68px;height:40px;display:flex;align-items:center}
.mbar{height:12px;border-radius:3px;background:#4C2934;min-width:1px}
.mbox{border-radius:3px;background:#4C2934;min-width:1px;min-height:1px}
.c{display:inline-flex;align-items:center;gap:11px}
.chip{width:40px;height:40px;border-radius:9px;border:1px solid rgba(33,18,23,.16);flex:0 0 auto}
/* Solid swatches carry a token value as fill, so the hairline that keeps a white
   colour swatch visible would only muddy them. */
.chip.solid{background:#4C2934;border-color:transparent}
.cmeta{display:flex;flex-direction:column;gap:1px;min-width:0}
.prim{font-weight:500;font-size:13px;color:#211217}
.hx{font-size:11px;color:#A98993}
.al{font-style:normal;font-weight:500;font-size:10.5px;color:#755760;margin-left:4px}
/* anatomy carousel — one annotated component per slide; the per-slide rules that move the
   track are generated next to ANATOMY_SLIDES and arrive as the page's extra_css. */
.anat{margin:16px 0 40px}
/* Off-screen rather than hidden, so the dots stay keyboard-reachable. */
.anatr{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
.anat-view{position:relative;overflow:hidden}
.anat-track{display:flex;transition:transform .32s cubic-bezier(.4,0,.2,1)}
.anat-slide{flex:0 0 100%;margin:0}
.anat-slide img{display:block;width:100%}
/* Overlaid on the frame, so the arrows sit inside the diagram's own margin. Only the
   checked slide's pair is displayed — see ANATOMY_CSS. */
.anat-nav{display:none;position:absolute;inset:0;align-items:center;
justify-content:space-between;padding:0 14px;pointer-events:none}
.anat-nav label{pointer-events:auto;width:34px;height:34px;border-radius:50%;display:flex;
align-items:center;justify-content:center;cursor:pointer;color:#211217;
background:rgba(255,255,255,.9);backdrop-filter:blur(10px);
border:1px solid rgba(33,18,23,.1);box-shadow:0 1px 3px rgba(33,18,23,.07)}
.anat-nav label:hover{background:#fff;border-color:rgba(33,18,23,.2)}
/* Every control here is an icon, so its name exists only as a title tooltip and this
   off-screen text. */
.anat-nav label span{position:absolute;width:1px;height:1px;
overflow:hidden;clip-path:inset(50%)}
/* welcome page — keynote editorial */
.eyebrow{display:block;font-style:normal;font:500 11px ui-monospace,"SF Mono",Menlo,monospace;
letter-spacing:.14em;text-transform:uppercase;color:#A98993;margin:0 0 4px}
.next{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:28px}
@media(max-width:760px){.next{grid-template-columns:1fr}}
.next a{display:flex;flex-direction:column;gap:3px;text-decoration:none;background:#F6ECE4;
border-radius:14px;padding:16px 18px;transition:background .15s}
.next a:hover{background:#F0DFD1}
.next b{color:#211217;font-size:14.5px}
.next span{color:#755760;font-size:12.5px;line-height:1.45}
/* roadmap — dark closing section */
.stage .eyebrow{color:rgba(255,255,255,.45)}
text-transform:uppercase;color:rgba(255,255,255,.4);padding:22px 0 8px 36px}
.tlm{width:21px;height:21px;border-radius:99px;flex:0 0 auto;display:grid;place-items:center;
background:#211217;border:1.5px solid rgba(255,255,255,.35);z-index:1}
.tlm.done{background:#16A34A;border-color:#16A34A}
.tlm.bl{border-style:dashed;border-color:rgba(255,255,255,.3)}
.tli.done b{color:rgba(255,255,255,.55)}
letter-spacing:0;color:rgba(255,255,255,.35)}
/* semantics family tabs */
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 22px;position:sticky;top:0;z-index:7;
padding:10px 0;background:rgba(249,244,241,.94);backdrop-filter:blur(10px)}
.tabs a{text-decoration:none;font-size:12.5px;font-weight:500;color:#755760;
padding:6px 13px;border-radius:99px;background:#F1E7DF}
.tabs a:hover{background:#EADFD6;color:#211217}
.tabs a.active{background:#211217;color:#fff}
h2[id],h3[id]{scroll-margin-top:120px}
/* components — one section per component, light + dark side by side, minimal chrome */
.comp{margin:0 0 34px}
.comp-h{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 11px}
.comp-h b{font-size:15px;font-weight:500;color:#211217}
.comp-h code{color:#A98993}
.comp-d{color:#755760;font-size:13px;margin:0 0 13px}
.cpair{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:760px){.cpair{grid-template-columns:1fr}}
.cc{font-size:10px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:#A98993;margin:0 0 7px 2px}
/* The light theme's surfacePrimary is white, which is also the card behind it, so without
   the hairline the light half of a light/dark pair has no edge at all. */
.cin{padding:24px;background:var(--surfacePrimary);border:1px solid var(--border);
border-radius:14px;height:100%;
display:flex;flex-direction:column;justify-content:center}
.cin>*{width:100%}
.cin>.rowx{justify-content:center}
.cin>.btnstack{max-width:300px;margin:0 auto}
.stack{display:flex;flex-direction:column;gap:6px}
.rowx{display:flex;gap:9px;flex-wrap:wrap;align-items:center}
/* AvatarView: 44pt circle, initials 16pt regular rounded, HHAccentHue fill/foreground */
.av{width:36px;height:36px;border-radius:99px;display:grid;place-items:center;
font:13px ui-rounded,-apple-system,sans-serif}
.av.sm{width:28px;height:28px;font-size:11px}
/* HeidiPrimary/Secondary/Outline button styles: full-width, minHeight 38 + 6 padding, radius 14,
   headline type, heidiShadow(.standard) */
.btnstack{display:flex;flex-direction:column;gap:9px;max-width:340px}
.btn{display:flex;align-items:center;justify-content:center;min-height:44px;border-radius:14px;
font-size:14px;font-weight:600}
/* HHSecondaryButton size .s: fit-content, 40pt, radius 12, no shadow */
.btns{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 13px;border-radius:12px;
font-size:13px;font-weight:600;background:var(--fillPrimary);color:var(--foregroundPrimary)}
.tg2{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:500}
/* HHAlert: icon + heading5 title + paragraph2 secondary message, radius 12 */
.alert{display:flex;gap:11px;align-items:flex-start;padding:12px 15px;border-radius:12px;margin-bottom:9px}
.alert .ai{flex:0 0 auto;width:19px;height:19px;margin-top:2px}
.alert b{display:block;font-size:14.5px;font-weight:500;margin:0 0 2px}
.alert p{margin:0;font-size:13px;color:var(--foregroundSecondary);line-height:1.45}
.page{border-radius:16px;overflow:hidden}
.pin{padding:14px}
.ttl{font-size:19px;font-weight:400;color:var(--foregroundPrimary);margin:2px 2px 1px}
.ssub{font-size:12.5px;color:var(--foregroundSecondary);margin:0 2px 13px}
.sec{font-size:13px;font-weight:500;color:var(--foregroundSecondary);margin:0 2px 7px}
.card{background:var(--surfaceTertiary);border-radius:12px;overflow:hidden;margin-bottom:14px}
/* Session groups: SessionListGroupMetrics.cornerRadius = HHRadius.xl2_5 (28) */
.card.sess{border-radius:22px}
.li{position:relative;display:flex;align-items:center;gap:12px;padding:12px 14px}
.li+.li::before{content:"";position:absolute;left:46px;right:0;top:0;height:1px;background:var(--border)}
.sess .li+.li::before{left:54px}
.lm{flex:1;min-width:0;display:flex;flex-direction:column}
.lm b{font-size:14px;font-weight:400;color:var(--foregroundPrimary)}
.lm i{font-style:normal;font-size:12px;color:var(--foregroundSecondary)}
.lr{font-size:15px;color:var(--foregroundTertiary)}
.lv{font-size:13px;color:var(--foregroundSecondary);display:flex;align-items:center;gap:5px;white-space:nowrap}
.lchev{color:var(--foregroundTertiary);font-size:15px}
.ic{width:20px;height:20px;flex:0 0 auto;color:var(--foregroundSecondary)}
/* HeidiToggle: UISwitch proportions, onTint fillAccent */
.tgl{width:44px;height:27px;border-radius:99px;background:var(--fillAccent);position:relative;flex:0 0 auto}
.tgl i{position:absolute;right:2px;top:2px;width:23px;height:23px;border-radius:99px;background:#fff}
.ubub{background:var(--fillSecondary);color:var(--foregroundPrimary);padding:9px 14px;border-radius:18px;font-size:13px}
.ans{color:var(--foregroundPrimary);font-size:13px;line-height:1.5}
.cite{display:inline-flex;align-items:center;gap:4px;background:var(--fillSecondary);color:var(--foregroundSecondary);font-size:12px;font-weight:500;padding:2px 6px;border-radius:8px;vertical-align:baseline}
.cn{color:var(--foregroundSecondary);font-weight:600}
.kp{background:var(--fillInfoMuted);color:var(--foregroundInfo);font-size:12.5px;font-weight:500;padding:9px 12px;border-radius:11px}
/* Recording orb: 100pt circle, icon cut out of the fill */
.orbwrap{display:flex;gap:34px;align-items:center;justify-content:center;padding:10px 0 4px}
.orbcol{display:flex;flex-direction:column;align-items:center;gap:12px}
.orb{width:84px;height:84px;border-radius:99px;display:grid;place-items:center}
.orb svg{width:30px;height:30px}
.orblbl{font-size:11px;color:var(--foregroundTertiary)}
.rectime{display:flex;align-items:center;gap:7px;font-size:16px;color:var(--foregroundSecondary)}
.recdot{width:9px;height:9px;border-radius:99px;background:var(--fillNegative);animation:pulse 1s ease-in-out infinite}
@keyframes pulse{50%{opacity:.5}}
/* ToastView: radius md, solid status fills or surfaceTertiary */
.toast{display:flex;align-items:flex-start;gap:10px;padding:11px 13px;border-radius:8px;margin-bottom:9px}
.toast svg{flex:0 0 auto;width:18px;height:18px;margin-top:1px}
.toast b{display:block;font-size:13.5px;font-weight:500}
.toast p{margin:1px 0 0;font-size:12.5px}
.toast .tx{margin-left:auto;font-size:13px;flex:0 0 auto}
.band{background:var(--surfacePrimary);padding:11px 13px;border-top:1px solid var(--border)}
.inp{background:var(--surfaceTertiary);border-radius:17px;
padding:11px 13px;font-size:13px;color:var(--foregroundTertiary);
display:flex;align-items:center;justify-content:space-between}
.ibtn{display:inline-flex;align-items:center;justify-content:center;height:26px;min-width:26px;
padding:0 9px;border-radius:9px;background:var(--fillPrimary);color:var(--foregroundPrimary);font-size:12px}
.send{width:25px;height:25px;border-radius:99px;background:var(--fillAccent)}
/* .note lives with its tinted variants further down — its fill is a semantic token. */
/* ---- problems page ---------------------------------------------------- */
@media(max-width:760px){.stats{grid-template-columns:repeat(2,1fr)}}
border:none;background:#F1E7DF;padding:6px 13px;border-radius:99px}
.ctl .sep{flex:1 1 auto}
.ctl .warn[aria-pressed=false]{color:#9A3412;background:#FEF3EA}
.hint+.ctl{margin-top:26px}
/* 1 · four systems, then the collision */
.defs{display:grid;grid-template-columns:1fr 1fr;gap:13px}
@media(max-width:620px){.defs{grid-template-columns:1fr}}
.def{background:#FAF6F2;border-radius:11px;overflow:hidden}
.def>header{padding:11px 13px 9px;border-bottom:1px solid rgba(33,18,23,.07);
background:rgba(252,250,248,.9)}
.def h4{margin:0;font:500 13px ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:0}
.def h4 em{font-style:normal;color:#A98993}
.def .src{font-size:11px;color:#A98993;margin-top:3px}
.duo{display:flex}
.duo span{flex:1;height:58px;display:flex;align-items:flex-end;gap:6px;padding:6px 9px;
font:10px ui-monospace,Menlo,monospace}
.duo em{font-style:normal;opacity:.6;text-transform:uppercase;letter-spacing:.05em}
.bar{display:flex;height:6px;border-radius:99px;overflow:hidden;background:rgba(33,18,23,.07);margin:11px 0 5px}
.bar i{display:block}
.blbl{display:flex;justify-content:space-between;font-size:11.5px;color:#755760}
.verdict{margin:14px 2px 0;font-size:13px;color:#755760}
.verdict.bad{color:#7F1D1D}
.verdict b{font-weight:500;color:#211217}
.verdict.bad b{color:#7F1D1D}
/* 2 · vocabulary */
.vin{width:100%;font:inherit;font-size:14px;padding:10px 14px;border-radius:10px;
border:none;background:#FAF6F2;margin:0 0 11px}
.vin:focus{outline:none;box-shadow:0 0 0 2px #4C2934}
.vpair{display:grid;grid-template-columns:1fr 1fr;gap:13px}
@media(max-width:620px){.vpair{grid-template-columns:1fr}}
.vcol{background:#FAF6F2;border-radius:11px;padding:12px 13px;min-height:150px}
.vcol h4{margin:0 0 2px;font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:#A98993}
.vcol .n{font-size:20px;font-weight:400;letter-spacing:-.025em;margin:0 0 9px}
.vcol .n em{font-style:normal;font-size:12px;color:#A98993;letter-spacing:0;margin-left:5px}
.vtok{display:flex;align-items:center;gap:7px;padding:3px 0;
font:12px ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:0}
.vtok i{width:13px;height:13px;border-radius:4px;border:1px solid rgba(33,18,23,.18);flex:0 0 auto}
.vfam{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#A98993;margin:9px 0 2px}
.vfam:first-child{margin-top:0}
.vnone{font-size:12.5px;color:#A98993;padding:6px 0}
/* 3 · off-ramp */
transition:opacity .18s,transform .18s}
.hsw.off{outline:1.5px dashed #C2410C;outline-offset:-4px;border-radius:99px}
.hgrid.dim .hsw:not(.hit){opacity:.12}
.hsw.hit{transform:scale(1.06)}
/* 4 · contrast */
.cpanes{display:grid;grid-template-columns:1fr 1fr;gap:13px}
@media(max-width:620px){.cpanes{grid-template-columns:1fr}}
.cpane{border-radius:11px;overflow:hidden;background:#FAF6F2}
.cpane .cb{padding:15px 15px 13px}
.crow{display:flex;align-items:flex-start;gap:9px;font-size:13.5px;line-height:1.45}
.crow svg{flex:0 0 auto;width:18px;height:18px;margin-top:1px}
.cfoot{display:flex;align-items:center;gap:8px;padding:9px 13px;font-size:11.5px;
border-top:1px solid rgba(33,18,23,.07)}
.ratio{font:500 12.5px ui-monospace,Menlo,monospace;letter-spacing:0}
.pill{font-size:10px;font-weight:500;letter-spacing:.06em;text-transform:uppercase;
padding:2px 7px;border-radius:99px}
.pass{background:#D8EEDC;color:#14532D} .fail{background:#FBD9D9;color:#7F1D1D}
.cfoot .sp{margin-left:auto;color:#A98993;font-family:ui-monospace,Menlo,monospace;font-size:11px}
/* 5 · alpha */
.apanes{display:grid;grid-template-columns:1fr 1fr;gap:13px}
@media(max-width:620px){.apanes{grid-template-columns:1fr}}
.apane{border-radius:11px;padding:15px;border:1px solid rgba(255,255,255,.09)}
.apane h5{margin:0 0 2px;font:500 12px ui-monospace,Menlo,monospace;letter-spacing:0;color:#fff}
.apane .as{font-size:11px;color:rgba(255,255,255,.55);margin:0 0 12px}
.achip{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 14px;border-radius:9px;
font-size:12.5px;color:#fff;box-shadow:0 0 0 1px rgba(255,255,255,.14)}
.averd{font-size:11.5px;margin:11px 0 0;color:rgba(255,255,255,.7)}
.averd.bad{color:#FCA5A5}
/* ---- buttons page ------------------------------------------------------ */
/* One state per row so a full-width style is shown at its real width; the caption
   sits above because the buttons themselves are already different heights. */
.bstates{display:flex;flex-direction:column;gap:13px;max-width:320px;margin:0 auto}
.bstate{display:flex;flex-direction:column;gap:5px;align-items:flex-start}
.bstate em{font-style:normal;font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;
color:var(--foregroundTertiary)}
.bx{display:inline-flex;align-items:center;justify-content:center;gap:8px;line-height:1.15;
font-family:-apple-system,"SF Pro Text",system-ui,sans-serif;letter-spacing:-.02em;
white-space:nowrap;flex:0 0 auto}
.bx.wide{display:flex;width:100%}
.bspin{width:14px;height:14px;border-radius:99px;border:2px solid currentColor;
border-right-color:transparent;opacity:.8;animation:bspin .8s linear infinite;flex:0 0 auto}
@keyframes bspin{to{transform:rotate(360deg)}}
/* Call-site lists are long by nature — collapsed so the page stays readable, but
   present, because "how many places" is the whole point of an inventory. */
details.sites{margin:2px 0 20px}
details.sites summary{cursor:pointer;font-size:12.5px;color:#755760;list-style:none}
details.sites summary::-webkit-details-marker{display:none}
details.sites summary::before{content:"▸";color:#A98993;display:inline-block;width:14px}
details.sites[open] summary::before{content:"▾"}
/* A code panel, not a paragraph: these are source references, and they read as such when
   they are monospaced, one per line, path first.
   Two columns used to be the default, which is what broke the layout when the list opened
   inside the Where cell — long unbreakable paths in a narrow auto-width column forced the
   table wider than the page. One column, and the panel is its own scroll container:
   overflow-x makes its min-content contribution zero, so a 90-character path scrolls inside
   the panel instead of stretching the cell that holds it. No table-layout:fixed needed. */
.sitelist{margin:9px 0 0;padding:10px 12px;border-radius:10px;
background:rgba(33,18,23,.045);border:1px solid rgba(33,18,23,.05);
font:11.5px/1.8 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:0;
overflow-x:auto;white-space:pre;max-width:100%}
.sitelist div{color:#755760}
.sitelist .p{color:#4C2934}
.sitelist .l{color:#A98993}
.gap{font-style:normal;color:#A98993}
.warnv{color:#9A3412}
.bgroup{font-size:12px;font-weight:500;text-transform:uppercase;letter-spacing:.06em;
color:#A98993;padding:18px 0 4px}
tr.bgrouprow td{border-top:none!important;padding-bottom:0}
"""

# The tint for the audit markers above: the app's own Negative role, so a reader who has
# met the colour on Semantics already knows what it is asking of them.
_RED = dict(ramps["HHRed"])
_BLUE = dict(ramps["HHBlue"])
_SUN = dict(ramps["HHSunlight"])
_SAND = dict(ramps["HHSand"])
_BARK = dict(ramps["HHBark"])
_FOREST = dict(ramps["HHForest"])
_SKY = dict(ramps["HHSky"])

# A poster per hero page, and the Bark wash for any page whose asset has not been shot yet —
# built here rather than inline below so the rule text stays one flat string.
HERO_BG_CSS = "".join(
    f".hero.{c['class']}{{background:#211217 url({c['poster']}) center/cover no-repeat}}"
    for c in HERO.values() if c.get("poster"))
HERO_BG_CSS += "".join(
    f".hero.{cls}{{background:linear-gradient(135deg,#{_BARK['s950']} 0%,"
    f"#{_BARK['s800']} 62%,#{_BARK['s700']} 100%)}}" for cls in HERO_FALLBACK)

# Out of sync is the majority state right now, and six Red-tinted pills in one table read as
# six errors. fillSecondary is the app's own quiet surface, so the dot and label carry
# the status instead of the fill shouting it. Pulled from HHColors rather than typed,
# like every other value here.
# An active item is tinted by the status it carries. Muted fill against the strong
# foreground, not fillPositive against foregroundPositive: those two are one ramp apart
# (Green 600 on Green 800) and measure 2.16:1, so the label would be unreadable. The muted
# pairing is the same shape the status pills use and clears AA at ~6.4:1.
_S = {t["name"]: t for t in sems}
# Every sidebar destination uses one interaction treatment, independent of its page status.
# Sand 200 is visibly darker than the Sand 50 panel, while foregroundAccent resolves to the
# reviewed Bark 800 foreground. Keeping hover and active in one selector prevents drift.
CSS += (f".side a:hover,.side a.on,.side a.on:hover{{background:#{_SAND['s200']};"
        f"color:#{_S['foregroundAccent']['lh']}}}")

# Tinted like the other two rather than Sand-with-a-hairline. Sand 50 is the page
# background, so that pill measured 1.00:1 against it and needed a border to have a shape
# at all; the negative muted fill is 1.12:1 on sand and 1.22:1 on a card — the same
# separation Live has — so the border has nothing left to do. Same token pair the sidebar
# tint uses, so the pill and the nav row cannot drift apart.
_TODO_FILL, _TODO_FG = "fillNegativeMuted", "foregroundNegative"
CSS += (f".pstat.todo{{background:#{_S[_TODO_FILL]['lh']};"
        f"color:#{_S[_TODO_FG]['lh']}}}")

# Inline alerts take fillSecondary, not fillPrimary — the standing rule for any new one.
# Bound to the token rather than a literal so it follows HHColors rather than drifting.
# No border. That puts a constraint on where a plain .note can go: fillSecondary is the
# page background, so an untinted alert has to sit on a white card or it disappears. The
# .audit and .design variants carry their own fill and are free of that.
CSS += (f".note{{background:#{_S['fillSecondary']['lh']};"
        f"border-radius:12px;padding:14px 16px;"
        f"font-size:13.5px;margin:22px 0;max-width:720px}}"
        # The lead gets its own line, matching .alert b and .toast b. Scoped to the first
        # child so a bold used mid-sentence in some later note is not broken onto a line of
        # its own — only the lead is a heading.
        f".note b:first-child{{display:block;margin-bottom:2px}}"
        f".note.audit{{background:#{_RED['s100']};color:#{_RED['s900']}}}"
        f".note.audit b,.note.audit code{{color:#{_RED['s800']}}}"
        # Info, not warning: a design is a legitimate thing to publish, it just is not the
        # build. Red here would read as "this page is wrong".
        f".note.design{{background:#{_BLUE['s100']};color:#{_BLUE['s900']}}}"
        f".note.design b,.note.design code{{color:#{_BLUE['s800']}}}"
        # Figma exports are 2x, so the pixel width is twice the width it is shown at.
        # Welcome hero: same card geometry as .scard, filled with the image instead of white.
        # Content sits at the bottom, so the crop keeps the figure and doorway clear of it.
        # No top margin: main's padding already sets the inset, and the two stacked put the
        # banner 62px down the page while the brand opposite it sat at 20px.
        ".hero{position:relative;isolation:isolate;min-height:480px;border-radius:32px;"
        "overflow:hidden;padding:32px;margin:0 0 32px;display:flex;flex-direction:column;"
        "justify-content:flex-end;background:#211217}"
        # -2 puts the footage under ::before's scrim (-1) but still inside .hero's own
        # stacking context, which is what `isolation` above is for.
        # Overscanned by PARALLAX_PX top and bottom, which is the room the 80%-speed drift
        # travels in. Deliberately small: the media is only 2×50px taller than the banner, so
        # a 480px hero shows 480 of 580 — about 8.6% cropped off each edge rather than the
        # ~36% a full-viewport parallax range would have cost.
        f".hero .hbg{{position:absolute;left:0;top:-{PARALLAX_PX}px;width:100%;"
        f"height:calc(100% + {PARALLAX_PX * 2}px);object-fit:cover;"
        "z-index:-2;pointer-events:none;will-change:transform}"
        # Cycled clips stack in the same place and cross-fade. Both sit at the same
        # z-index, so the incoming one paints over the outgoing purely by being later
        # in source order. The duration is HERO_FADE_MS, which the script also uses as
        # its lead-in.
        f".hero .hclip{{opacity:0;transition:opacity {HERO_FADE_MS}ms linear}}"
        ".hero .hclip.on{opacity:1}"
        # Reduced motion falls back to the poster frame the class background paints, which
        # does not move at all.
        "@media(prefers-reduced-motion:reduce){.hero .hbg{display:none}}"
        # One background rule per hero page, generated above from the same dict the asset copy
        # walks, so the poster a page paints is named once.
        f"{HERO_BG_CSS}"
        # Brand frames are far brighter than Welcome's footage where the type falls, so this
        # scrim is deeper and taller than the shared one, and only here. Measured on the
        # render with the type hidden, over the band the title and sub-hero occupy, worst
        # pixel: h-brand 6.10:1 on who-we-are.mp4 and 4.88:1 on who-we-are-2.mp4, h-serve
        # 5.10:1. Re-measure whenever the footage is replaced — these two carry the tightest
        # margins on the site and the scrim is the only thing holding them.
        ".hero.h-brand::before,.hero.h-serve::before{background:"
        "linear-gradient(to top,rgba(0,0,0,.8) 0,rgba(0,0,0,.3) 250px,"
        "rgba(0,0,0,0) 420px),rgba(0,0,0,.18)}"
        # TextXL — one banner text style, shared by every hero. It replaces the per-page
        # sizes the banners had drifted into (14px on Welcome, 24px on the brand pages), so
        # the three read as the same treatment. A step above the 15px body rather than a
        # display size: the raster title above it is already doing the shouting. Site chrome,
        # not an app token — nothing in the Swift sources answers to this name.
        ".textxl{font-size:18px;line-height:1.45;letter-spacing:-.02em;font-weight:400}"
        # The flat 20% is the brief. The gradient is on top of it because the copy sits over
        # sunlit grass, where white measured 1.22:1. Its fade is in px, not a percentage of
        # the hero: the content is bottom-anchored, so a percentage silently slides out from
        # under the title whenever min-height changes (at 560 it read 3.37:1, at 480 2.58:1).
        ".hero::before{content:'';position:absolute;inset:0;z-index:-1;background:"
        "linear-gradient(to top,rgba(0,0,0,.62) 0,rgba(0,0,0,0) 270px),rgba(0,0,0,.2)}"
        # Narrower than the 720px body measure: reversed out over a photograph, a long line
        # is harder to track back, and the wrap keeps the copy clear of the figure.
        ".hero .lede{color:#fff;opacity:.7;margin:0;max-width:560px;"
        "text-shadow:0 1px 12px rgba(0,0,0,.45)}"
        ".hero .phead{margin-bottom:10px}"
        # With the lede on top the gap moves with it, or the two blocks close up
        # and the title sits 10px clear of nothing.
        ".hero.lede-above .phead{margin-bottom:0}"
        ".hero.lede-above .lede{margin:0 0 10px}"
        # align-self, because .hero is a column flex container and the pill would otherwise
        # stretch the full width of the card.
        # Type, gap and padding scale together, or the pill only gets roomier rather than
        # bigger. margin-bottom:auto is what puts it at the top: .hero is bottom-anchored
        # (justify-content:flex-end), so the auto margin takes all the free space and the
        # bottom row keeps its place, which a top-anchored override would have disturbed.
        # The badge look itself — Sunlight fill, Bark label, one type size — shared by the hero
        # pill and the archetype numbers so the two cannot drift apart. Only the shape and the
        # placement differ, and those live in the two rules below. font-style:normal because
        # both are <em>, which the UA would otherwise italicise.
        f".hbadge,.abadge{{display:inline-flex;align-items:center;font-style:normal;"
        f"font-size:16px;font-weight:500;line-height:1;"
        f"background:#{_SUN['s200']};color:#{_BARK['s800']}}}"
        f".hero .hbadge{{align-self:flex-start;gap:7px;"
        f"padding:8px 15px;border-radius:999px;margin:0 0 auto}}"
        # Bottom row: the copy takes the space it needs and the action holds the right edge.
        # min-width:0 on the copy so a long lede wraps instead of pushing the action out.
        ".hero .hrow{display:flex;align-items:flex-end;justify-content:space-between;gap:28px}"
        ".hero .hcopy{min-width:0}"
        # Under 760 the two columns stop fitting side by side, so the action drops below the
        # copy and the row becomes the stack it used to be.
        "@media(max-width:760px){.hero .hrow{flex-direction:column;align-items:flex-start;"
        "gap:4px}}"
        # One flat white 16% fill and nothing else: no sheen gradient, no edge highlights, no
        # border, no drop shadow. The label is legible because the hero's own scrim is deepest
        # exactly where this sits, so the pill does not need to build its own contrast out of
        # layers. flex-shrink:0 so the label never wraps mid-word.
        ".hero .hbtn{flex:0 0 auto;"
        "display:inline-flex;align-items:center;gap:8px;"
        "margin:20px 0 0;padding:14px 23px 14px 20px;border-radius:999px;"
        "font-size:16px;font-weight:600;line-height:1;letter-spacing:-.01em;"
        "color:#fff;text-decoration:none;background:rgba(255,255,255,.16);"
        "transition:background .18s,transform .18s}"
        ".hero .hbtn:hover{background:rgba(255,255,255,.26)}"
        ".hero .hbtn:active{transform:translateY(1px) scale(.985)}"
        ".hero .hbtn svg{flex:0 0 auto;opacity:.92}"
        # At 80px the raster is 689px wide, so from ~1070px down it would run past the
        # hero's padding — it is an image and cannot rewrap. width:100% against the inline
        # max-width scales it down proportionally and stops it at its drawn size; the
        # !important is what beats the rasteriser's inline height pin.
        ".hero h1 .h1img{width:100%;height:auto!important;"
        "filter:drop-shadow(0 2px 14px rgba(0,0,0,.45))}"

        # ---- brand pages -------------------------------------------------------
        # Statements, not tables: one claim per row, label left, claim and its reasoning
        # right, so the eight foundations scan as a list of positions.
        ".bstat{display:grid;grid-template-columns:150px 1fr;gap:0 28px;"
        "padding:24px 0}"
        # Rule between rows rather than on every row and off the first: the head shares
        # the card with them, so any first-row selector is one layout change from wrong.
        ".bstat+.bstat{border-top:1px solid rgba(33,18,23,.08)}"
        ".bstat .eyebrow{margin:3px 0 0}"
        ".bstat b{display:block;font-size:24px;font-weight:500;letter-spacing:-.03em;"
        "line-height:1.24;color:#211217}"
        ".bstat p{margin:9px 0 0;font-size:14.5px;line-height:1.6;color:#755760;"
        "max-width:620px}"
        "@media(max-width:700px){.bstat{grid-template-columns:1fr;gap:8px}}"
        # Values: the pillar carries its own line, the three behaviours sit under it.
        ".vals{display:grid;grid-template-columns:1fr 1fr;gap:20px}"
        "@media(max-width:820px){.vals{grid-template-columns:1fr}}"
        f".val{{border-radius:20px;padding:24px;background:#{_SUN['s50']}}}"
        ".val h3{font-size:19px;margin:0}"
        ".val .vsub{font-style:italic;color:#755760;font-size:14px;margin:2px 0 16px}"
        ".val dl{margin:0}"
        ".val dt{font-size:13.5px;font-weight:500;color:#211217;margin-top:13px}"
        ".val dd{margin:2px 0 0;font-size:13.5px;line-height:1.55;color:#755760}"
        # The manifesto is the one place on the site that gets to be quiet: one column, no
        # chrome, no display type. Stanzas are separated by space rather than rules.
        f".mani{{position:relative;isolation:isolate;background:#{_SUN['s200']};"
        f"border-radius:32px;padding:56px 48px;margin:32px 0;color:#{_BARK['s950']}}}"
        # Green rises out of the bottom of the card as it passes: --fill is set by
        # PARALLAX_JS from the card's own progress through the viewport, so the wash
        # tracks the scroll rather than a fixed animation. Sunlight stays the base fill;
        # this only tints it. Absent JS or under reduced motion --fill never arrives and
        # the card is simply yellow.
        f".mani::after{{content:'';position:absolute;inset:0;z-index:-1;border-radius:32px;"
        f"pointer-events:none;background:linear-gradient(to top,#{_S['fillPositiveMuted']['lh']} 0%,"
        f"rgba(255,255,255,0) 62%);opacity:calc(var(--fill,0) * .85)}}"
        # Every stanza is set at the same size: the manifesto is one voice throughout, so it
        # carries no lead-versus-body hierarchy. Regular weight rather than a borrowed h3,
        # but it inherits body's -.03em: reading copy set large is still reading copy, and a
        # looser track here read as a different typeface to everything around it.
        ".textXL{font-size:26px;font-weight:300;line-height:1.55}"
        # Opacity-only reveal, both directions, with a floor rather than 0 so copy scrolled
        # past stays legible-ish instead of blanking. `reveal-on` is set by REVEAL_JS, so the
        # faded state only exists on a page whose script ran: no JS, no IntersectionObserver,
        # or reduced motion all leave the copy at full opacity.
        # Slow-start curve: the ramp lingers in the faint range, so the copy arrives rather
        # than switches on.
        ".reveal-on .reveal{opacity:.16;transition:opacity 1.6s cubic-bezier(.5,0,.35,1)}"
        ".reveal-on .reveal.in{opacity:1}"
        # pretty, not balance. The stanzas are verse with explicit breaks, and the longest
        # authored line needs 1316px to fit, so at any readable measure a few of them wrap and
        # leave a fragment alone underneath. Measured all three modes on the two lines that
        # wrap: balance returned line widths identical to plain wrap — Chrome does not balance
        # a block containing forced breaks — while pretty pulled words down and took those
        # orphans from 89px and 32px to 152px and 71px. Lines that already fit are untouched
        # either way, so the Brand Book's own breaks still lead.
        ".mani p{max-width:720px;margin:0 0 22px;text-wrap:pretty}"
        # Top right of the card, on the same inset the copy uses. The disc is Sunlight 200 —
        # the card's own fill — so what reads here is the sparkle, not a yellow circle on
        # yellow. Absolute against .mani, which is positioned for it above.
        ".mstar{position:absolute;top:50%;margin-top:-60px;right:40px;width:120px;"
        "height:120px;pointer-events:none;will-change:transform}"
        "@media(max-width:700px){.mstar{width:84px;height:84px;margin-top:-42px;right:24px}}"
        "@media(max-width:700px){.mani{padding:36px 24px}.mani p{font-size:24px}}"
        # Pull quotes on the charter: the register examples are the argument, so they get
        # the emphasis rather than another paragraph of prose.
        ".regs{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0 0}"
        "@media(max-width:700px){.regs{grid-template-columns:1fr}}"
        f".reg{{border-radius:16px;padding:18px;background:#{_SUN['s50']}}}"
        ".reg b{display:block;font-size:15px;margin-bottom:3px}"
        ".reg span{font-size:13.5px;color:#755760;line-height:1.5}"
        ".pull{margin:22px 0;padding-left:20px;border-left:2px solid #4C2934;"
        "font-size:19px;line-height:1.5;letter-spacing:-.02em;color:#211217;max-width:640px}"
        # ---- archetypes --------------------------------------------------------
        # The portrait carries the archetype as much as the words do, so it leads the block
        # at full width rather than sitting in a column. These are wide scene photographs of
        # a whole room — the subject is often well off-centre (the admin sits at the right
        # edge of her frame), and any column narrow enough to sit beside the text cropped
        # her out. 16/9 is the source ratio, so the band shows the frame as shot.
        # ---- screens mosaic ----------------------------------------------------
        # auto-fill rather than a fixed column count: the tile width is the constant here,
        # so the same grid gives four across on a desktop and two on a phone without a
        # breakpoint. Every other tile drops half a step — that offset is what makes a
        # grid of identical phone rectangles read as a mosaic rather than a spreadsheet.
        ".smos{display:grid;grid-template-columns:repeat(auto-fill,minmax(206px,1fr));"
        "gap:30px 22px;margin:26px 0 0;align-items:start}"
        ".smos .stile:nth-child(even){margin-top:30px}"
        "@media(max-width:560px){.smos .stile:nth-child(even){margin-top:0}}"
        ".stile{margin:0;min-width:0}"
        # 9/19.5 is the iPhone ratio, so a full-height capture sits in the frame uncropped.
        f".sframe{{position:relative;aspect-ratio:9/19.5;border-radius:26px;overflow:hidden;"
        f"background:#{_BARK['s25']};border:1px solid rgba(33,18,23,.10);"
        "box-shadow:0 12px 26px -14px rgba(33,18,23,.30)}"
        ".sframe .sh{display:block;width:100%;height:100%;object-fit:cover}"
        ".sframe .dark{display:none}"
        ".dktog:checked~.smos .sframe .light{display:none}"
        ".dktog:checked~.smos .sframe .dark{display:block}"
        # The slot says which capture it wants, so an added screenshot needs no other edit.
        ".sh.todo{display:flex;align-items:center;justify-content:center;text-align:center;"
        "padding:14px;background:transparent}"
        f".sh.todo code{{line-height:1.6;color:#{_BARK['s400']}}}"
        ".stile figcaption{padding:11px 2px 0}"
        ".stile figcaption b{display:block;font-size:13.5px;font-weight:500;color:#211217;"
        "letter-spacing:-.01em}"
        f".stile figcaption code{{display:block;margin-top:2px;"
        f"color:#{_BARK['s400']}}}"
        # A two-up segmented control, checkbox-driven so the page needs no script — the
        # same trick the nav burger uses.
        ".dkbtn{display:inline-flex;padding:2px;border-radius:999px;background:#F4E7DD;"
        "cursor:pointer;user-select:none;font-size:12px;font-weight:500;color:#755760}"
        ".dkbtn span{padding:5px 15px;border-radius:999px}"
        ".dkbtn span:first-child{background:#4C2934;color:#fff}"
        ".dktog:checked~.dkbtn span:first-child{background:transparent;color:#755760}"
        ".dktog:checked~.dkbtn span:last-child{background:#4C2934;color:#fff}"
        ".arch{display:block}"
        # A persona is an <h3> plus a sibling .arch, not one element, so the rule that
        # separates them hangs off the name. The first name in each group takes none: the
        # section head above it already draws that line, and two a heading apart read as a
        # mistake.
        # The rule that separates two personas hangs off the photograph now that the name is
        # inside it. The first in each group takes none: the section head above it already
        # draws that line, and two a heading apart read as a mistake.
        ".arch{margin-top:38px;padding-top:30px;border-top:1px solid rgba(33,18,23,.08)}"
        ".shead+.arch{margin-top:0;padding-top:0;border-top:0}"
        # Kept for the no-photograph fallback, where the name is still a sibling above.
        ".aname{margin:0}"
        f".arch-img{{position:relative;aspect-ratio:16/9;border-radius:28px;overflow:hidden;"
        f"margin-bottom:20px;background:#{_SUN['s100']}}}"
        ".arch-img img{display:block;width:100%;height:100%;object-fit:cover}"
        # A photograph cannot be relied on to be dark where the name lands, so the name gets
        # its own scrim rather than a text-shadow: measured 1.15:1 on the brightest frame
        # without it. Tall and soft so it reads as light falling off, not as a bar.
        ".arch-img::after{content:'';position:absolute;inset:auto 0 0 0;height:82%;"
        "pointer-events:none;background:linear-gradient(to top,rgba(0,0,0,.78) 0,"
        "rgba(0,0,0,.35) 42%,rgba(0,0,0,0) 100%)}"
        ".arch-cap{position:absolute;left:26px;right:26px;bottom:20px;z-index:1}"
        ".arch-cap .aname{margin:0}"
        "@media(max-width:560px){.arch-cap{left:18px;right:18px;bottom:14px}}"
        # Mirrors .arch-cap's insets in the opposite corner, at both breakpoints, so the number
        # and the name sit on the same margins. A fixed square with a 50% radius rather than the
        # hero pill's padding + 999px: padding sized to a one- or two-digit label would give an
        # oval, and these have to stay circular whatever the count reaches. z-index for the same
        # reason the caption has it — above .arch-img::after.
        ".arch-img .abadge{position:absolute;left:26px;top:20px;z-index:1;"
        "width:48px;height:48px;border-radius:50%;justify-content:center;padding:0}"
        "@media(max-width:560px){.arch-img .abadge{left:18px;top:14px}}"
        # The slot is sized and shaped now so a dropped-in photo needs no layout work; until
        # then it says which filename it is waiting for rather than sitting empty.
        ".arch-img.todo{display:flex;align-items:center;justify-content:center;text-align:center;"
        "border:1px dashed rgba(33,18,23,.22);background:transparent;padding:16px}"
        ".arch-img.todo code{color:#A98993;line-height:1.5}"
        # The card's eyebrow and the facts labels beneath it are the same label — one size,
        # weight, tracking and grey — so they share a rule rather than two that drifted apart
        # (the eyebrow had been 12.5px against the labels' 11px, and read as a size of its
        # own). Only the margins differ, below.
        # The role tag stays an uppercase eyebrow: it sits on the photograph as a label
        # for the name under it. The fact labels inside the card are headings for the
        # lists below them, so they read as body copy at full strength instead.
        ".arch .role{font-size:11px;font-weight:500;color:#A98993;"
        "text-transform:uppercase;letter-spacing:.06em;margin:0 0 6px}"
        f".afacts h4{{font-size:15px;font-weight:500;color:#{_S['foregroundPrimary']['lh']}}}"
        # Base body type, with no font-size, weight or letter-spacing of its own: whatever body
        # sets, this takes. Plain block flow — the flex row and its gap only existed to seat
        # the quote mark that used to lead this line.
        # Nothing in the styling says "quotation" any more: no mark, no quotation marks in the
        # string, and the face is upright. It reads as speech from sitting under the archetype's
        # name, so keep it there.
        ".arch blockquote{margin:8px 0 0;color:#211217}"
        # On the photograph the caption reverses out, so role and quote take the same
        # white the name does rather than the page's greys.
        ".arch-cap .role{color:rgba(255,255,255,.72)}"
        # The quote is secondary to the name it sits under, so it takes foregroundSecondary
        # rather than a hand-picked white — on dark that token is white at 75%.
        f".arch-cap blockquote{{color:{rgba(_S['foregroundSecondary']['dh'], _S['foregroundSecondary']['da'])};max-width:46em}}"
        ".arch-nocap{margin-bottom:16px}"
        ".afacts{display:grid;grid-template-columns:1fr 1fr;gap:22px 28px;margin:0}"
        "@media(max-width:560px){.afacts{grid-template-columns:1fr}}"
        ".afacts h4{margin:0 0 4px}"
        ".afacts ul{margin:0;padding-left:16px}"
        ".afacts li{font-size:14px;line-height:1.55;color:#755760;margin-bottom:5px}"
        ".afacts p{margin:0;font-size:14px;line-height:1.55;color:#755760}"
        # Source links inside a provenance note, so the reader can go check the original.
        # ?edit only. Dashed while idle so the editable surface is obvious without shouting;
        # the locked children get their own tint so it is clear why they will not take a
        # caret. Sky rather than Accent: this is a tool, not part of the design system.
        f".editing [contenteditable=true]{{outline:1px dashed #{_SKY['s400']};"
        "outline-offset:4px;border-radius:3px}"
        f".editing [contenteditable=true]:focus{{outline:2px solid #{_SKY['s600']};"
        f"background:#{_SKY['s50']}}}"
        f".editing [contenteditable=false]{{background:#{_SKY['s100']};border-radius:3px;"
        "cursor:not-allowed}"
        ".ebar{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:20;"
        "display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:99px;"
        "background:#211217;color:#fff;font-size:12.5px;"
        "box-shadow:0 6px 24px rgba(33,18,23,.28)}"
        ".ebar b{font-weight:500}"
        ".ebar button{font:inherit;color:#211217;background:#fff;border:0;cursor:pointer;"
        "padding:5px 11px;border-radius:99px}"
        ".ebar button:hover{background:#F0DFD1}"
        ".fig{display:block;width:100%;height:auto;border-radius:16px}"
        ".figwrap{margin:0}"
        # Texture grid. The whole tile is the anchor, so both hover layers are
        # pointer-events:none — a click anywhere on the card still downloads.
        ".texgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));"
        "gap:14px}"
        ".texcell{position:relative;display:block;text-decoration:none;border-radius:14px;"
        "overflow:hidden;background:#F6ECE4}"
        # Bark 950 at 5% over the tile on hover.
        f'.texcell::before{{content:"";position:absolute;inset:0;z-index:1;'
        f"pointer-events:none;background:{rgba(_BARK['s950'], .05)};opacity:0;"
        "transition:opacity .14s ease}"
        ".texcell:hover::before{opacity:1}"
        ".texcell img{display:block;width:100%;aspect-ratio:3/2;object-fit:cover}"
        # People are 1:1, 3:2 and 2:1 in the source. A common 4/5 crop is what makes ten of
        # them read as one set rather than a ragged pile, and portrait is the shape a person
        # actually fits. The clips crop to the same box so a tile does not change size when
        # its poster gives way to the video.
        ".pcell img,.pcell video{display:block;width:100%;aspect-ratio:4/5;object-fit:cover}"
        ".pcell video{background:#F6ECE4}"
        # No download affordance on a clip, so its hover tint would promise a click that
        # does nothing.
        ".pcell:not(a)::before{display:none}"
        ".pgrid{grid-template-columns:repeat(auto-fill,minmax(184px,1fr))}"
        ".pcell .texdl{aspect-ratio:4/5}"
        # The tile is the image now, so the button box is simply the tile.
        ".texdl{position:absolute;inset:0;z-index:2;"
        "display:flex;align-items:center;justify-content:center;pointer-events:none;"
        "opacity:0;transition:opacity .14s ease}"
        ".texcell:hover .texdl{opacity:1}"
        f'.texdl i{{display:flex;align-items:center;justify-content:center;width:48px;'
        f"height:48px;border-radius:999px;background:#fff;color:#{_BARK['s950']}}}"
        # The glyph ships at 20px; 18 keeps the same optical inset inside a 48px button.
        '.texdl svg{width:18px;height:18px}'
        "@media(prefers-reduced-motion:reduce){.texcell::before,.texdl{transition:none}}"
        ".figsrc{display:flex;gap:8px;align-items:baseline;margin-top:10px;font-size:11.5px;"
        "color:#A98993}"
        ".figsrc a{color:#755760}")

# The principles we work to, each paired with the thing in this repo that actually enforces
# it. A principle with no enforcement is a poster; the third field is what makes it
# checkable. Every path referenced below exists in the repo.
# The principles, as a plain list — title and body, nothing else.
PRINCIPLES = [
    ("Quality over quantity",
     "Every feature has a cost. Earn trust through depth, polish, and reliability &mdash; not "
     "feature count."),
    ("We build together",
     "No handoff culture. Designers, engineers, and agents share ownership from idea to "
     "implementation. We are all builders."),
    ("Fix as you go",
     "Plant deliberately. Prune relentlessly. Every change should make the system simpler, "
     "stronger, or more useful."),
    ("Design systems, not screens",
     "Systems scale. Screens don&rsquo;t. Design components, states, and flows that can be "
     "reused across the product."),
    ("Code is the source of truth",
     "The product is the truth. Figma communicates intent, but the design system lives in "
     "production code."),
    ("Consistency creates trust",
     "Every inconsistency compounds. Shared patterns and behaviors create products that feel "
     "reliable and trustworthy."),
    ("Familiar by design",
     "Start with the platform. Custom UI should solve a real problem, not satisfy a "
     "preference."),
    ("No custom values",
     "Every exception creates system debt. Use semantic tokens and shared foundations instead "
     "of one-off values."),
    ("Everything is a component",
     "New patterns are a last resort. Reuse, refactor, or reject before creating something "
     "new."),
]


# ---------------------------------------------------------------- parse type
# ComponentsKit sizes, as asserted by the HHFont doc comment on each token.
UNIVERSAL = {"lgHeadline": (20, "Inter", "Semibold"), "lgButton": (16, "Inter", "Medium"),
             "lgBody": (16, "Inter", "Regular"), "mdButton": (14, "Inter", "Medium"),
             "mdBody": (14, "Inter", "Regular"), "smButton": (12, "Inter", "Medium"),
             "smBody": (12, "Inter", "Regular"), "smCaption": (10, "Inter", "Regular")}
PS_WEIGHT = {"Inter-Regular_SemiBold": "Semibold", "Inter-Regular_Medium": "Medium",
             "Inter-Regular": "Regular"}
font_src = read_swift(THEME / "HHFont.swift")
EXPOSURE = dict(re.findall(r"static let (\w+)Size: CGFloat = (\d+)", font_src))

fonts, fsection = [], ""
fbody = font_src[font_src.index("enum HHFont {"):]
# Only `static var <name>: Font` tokens — the UIFont counterparts are the same
# tokens for UIKit call sites, not separate design-system entries.
for blk in re.finditer(
        r"((?:[ \t]*///[^\n]*\n)*)[ \t]*static var (\w+): Font \{\n(.*?)\n    \}", fbody, re.S):
    doc, name, body_ = blk.group(1), blk.group(2), blk.group(3)
    ms = list(re.finditer(r"// MARK: (?:- )?(\w[\w ]*)", fbody[:blk.start()]))
    fsection = ms[-1].group(1).strip() if ms else ""
    if fsection in ("Private Helper", "Custom Sizes") or is_debug(name):
        continue
    desc = " ".join(l.strip().lstrip("/").strip() for l in doc.strip().splitlines())
    anchor = (re.search(r"relativeTo: \.(\w+)", body_) or [None, ""])[1]
    size = fam = weight = None
    ps = ""
    cu = re.search(r'\.custom\(name: (?:"([^"]+)"|HHExposureFont\.(\w+)), '
                   r'size: (?:(\d+)|HHExposureFont\.(\w+))\)', body_)
    uf = re.search(r"UniversalFont\.(\w+)", body_)
    alias = re.match(r"\s*(\w+)\s*$", body_)
    if cu:
        ps = cu.group(1) or ("Exposure-10-Regular" if "regular" in (cu.group(2) or "") else "Exposure-10-Italic")
        fam = "Exposure" if "Exposure" in ps else "Inter"
        weight = PS_WEIGHT.get(ps, "Regular")
        size = int(cu.group(3)) if cu.group(3) else int(EXPOSURE[cu.group(4).replace("Size", "")])
    elif uf and uf.group(1) in UNIVERSAL:
        size, fam, weight = UNIVERSAL[uf.group(1)]
        ps = "Inter-Regular"
    elif alias:
        prev = next((f for f in fonts if f["name"] == alias.group(1)), None)
        if prev:
            size, fam, weight, ps = prev["size"], prev["fam"], prev["weight"], prev["ps"]
    if size is None:
        continue
    fonts.append(dict(name=name, section=fsection, desc=desc, size=size, ps=ps,
                      fam=fam, weight=weight, anchor=anchor,
                      src=(cu.group(0) if cu else uf.group(0) if uf
                           else f"HHFont.{alias.group(1)}")))

# ------------------------------------------------------- parse spacing/radius
def scale_of(path, enum):
    src = read_swift(THEME / path)
    blk = re.search(r"enum " + enum + r" \{(.*?)\n\}", src, re.S).group(1)
    out = []
    # Anchored to line start with only whitespace before `static let`, so commented-out
    # declarations (`//    static let iconContainerSmall...`) are not documented as real
    # tokens. The note must be a trailing comment on the SAME line — `\s*` here would
    # reach across blank lines and attach the next section's `// MARK` to this token.
    for m in re.finditer(r"^[ \t]*static let (\w+): CGFloat = ([\d.]+)[ \t]*"
                         r"(?://[ \t]*([^\n]*))?$", blk, re.M):
        note = (m.group(3) or "").strip()
        # The comment usually just restates the value ("8px", "4px - Extra small");
        # keep only real prose. A trailing % means the number is the prose ("40% opacity").
        note = re.sub(r"^\d+(?:px)?(?![%\w])\s*[-–]?\s*", "", note).strip()
        if not is_debug(m.group(1)):
            out.append((m.group(1), float(m.group(2)), note))
    return out


SPACING = scale_of("HHSpacing.swift", "HHSpacing")
_sizing_all = scale_of("HHSpacing.swift", "HHSizing")
# HHSizing mixes point sizes with the three state opacities. They are semantic colour
# state, not geometry, so they are documented with the colour roles instead.
SIZING = [t for t in _sizing_all if not t[0].startswith("opacity")]
OPACITY = [t for t in _sizing_all if t[0].startswith("opacity")]
RADIUS = scale_of("HHRadius.swift", "HHRadius")

# ------------------------------------------------- the Foundations token table
# Every foundation — colour, type, spacing, radius, icons — documents its tokens
# through these four helpers, so a row reads the same on every page. Only the
# swatch inside pv() changes per token kind.
def ttable(cols, rows):
    # A row short of a cell still renders — the remaining values just slide left under the
    # wrong headers, which reads as a data error rather than a markup one and survives the
    # link/stylesheet sweep untouched. Cheaper to refuse to build it.
    for r in rows:
        cells = re.findall(r"<td[^>]*>", "".join(r))
        n = sum(int(m.group(1)) if (m := re.search(r'colspan="(\d+)"', c)) else 1
                for c in cells)
        assert n == len(cols), (f"table row spans {n} columns, header has {len(cols)} "
                                f"({[c[:40] for c in r]})")
    head = "".join(f'<th style="width:{w}">{l}</th>' for l, w in cols)
    body = "".join(f"<tr>{''.join(r)}</tr>" for r in rows)
    return f'<table class="tt"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def tk(name, sub=""):
    """Token cell — the symbol a view actually types, chipped because it is code."""
    return (f'<td class="tk"><span class="tok" title="Copy">{html.escape(name)}</span>'
            + (f'<span class="tksub">{sub}</span>' if sub else "") + "</td>")


def us(text):
    """Prose cell — what the token is for. Doc-comment backticks become code."""
    inline = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return f'<td class="us">{inline}</td>'


def pv(swatch, primary, meta="", td=True):
    """Swatch + value cell. `swatch` is the per-foundation preview element."""
    inner = (f'<span class="c">{swatch}<span class="cmeta">'
             f'<b class="prim">{primary}</b>'
             + (f'<span class="hx">{meta}</span>' if meta else "")
             + "</span></span>")
    return f"<td>{inner}</td>" if td else inner


# ---------------------------------------------------------------- page 1
ORDER = ["HHSand","HHBark","HHSky","HHForest","HHSunlight","HHNeutral","HHGreen","HHRed","HHOrange","HHBlue","HHPro"]
GROUPS = [("Brand hues", ["HHSand","HHBark","HHSky","HHForest","HHSunlight"]),
          ("Status ramps · Tailwind", ["HHNeutral","HHGreen","HHRed","HHOrange","HHBlue"]),
          ("Tier", ["HHPro"])]
# Primitives are fixed hex, so the swatch is the documentation — a table would only
# restate the ramp strip in words.
p1 = ""
for r in ORDER:
    stops = ramps.get(r, [])
    if not stops: continue
    p1 += f'<h3>{r[2:]}<span class="ct">{len(stops)}</span></h3><div class="scale">'
    for s,h in stops:
        lum = int(h[0:2],16)*.299 + int(h[2:4],16)*.587 + int(h[4:6],16)*.114
        p1 += f'<div class="sw" style="background:#{h};color:{"#111" if lum>140 else "#fff"}"><b>{s[1:]}</b><code>{h}</code></div>'
    p1 += '</div>'
# The ramps are one exhibit, not eleven: a card each would be mostly padding around a thin
# strip. They drop to h3 so sectionise() leaves them alone and they share this one card.
# The note closes the card rather than sitting under it: it is a footnote to these ramps,
# and an alert's fill is fillSecondary, which is the page background — outside the card
# there would be nothing to see.
p1 = (f'<div class="scard nodiv">{wrap_heads(p1)}'
      '<div class="note"><b>Primitives are fixed hex in both themes.</b> Theme adaptation '
      'happens in the semantic layer, never here. Views must not reference a ramp '
      'directly; compose a semantic token instead.</div></div>')

# ---------------------------------------------------------------- page 2
USE = {'surfacePrimary':'default page fill','surfaceSecondary':'sheet pages','surfaceTertiary':'row-list sections, cards',
 'fillAccent':'primary buttons, toggle on-tint','fillPrimary':'chips, inputs, wells','fillSecondary':'chat bubbles, soft chips',
 'foregroundPrimary':'body and titles','foregroundSecondary':'supporting text','foregroundTertiary':'hints, metadata',
 'foregroundAccent':'links, interactive text','foregroundPrimaryInvert':'text on fillAccent','foregroundWhite':'always-white chrome',
 'foregroundBrand':'the Heidi mark','border':'every stroke and separator',
 'dialogScrim':'dims the page behind HHConfirmationDialogView',
 'scrim':'dims the page behind dialogs — one value, one call site'}
CATS = [("Foreground","Foreground","Text and icons."),
        ("Fill","Fill","Element fills: buttons, chips, badges, toggles, pills."),
        ("Surface","Surface","Containers: pages, sheets, sections, cards, and the scrim behind dialogs."),
        ("Border","Border","Outlines, separators, strokes, hairlines."),
]
def cell(hx,a,nm):
    al = '' if a==1.0 else f'<i class="al">{int(round(a*100))}%</i>'
    return pv(f'<i class="chip" style="background:{rgba(hx,a)}"></i>',
              html.escape(nm), f'<code>{hx}</code>{al}', td=False)
# HHColors.swift keeps the inverts and brand hues next to Primary, but someone looking up a
# text colour wants the neutral three-step together and first. Names here lead their section
# in this order; everything else keeps source order behind them, so the file stays the
# ordering authority for every token not named.
SEM_LEAD = {"Foreground": ["foregroundPrimary", "foregroundSecondary", "foregroundTertiary"]}
_sem_names = {s["name"] for s in sems}
assert all(n in _sem_names for ns in SEM_LEAD.values() for n in ns), (
    "SEM_LEAD names a token that HHColors.swift no longer has: "
    f"{[n for ns in SEM_LEAD.values() for n in ns if n not in _sem_names]}")

sections = ""
for key,label,desc in CATS:
    rows = [s for s in sems if s['section']==key]
    if not rows: continue
    # Stable sort, so the unnamed tokens keep the order the Swift file gave them.
    _lead = SEM_LEAD.get(key, [])
    rows.sort(key=lambda s: _lead.index(s["name"]) if s["name"] in _lead else len(_lead))
    sections += f'<h2 id="{label.lower()}">{label}<span class="ct">{len(rows)}</span></h2><p class="lede sub">{desc}</p>'
    sections += ttable(
        [("Token", "21%"), ("Use for", "25%"), ("Light", "27%"), ("Dark", "27%")],
        [[tk(s["name"]), us(USE.get(s["name"], "")),
          f'<td>{cell(s["lh"], s["la"], s["ln"])}</td>',
          f'<td>{cell(s["dh"], s["da"], s["dn"])}</td>'] for s in rows])
# One component per frame, tokens called out with dotted leaders, simplest anatomy first.
# Same pixel size in every frame, which is what lets the track slide by whole percentages.
ANATOMY_SLIDES = [
    ("search", "Search field",
     "Search field: surface behind the bar, fill for the input itself, foreground for the "
     "icon and placeholder"),
    ("header", "Screen header",
     "Patient header: foreground.primary for the title, the back chevron and the trailing "
     "glyphs; foreground.secondary for the subtitle"),
    ("toast", "Toast",
     "Sessions-merged toast: a surface.primary card inside a border hairline, fill.primary "
     "behind Undo, foreground.primary for the label and both glyphs"),
    ("row", "Session row",
     "Session row: border and fill.forest on the avatar with a foreground.forest initial, "
     "foreground.primary name over foreground.secondary meta, and a foreground.negative "
     "alert on surface.tertiary"),
]

# The Lucide chevrons are inlined rather than fetched: this runs before lucide_svg() is
# defined, and each glyph is one path. Same stroke treatment as the icon grid.
CHEV = ('<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="{}"/></svg>')

# Radio-driven rather than scripted: the tabs above already own the URL hash, and an anchor
# per slide would scroll the page instead of moving the track. The arrows are one pair per
# slide — a label can only point at a fixed radio, so "previous" has to be a different
# element on each slide, and only the checked slide's pair is shown. They wrap around, so
# neither arrow is ever a dead control.
ANATOMY = (
    '<div class="anat">'
    + "".join(f'<input type="radio" name="anat" id="anat-{slug}" class="anatr"'
              f'{" checked" if i == 0 else ""}>'
              for i, (slug, _, _) in enumerate(ANATOMY_SLIDES))
    + '<div class="anat-view"><div class="anat-track">'
    + "".join(f'<div class="anat-slide"><img src="anatomy-{slug}.png" alt="{alt}"></div>'
              for slug, _, alt in ANATOMY_SLIDES)
    + '</div>'
    + "".join(
        f'<div class="anat-nav n-{slug}">'
        f'<label for="anat-{ANATOMY_SLIDES[i - 1][0]}" title="Previous diagram">'
        f'<span>Previous diagram</span>{CHEV.format("m15 18-6-6 6-6")}</label>'
        f'<label for="anat-{ANATOMY_SLIDES[(i + 1) % len(ANATOMY_SLIDES)][0]}" '
        f'title="Next diagram">'
        f'<span>Next diagram</span>{CHEV.format("m9 18 6-6-6-6")}</label></div>'
        for i, (slug, _, _) in enumerate(ANATOMY_SLIDES))
    + '</div></div>')

# The slide count is data, so the rules that move the track are generated with it.
ANATOMY_CSS = "".join(
    f'#anat-{slug}:checked~.anat-view .anat-track{{transform:translateX({-i * 100}%)}}'
    f'#anat-{slug}:checked~.anat-view .anat-nav.n-{slug}{{display:flex}}'
    for i, (slug, _, _) in enumerate(ANATOMY_SLIDES))

# Opacity closes the semantics page: the state tokens that modulate a colour rather than
# name one. scale_table is defined below, so this section is appended after it.
p2 = f'{ANATOMY}{sections}'


# ------------------------------------------------------------ page: icons
# The icons the app actually uses: the CustomIcons registry (the sanctioned way to name
# one) plus every raw name that skipped it. The catalogue holds the whole Lucide set, so
# listing the catalogue would document 1500 icons we don't use.
# Lucide glyphs live in Lucide-Icons.xcassets, but a few (e.g. external-link) sit in the
# main catalogue instead. Both resolve by name at runtime, so both must be searched or the
# page reports a working icon as missing.
ICON_CAT = ROOT / "HeidiNative/Lucide-Icons.xcassets"
ICON_CATS = [ICON_CAT, ROOT / "HeidiNative/Assets.xcassets"]
VENDORED = {p.name[:-len(".imageset")] for c in ICON_CATS for p in c.rglob("*.imageset")}
icons_src = read_swift(ROOT / "HeidiNative/Managers/SymbolHelper/CustomIcons.swift")

registered = {}
for m in re.finditer(r'((?:[ \t]*///[^\n]*\n)*)[ \t]*static let (\w+) = "([^"]+)"', icons_src):
    doc = " ".join(l.strip().lstrip("/").strip() for l in m.group(1).strip().splitlines())
    # The comment opens by naming the glyph ("Book open icon - used for…"); keep the use.
    doc = re.sub(r"^[\w' ]+ icon\s*[-–]\s*", "", doc)
    doc = re.sub(r"^[\w' ]+ \([^)]*\)\s*[-–]\s*", "", doc).strip()
    if not (is_debug(m.group(2)) or is_debug(m.group(3))):
        registered[m.group(3)] = (m.group(2), doc[:1].upper() + doc[1:] if doc else "")

# Finding the raw names is not a grep for `Image.lucide("literal")`: most of them never
# appear as an argument to it. `Image.lucide` is only `Image(name).renderingMode(.template)`,
# so a bare `Image("calendar-clock")` draws the same glyph, and the name usually arrives
# through an indirection — a computed `iconName` (the Evidence badges), an `icon:` argument
# (ChatHistoryView), or a generated `ImageResource` symbol like `.penTool`, which is a
# camelCased asset name with no string to grep at all. Each is resolved below.
#
# The hazard is the reverse direction. Lucide has ~1589 glyphs, so its names collide with
# ordinary words — `type`, `user`, `file`, `server`, `code` — and with SF Symbols, which
# `Image(systemName:)` draws from an entirely different set. A name-only match puts JSON
# keys and SF Symbols on the page as Lucide icons. So a name counts only once it is tied to
# an asset render, by three tests that each exclude a distinct class of impostor.
ICONISH = r"(?![Ss]ystem)(\w*(?:[Ii]con|[Aa]sset|[Gg]lyph)\w*)"
ASSET_LIT = [re.compile(p + r'"([a-z0-9][a-z0-9-]*)"') for p in (
    r"\bImage\.lucide\(\s*", r"\bImage\(\s*", r"ImageName\.custom\(\s*", r"\bUIImage\(named:\s*",
    # `Label(title, image:)` draws an asset; its SF Symbol sibling is the distinct
    # `systemImage:`, which the lowercase `i` here already excludes.
    r"\bimage:\s*")]
# `Image(.messageSquareText)` — an ImageResource literal, so unambiguously an asset: SF
# Symbols can only arrive through the separate `Image(systemName:)` initialiser.
ASSET_SYMBOL = [re.compile(p + r"\.([a-z][A-Za-z0-9]*)\s*[,)]") for p in (
    r"\bImage\(\s*", r"\bimage:\s*")]
ASSET_ID = [re.compile(p) for p in (
    r"\bImage\.lucide\(\s*[\w.]*?(\w+)\s*[,)]", r"\bImage\(\s*(\w+)\s*[,)]",
    r"ImageName\.custom\(\s*(\w+)")]
SYS_ARG = [re.compile(p) for p in (
    r"\bImage\(systemName:\s*([^)]*)", r"systemImage:\s*([^,)]*)", r"\.sf\(\s*([^,)]*)")]
ICON_LABEL = re.compile(r"\b" + ICONISH + r'\s*:\s*"([a-z0-9][a-z0-9-]*)"')
ICON_DECL = re.compile(r"\b(?:var|let|func)\s+" + ICONISH + r"\b")
# `icon: .penTool` — an ImageResource symbol, i.e. the asset name camelCased by the compiler.
ICON_SYMBOL = re.compile(r"\b" + ICONISH.replace("[Gg]lyph", "[Gg]lyph|[Ii]mage")
                         + r"\s*:\s*\.([a-z][A-Za-z0-9]*)\b(?!\s*\()")
# SF Symbol names are dot-separated and Lucide names are kebab-case, so one declaration is
# never both. A `checkmark.circle.fill` in the body proves the whole switch is SF Symbols,
# which is what tells `WiFiSocketState.icon`'s "circle" and "hourglass" from real glyphs.
SF_SHAPE = re.compile(r'"[a-z0-9]+(?:\.[a-z0-9]+)+"')


def kebab_asset(symbol):
    """`messageSquareText` -> `message-square-text`, undoing the ImageResource camelCasing."""
    return re.sub(r"(?<!^)(?=[A-Z])", "-", symbol).lower()


def decl_body(txt, i):
    """The declaration at `i`: its brace-balanced body, or its line for a plain `= value`."""
    nl, brace = txt.find("\n", i), txt.find("{", i)
    if brace == -1 or (nl != -1 and brace > nl):
        return txt[i:nl if nl != -1 else len(txt)]
    depth = 0
    for j in range(brace, len(txt)):
        depth += (txt[j] == "{") - (txt[j] == "}")
        if depth == 0:
            return txt[i:j]
    return txt[i:brace]


swift = {sw: read_swift(sw) for sw in swift_sources(ROOT / "HeidiNative")}
# Which identifiers reach an asset render, gathered across the corpus: the Evidence badges
# compute an `iconName` that only `EvidenceSourceBadge`, in a third file, ever draws.
asset_ids = {m.group(1) for txt in swift.values() for rx in ASSET_ID for m in rx.finditer(txt)}

used = set()
for sw, txt in swift.items():
    # …but "drawn as an SF Symbol" is judged per file, where the identifier is in scope.
    # `icon` renders an asset in ChronicleNotFoundSheet and an SF Symbol in
    # WorkChatAgentStepsView; only the file it appears in says which.
    sys_ids = {i for rx in SYS_ARG for m in rx.finditer(txt) for i in re.findall(r"\w+", m.group(1))}

    def resolves_to_asset(ident):
        return ident in asset_ids and ident not in sys_ids

    for rx in ASSET_LIT:
        used |= {m.group(1) for m in rx.finditer(txt)}
    for rx in ASSET_SYMBOL:
        used |= {kebab_asset(m.group(1)) for m in rx.finditer(txt)}
    used |= {kebab_asset(m.group(2))
             for m in ICON_SYMBOL.finditer(txt) if resolves_to_asset(m.group(1))}
    used |= {m.group(2) for m in ICON_LABEL.finditer(txt) if resolves_to_asset(m.group(1))}
    for m in ICON_DECL.finditer(txt):
        if not resolves_to_asset(m.group(1)):
            continue
        body = decl_body(txt, m.start())
        if SF_SHAPE.search(body):
            continue
        used |= set(re.findall(r'"([a-z0-9][a-z0-9-]*)"', body))

LUCIDE_VERSION = "1.28.0"
LUCIDE_CACHE = ROOT / ".context/lucide-cache"


def lucide_svg(name):
    """Fetch the icon's real Lucide SVG, cached on disk so a rebuild works offline.

    The shipped assets are PDFs; rasterising them gave soft, unrecolourable glyphs. The
    upstream SVG is sharp at any size and strokes with currentColor, so the grid can tint
    it with a token. Lucide is ISC-licensed, so unlike Exposure it can be shipped."""
    LUCIDE_CACHE.mkdir(parents=True, exist_ok=True)
    cached = LUCIDE_CACHE / f"{name}.svg"
    if not cached.exists():
        import urllib.error, urllib.request
        url = f"https://unpkg.com/lucide-static@{LUCIDE_VERSION}/icons/{name}.svg"
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                cached.write_bytes(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            cached.write_text("")   # cache the miss; the name is not a Lucide glyph
    body = cached.read_text()
    if not body.strip():
        return None
    # Size and colour come from CSS, so drop the upstream width/height and comment.
    body = re.sub(r"<!--.*?-->\s*", "", body, flags=re.S)
    body = re.sub(r'\s(?:width|height)="\d+"', "", body, count=2)
    return body.strip()

# The copy toast's tick. A real glyph rather than U+2714 with a variation selector, which
# rendered as a grey emoji tick that no colour could override.
COPY_ICON = lucide_svg("check").replace("<svg", '<svg aria-hidden="true"', 1)



# An asset render proves the name is an image, not that it is a Lucide one: the app also
# ships bespoke art (evidencelogo, chronicle-connected) and near-misses (check-circle, where
# Lucide's glyph is circle-check). Requiring an upstream glyph drops those. The same test is
# deliberately *not* applied to CustomIcons, where a name with no glyph is drift worth saying.
loose = sorted(n for n in used - set(registered) if n in VENDORED and lucide_svg(n))

# One canary per discovery mechanism, because the failure is silent: if a regex above stops
# matching, the page keeps building and simply documents fewer icons than the app draws.
for canary, mechanism in [("calendar-clock", 'bare Image("…")'),
                          ("map-pinned", "iconName computed in another file"),
                          ("zap", "icon: label"),
                          ("pen-tool", "icon: label carrying an ImageResource symbol"),
                          ("message-square-text", "bare Image(.imageResource)")]:
    assert canary in loose, f"icons: {canary} lost — {mechanism} no longer resolves"
# SF Symbols share names with Lucide glyphs, so over-matching is as wrong as under-matching:
# these three are drawn by Image(systemName:) and must never be presented as Lucide.
for impostor in ("sparkles", "circle", "hourglass"):
    assert impostor not in loose, f"icons: {impostor} is an SF Symbol, not a Lucide glyph"


def icon_grid(names):
    cells, absent = "", []
    for n in names:
        svg = lucide_svg(n)
        if svg is None:
            absent.append(n)
            continue
        cells += (f'<span class="icell" tabindex="0" aria-label="{html.escape(n)}">{svg}'
                  f'<span class="itip">{html.escape(n)}</span></span>')
    return f'<div class="igrid">{cells}</div>', absent


grid_reg, missing_reg = icon_grid(sorted(registered))
pi = (f'<h2>In use<span class="ct">{len(registered) - len(missing_reg)}</span></h2>'
      '<p class="lede sub">Named in <code>CustomIcons</code>, the '
      'sanctioned way to reference a glyph.</p>'
      + grid_reg)
if loose:
    grid_loose, missing_loose = icon_grid(loose)
    pi += (f'<h2>Referenced by raw name'
           f'<span class="ct">{len(loose)}</span></h2>'
           '<p class="lede sub">Also drawn, but named at the point of use &mdash; as a '
           'string literal, a computed <code>iconName</code>, or a generated '
           '<code>ImageResource</code> symbol &mdash; instead of going through '
           '<code>CustomIcons</code>, which <code>CustomIcons.swift</code> asks callers to '
           'prefer.</p>' + grid_loose)
    missing_reg += missing_loose
if missing_reg:
    pi += ('<div class="note"><b>Not glyphs in Lucide ' + LUCIDE_VERSION + ':</b> '
           + ", ".join(f"<code>{m}</code>" for m in sorted(set(missing_reg)))
           + ' &mdash; these resolve from the asset catalogue at runtime but have no upstream '
             'SVG, so they are either renamed, removed upstream, or bespoke.</div>')


# ------------------------------------------------------------ page: fonts
CSS_WEIGHT = {"Regular": 400, "Medium": 500, "Semibold": 600}
FSECTS = ["Headings", "Paragraphs", "Captions", "Footnotes", "Parsed Markdown Headings"]
SPECIMEN_TEXT = "Ag"


FONT_COLS = [("Token", "26%"), ("Value", "26%"),
             ("Notes", "30%"), ("Source", "18%")]


def exposure_specimen(otf, size, text=SPECIMEN_TEXT):
    """Rasterise an Exposure specimen. The 205TF licence forbids redistributing the font
    itself, so the site carries a picture of the type rather than the type."""
    from PIL import Image, ImageDraw, ImageFont
    scale = 3
    face = ImageFont.truetype(str(FONTDIR / otf), size * scale)
    box = face.getbbox(text)
    img = Image.new("RGBA", (box[2] - box[0] + 4, box[3] - box[1] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((2 - box[0], 2 - box[1]), text,
                             font=face, fill=(33, 18, 23, 255))
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    name = (f"{pathlib.Path(otf).stem.replace('[', '').replace(']', '')}-{size}"
            f"{'' if text == SPECIMEN_TEXT else '-' + slug}.png")
    (OUT / "specimens").mkdir(parents=True, exist_ok=True)
    img.save(OUT / "specimens" / name)
    # Rounded, not floored: flooring each axis separately moved the declared ratio off the
    # drawn one, which is a second way to stretch a glyph.
    return f"specimens/{name}", round(img.width / scale), round(img.height / scale)


pf = ""
for fs in FSECTS:
    group = [f for f in fonts if f["section"] == fs]
    if not group:
        continue
    pf += f'<h2>{fs}<span class="ct">{len(group)}</span></h2>'
    rows = []
    for f in group:
        # The real face at the real pt size, uncapped. It used to clamp at 34px to keep the
        # row short, which made heading1 (48) and heading1_5 (36) resolve to the same raster
        # — so the column whose whole job is relative size showed the two largest tokens as
        # identical. A taller row is the cheaper cost.
        shown = f["size"]
        label = f'{f["size"]}px {f["fam"]} {f["weight"]}'
        if f["fam"] == "Exposure":
            otf = "Exposure[+10].otf" if "+10" in f["ps"] else "Exposure[-10].otf"
            src, w, h = exposure_specimen(otf, shown)
            spec = (f'<span class="fspec"><img src="{src}" width="{w}" height="{h}" '
                    f'alt="Ag"></span>')
        else:
            spec = (f'<i class="fspec" style="font-family:Inter,ui-sans-serif;'
                    f'font-size:{shown}px;font-weight:{CSS_WEIGHT[f["weight"]]}">Ag</i>')
        # The doc comment opens by restating the name, metrics and ComponentsKit mapping,
        # each of which already has its own column. Keep the caveats.
        prose = re.sub(r"^[\w.\d ]+ - ", "", f["desc"])
        prose = re.sub(r"^\d+px [A-Za-z]+(?: (?:Regular|Medium|Semi[Bb]old|Bold))?", "", prose)
        prose = re.sub(r"^\s*\(custom font\)", "", prose)
        prose = re.sub(r"^[,.]?\s*\(maps to [^)]*\)", "", prose)
        prose = re.sub(r"^[,.]\s*", "", prose).strip()
        prose = re.sub(r"^\((.*)\)\.?$", r"\1", prose).strip()
        prose = (prose[:1].upper() + prose[1:]) if prose else ""
        rows.append([
            # The native Dynamic Type anchor sits under the token, not under the value: it
            # is the equivalent of the HH name, not a property of the rendered size.
            tk(f'HHFont.{f["name"]}',
               f'<code>.{f["anchor"]}</code>' if f["anchor"] else "inherited"),
            pv(spec, label),
            us(prose),
            f'<td class="us"><code>{html.escape(f["src"])}</code></td>',
        ])
    # Same spec for every section on this page: columns that do not line up between two
    # tables read as a rendering fault rather than as two tables.
    pf += ttable(FONT_COLS, rows)


# ---------------------------------------------------------- scale tables
def scale_table(items, kind, cap=64):
    rows = []
    for name, v, note in items:
        n = int(v) if v == int(v) else v
        if kind == "opacity":
            sw = f'<i class="chip solid" style="opacity:{v}"></i>'
            value = f"{round(v * 100)}%"
        elif kind == "radius":
            sw = f'<i class="chip solid" style="border-radius:{n}px"></i>'
            value = f"{n}pt"
        elif kind == "space":
            sw = f'<i class="mtrack"><i class="mbar" style="width:{min(v, cap)}px"></i></i>'
            value = f"{n}pt"
        else:
            sw = (f'<i class="mtrack"><i class="mbox" '
                  f'style="width:{min(v, 40)}px;height:{min(v, 40)}px"></i></i>')
            value = f"{n}pt"
        rows.append([tk(name), pv(sw, value), us(note)])
    return rows


SCALE_COLS = [("Token", "26%"), ("Value", "30%"), ("Notes", "44%")]

# Semantics closes with the state opacities. This has to land before COLOR_TABS, which
# captures p2 by value.
p2 += (f'<h2 id="opacity">Opacity<span class="ct">{len(OPACITY)}</span></h2>'
       '<p class="lede sub">State opacities. These modulate a colour '
       'that is already correct rather than name a new one.</p>'
       + ttable(SCALE_COLS, scale_table(OPACITY, "opacity")))


# ------------------------------------------------------- page: colors (tabbed)
# Primitives and semantics are one subject read two ways, so they share a page.
# The tab is in the URL hash, which makes it linkable and lets the sidebar's
# Primitives/Semantics children point straight at it.
# Semantics leads, and is the default by consequence: show() falls back to SL[0] for an
# absent or unrecognised hash. Semantic roles are what a screen is built from; primitives
# are the palette those are mixed out of, and opening on them invites picking a raw stop.
COLOR_TABS = [("semantics", "Semantics", p2), ("primitives", "Primitives", p1)]

pc = '<div class="ptabs" role="tablist">' + "".join(
    f'<a href="#{slug}" id="tab-{slug}" role="tab">{label}</a>'
    for slug, label, _ in COLOR_TABS) + "</div>"
for tab_slug, label, body_ in COLOR_TABS:
    pc += f'<section class="tabpanel" id="panel-{tab_slug}">{body_}</section>' 
pc += ('<script>'
       'const SL=["' + '","'.join(s for s, _, _ in COLOR_TABS) + '"];'
       'function show(s){if(!SL.includes(s))s=SL[0];'
       'SL.forEach(x=>{const p=document.getElementById("panel-"+x),t=document.getElementById("tab-"+x);'
       'p.hidden=x!==s;t.setAttribute("aria-selected",x===s);'
       # Keep the sidebar child in step with the visible tab.
       'const sb=document.querySelector(`.side .sub a[href$="#${x}"]`);'
       'if(sb)sb.classList.toggle("on",x===s);});}'
       'show(location.hash.slice(1));'
       'addEventListener("hashchange",()=>show(location.hash.slice(1)));'
       '</script>')


def scale_page(enum, items, kind, blurb):
    return (f'<h2>{enum}<span class="ct">{len(items)}</span></h2>'
            f'<p class="lede sub">{blurb}</p>'
            + ttable(SCALE_COLS, scale_table(items, kind)))


p_space = scale_page("HHSpacing", SPACING, "space",
                     "<code>space4</code> (16pt) is the default.")
p_radius = scale_page("HHRadius", RADIUS, "radius",
                      "<code>md</code> (8pt) is the base.")
p_sizing = scale_page("HHSizing", SIZING, "size",
                      "Control heights, avatar diameters and icon squares.")

# ---------------------------------------------------------------- page 3
def two_up(inner):
    return ('<div class="cpair">'
            f'<div class="light"><div class="cin">{inner}</div></div>'
            f'<div class="dark"><div class="cin">{inner}</div></div>'
            '</div>')


def _svg(paths, color="var(--foregroundSecondary)"):
    return (f'<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


I_DOC = '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
I_LANG = '<path d="M3 5h9"/><path d="M8 3c0 5-2 9-5 11"/><path d="M5.5 9c.5 3 3.5 5 6.5 6"/><path d="M13 21l4.5-10 4.5 10"/><path d="M14.5 17.5h6"/>'
I_STETH = '<path d="M5 3v5a4 4 0 0 0 8 0V3"/><path d="M9 16a5 5 0 0 0 5 5 4 4 0 0 0 4-4v-2"/><circle cx="18" cy="11" r="2"/>'
I_NOTE = '<path d="M5 4a1 1 0 0 1 1-1h8l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z"/><path d="M14 3v5h5"/><path d="M8 13h8M8 17h5"/>'
I_TRASH = '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/><path d="M10 11v6M14 11v6"/>'


def srow(icon, label, value=None, danger=False):
    color = 'var(--foregroundNegative)' if danger else 'var(--foregroundPrimary)'
    right = (f'<span class="lv">{value}<span class="lchev">›</span></span>' if value
             else '<span class="lchev">›</span>')
    return f'<div class="li">{icon}<span class="lm"><b style="color:{color}">{label}</b></span>{right}</div>'


TEXT = ('<div class="stack">'
        '<div style="color:var(--foregroundPrimary)">Primary — note body and section titles.</div>'
        '<div style="color:var(--foregroundSecondary)">Secondary — supporting captions and helper text.</div>'
        '<div style="color:var(--foregroundTertiary);font-size:13px">Tertiary — timestamps, counts and metadata.</div>'
        '<a href="#" style="color:var(--foregroundAccent);text-decoration:none;font-weight:500">Accent — view source transcript</a>'
        '</div>')

AVATARS = ('<div class="rowx">'
           '<span class="av" style="background:var(--fillBark);color:var(--foregroundBark)">MC</span>'
           '<span class="av" style="background:var(--fillSky);color:var(--foregroundSky)">DO</span>'
           '<span class="av" style="background:var(--fillForest);color:var(--foregroundForest)">PR</span>'
           '<span class="av" style="background:var(--fillSunlight);color:var(--foregroundSunlight)">TW</span>'
           '</div>')

def alert(bg, fg, icon, title, msg, border=False, last=False):
    styles = f'background:{bg}' + (';border:1px solid var(--border)' if border else '') + (';margin-bottom:0' if last else '')
    return (f'<div class="alert" style="{styles}">'
            f'<svg class="ai" viewBox="0 0 24 24" fill="none" stroke="{fg}" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round">{icon}</svg>'
            f'<span style="min-width:0"><b style="color:{fg}">{title}</b><p>{msg}</p></span></div>')


I_INFO = '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M12 12v4"/>'
I_CALERT = '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>'

ALERTS = (alert("var(--surfaceTertiary)", "var(--foregroundPrimary)", I_INFO,
                "New feature available", "Try the updated template picker from the session screen.", border=True)
          + alert("var(--fillNegativeMuted)", "var(--foregroundNegative)", I_CALERT,
                  "Silence detected", "We can't hear anything. Check your microphone is close to the conversation.", last=True))

SESSIONS = ('<div class="page" style="background:var(--surfaceSecondary)"><div class="pin">'
            '<div class="sec">Today</div>'
            '<div class="card sess">'
            '<div class="li"><span class="av sm" style="background:var(--fillForest);color:var(--foregroundForest)">A</span><span class="lm"><b>Andrew Gillis</b><i>11:00 AM · Consult note</i></span><span class="lr">›</span></div>'
            '<div class="li"><span class="av sm" style="background:var(--fillSky);color:var(--foregroundSky)">C</span><span class="lm"><b>Chloe Nguyen</b><i>9:28 AM · Symptoms review</i></span><span class="lr">›</span></div>'
            '</div>'
            '<div class="sec">Yesterday</div>'
            '<div class="card sess">'
            '<div class="li"><span class="av sm" style="background:var(--fillBark);color:var(--foregroundBark)">S</span><span class="lm"><b>Sarah Doyle</b><i>11:56 AM · Pain management</i></span><span class="lr">›</span></div>'
            '</div></div></div>')

SETTINGS = ('<div class="page" style="background:var(--surfaceSecondary)"><div class="pin">'
            '<div class="ttl">Session settings</div>'
            '<div class="ssub">Applies to this consult only</div>'
            '<div class="card">'
            + srow(_svg(I_DOC), "Template", "SOAP note")
            + srow(_svg(I_LANG), "Language", "English (AU)")
            + srow(_svg(I_STETH), "Consult type", "In person")
            + f'<div class="li">{_svg(I_NOTE)}<span class="lm"><b>Auto-generate note</b><i>When recording stops</i></span><span class="tgl"><i></i></span></div>'
            + srow(_svg(I_TRASH, "var(--foregroundNegative)"), "Delete session", danger=True)
            + '</div></div></div>')

CHAT = ('<div class="page" style="background:var(--surfacePrimary)">'
        '<div style="padding:14px 14px 12px;display:flex;flex-direction:column;gap:12px">'
        '<div style="display:flex;justify-content:flex-end;padding-left:10%">'
        '<div class="ubub">First-line antibiotic for community-acquired pneumonia in a healthy adult?</div>'
        '</div>'
        '<div class="ans">Amoxicillin 500 mg three times daily for 5 days is first-line for a previously healthy adult. <span class=\"cite\"><svg viewBox=\"0 0 24 24\" width=\"11\" height=\"11\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" style=\"flex:0 0 auto\"><path d=\"M9 15l6-6\"/><path d=\"M12 6l1-1a4 4 0 0 1 6 6l-1 1\"/><path d=\"M12 18l-1 1a4 4 0 0 1-6-6l1-1\"/></svg>NICE</span> Add a macrolide only if atypical cover is suspected. <span class=\"cite\"><svg viewBox=\"0 0 24 24\" width=\"11\" height=\"11\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" style=\"flex:0 0 auto\"><path d=\"M9 15l6-6\"/><path d=\"M12 6l1-1a4 4 0 0 1 6 6l-1 1\"/><path d=\"M12 18l-1 1a4 4 0 0 1-6-6l1-1\"/></svg>UpToDate<b class=\"cn\">+2</b></span></div>'
        '<div style="display:flex;justify-content:flex-end;padding-left:10%">'
        '<div class="ubub">Any change for a penicillin allergy?</div>'
        '</div>'
        '<div class="ans">Use doxycycline 100 mg twice daily, or a macrolide such as clarithromycin. <span class=\"cite\"><svg viewBox=\"0 0 24 24\" width=\"11\" height=\"11\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" style=\"flex:0 0 auto\"><path d=\"M9 15l6-6\"/><path d=\"M12 6l1-1a4 4 0 0 1 6 6l-1 1\"/><path d=\"M12 18l-1 1a4 4 0 0 1-6-6l1-1\"/></svg>BNF</span></div>'
        '<div class="kp">Key points · 3 findings</div>'
        '</div>'
        '<div class="band"><div class="inp" style="margin-bottom:8px">Ask Heidi…</div>'
        '<div style="display:flex;align-items:center;gap:7px">'
        '<span class="ibtn">+</span><span class="ibtn">Sources</span>'
        '<span class="send" style="margin-left:auto"></span></div></div>'
        '</div>')

def _pill_glyph(paths):
    # iconXSmall (12) — the pill's leading glyph slot, whichever glyph fills it.
    return ('<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex:0 0 auto">'
            f'{paths}</svg>')


LINK = _pill_glyph('<path d="M9 15l6-6"/><path d="M12 6l1-1a4 4 0 0 1 6 6l-1 1"/>'
                   '<path d="M12 18l-1 1a4 4 0 0 1-6-6l1-1"/>')
PILL_DOC = _pill_glyph(I_DOC)


def cite(name, extra=None):
    n = f'<b class="cn">+{extra}</b>' if extra else ''
    return f'<span class="cite">{LINK}{name}{n}</span>'


I_WAVE = '<path d="M3 10v4M7 7v10M11 4v16M15 7v10M19 10v4"/>'
I_CHECKC = '<circle cx="12" cy="12" r="9"/><path d="M8.5 12l2.5 2.5 4.5-5"/>'
I_TRI = '<path d="M12 3L2.5 20h19z"/><path d="M12 9v5M12 17.5h.01"/>'

def orb(bg, icon, label, cutout):
    return (f'<span class="orbcol"><span class="orb" style="background:{bg}">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="{cutout}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{icon}</svg></span>'
            f'<span class="orblbl">{label}</span></span>')

RECORDING = ('<div class="page" style="background:var(--surfacePrimary)"><div class="pin">'
             '<div class="orbwrap">'
             + orb("var(--fillPositive)", I_WAVE, "Ready", "var(--surfacePrimary)")
             + orb("var(--fillAccent)",
                   '<rect x="7.5" y="7.5" width="9" height="9" rx="1.5" fill="var(--surfacePrimary)" stroke="none"/>',
                   "Recording", "var(--surfacePrimary)")
             + '</div>'
             '<div style="display:flex;justify-content:center;padding:6px 0 8px">'
             '<span class="rectime"><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" '
             'stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="13.5" r="7"/><path d="M12 10.5v3M10 2.5h4M12 2.5v2"/></svg>'
             '12:36<span class="recdot"></span></span>'
             '</div></div></div>')


def toast(bg, fg, sub, icon, title, msg, last=False):
    m = ';margin-bottom:0' if last else ''
    return (f'<div class="toast" style="background:{bg}{m}">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="{fg}" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round">{icon}</svg>'
            f'<span style="min-width:0"><b style="color:{fg}">{title}</b>'
            f'<p style="color:{sub}">{msg}</p></span>'
            f'<span class="tx" style="color:{sub}">✕</span></div>')

TOASTS = (toast("var(--fillPositive)", "#fff", "rgba(255,255,255,.9)", I_CHECKC,
                "Note generated", "SOAP note is ready to review.")
          + toast("var(--fillNegative)", "#fff", "rgba(255,255,255,.9)", I_TRI,
                  "Upload failed", "We'll retry when you're back online.")
          + toast("var(--surfaceTertiary)", "var(--foregroundPrimary)", "var(--foregroundSecondary)", I_INFO,
                  "Session recovered", "Recording resumed from your last session.", last=True))

I_FLASH = '<path d="M13 2L4.5 13.5h6L11 22l8.5-11.5h-6z"/>'

PILLS = ('<div class="rowx">'
         + cite("PubMed", "2")
         + '<span class="cite" style="background:var(--fillProMuted);color:var(--foregroundPro)">'
         + PILL_DOC + 'Patient document</span>'
         '<svg viewBox="0 0 24 24" width="17" height="17" fill="var(--foregroundPro)" stroke="none">' + I_FLASH + '</svg>'
         '</div>')

COMPONENTS = [
    ("Text hierarchy", "foregroundPrimary · Secondary · Tertiary · Accent",
     "Four foreground roles carry the whole type ramp; size and weight do the rest.", TEXT),
    ("Avatars — AvatarView", "fillBark/Sky/Forest/Sunlight + matching foreground",
     "44pt circle, initials in 16pt rounded regular; HHAccentHue picks a stable fill/foreground pair per name.", AVATARS),
    ("Pills — CitationAttachment & Pro", "fillSecondary · foregroundSecondary · fillProMuted · foregroundPro",
     "Citation pill: per-source favicon (link glyph until it loads), source name, +N count. Patient documents take the Pro-muted pair and a document glyph; the Pro flash indicator is icon-only. Both tone pairs come from CitationPillPalette, shared with the TextKit renderer.", PILLS),
    ("Alerts — HHAlert", "surfaceTertiary + border · fillNegativeMuted",
     "Two variants only: default (surfaceTertiary, hairline, info icon) and destructive (fillNegativeMuted, circle-alert). heading5 title, paragraph2 secondary message.", ALERTS),
    ("Recording orb", "fillPositive ready · fillAccent recording · fillNegative timer dot",
     "100pt circle; the state icon is cut out of the fill. Positive when ready, accent while recording; the elapsed-time row is foregroundSecondary with a pulsing fillNegative dot.", RECORDING),
    ("Toasts", "fillPositive · fillNegative · surfaceTertiary",
     "Transient, bottom-anchored (unlike HHAlert). Success and error use solid status fills with white text; info and warning sit on surfaceTertiary with primary/secondary text.", TOASTS),
    ("Session list", "surfaceSecondary page · surfaceTertiary groups",
     "Page on surfaceSecondary; each date group is an inset, clipped surfaceTertiary container (radius 28), dividers inset past the avatar.", SESSIONS),
    ("Settings sheet", "surfaceSecondary · surfaceTertiary · foregroundNegative",
     "Grouped rows in a flat surfaceTertiary card — leading icons, right-aligned values, a toggle, and a destructive action.", SETTINGS),
    ("Evidence chat", "surfacePrimary · fillSecondary · fillPrimary · fillInfoMuted",
     "Your question sits in a fillSecondary bubble; Heidi's answer is flush foregroundPrimary text with inline citation pills. The input band matches the page, with fillPrimary buttons carrying primary labels.", CHAT),
]

# Which page each existing demo lives on. `None` parks a built demo that has no page in
# the IA yet — it stays in the generator, and the build prints it so it can't be forgotten.
ROUTE = {
    # A colour demo (foreground roles), not a type demo — it doesn't belong on Fonts.
    "Text hierarchy": None,
    "Avatars — AvatarView": None,
    "Toasts": None,
    "Session list": None,
    "Settings sheet": None,
    "Pills — CitationAttachment & Pro": None,
    "Alerts — HHAlert": None,
    "Recording orb": None,
    "Evidence chat": None,
}
missing = [c[0] for c in COMPONENTS if c[0] not in ROUTE]
assert not missing, f"demo not routed to a page: {missing}"

demos, parked = {}, []
for name, toks, desc, inner in COMPONENTS:
    if ROUTE[name] is None:
        parked.append(name)
        continue
    demos.setdefault(ROUTE[name], "")
    demos[ROUTE[name]] += (
        # One chip per token, not one per list: each is separately copyable, and a chip
        # spanning "a · b" would put the separator on the clipboard.
        f'<section class="comp"><div class="comp-h"><b>{name}</b>'
        + " &middot; ".join(f"<code>{t.strip()}</code>"
                            for t in toks.split("&middot;")) + '</div>'
        f'{two_up(inner)}</section>')

TOKEN_NOTE = ('<div class="note"><b>Every preview is driven by the same token values as the app.</b> '
              'In dark mode, <code>surfaceSecondary</code> and <code>surfaceTertiary</code> '
              'sit one Neutral stop apart.</div>')


def stub(what):
    return ('<div class="stub"><b>Not documented yet</b>'
            f'<p>{what}</p></div>')


# ---------------------------------------------------------- page: shadows
# Elevation is its own token family: HeidiShadowStyle pairs an offset, a radius and a
# tone. The tone is Bark 950, not black, which is the part call sites most often miss.
SHADOW_SRC = read_swift(ROOT / "HeidiNative/Extensions/View+HeidiShadow.swift")
SHADOW_TONE = dict(ramps["HHBark"])["s950"]

shadows = []
for m in re.finditer(r"((?:[ \t]*///[^\n]*\n)*)[ \t]*static var (\w+) = HeidiShadowStyle\("
                     r"xOffset: ([\d.-]+), yOffset: ([\d.-]+), radius: ([\d.]+), "
                     r"color: (?:shadowTint\(([\d.]+)\)|(Color\.\w+))\)", SHADOW_SRC):
    doc = " ".join(l.strip().lstrip("/").strip() for l in m.group(1).strip().splitlines())
    if is_debug(m.group(2)):
        continue
    shadows.append(dict(name=m.group(2), x=float(m.group(3)), y=float(m.group(4)),
                        r=float(m.group(5)), alpha=float(m.group(6)) if m.group(6) else None,
                        literal=m.group(7), doc=doc))

# How often each style is actually applied, so an unused step is visible as unused.
_swift = swift_sources(ROOT / "HeidiNative")
_all_src = "\n".join(read_swift(f) for f in _swift)
SHADOW_USES = {sh["name"]: len(re.findall(r"heidiShadow\(\." + sh["name"] + r"\b", _all_src))
               for sh in shadows}

# Call sites that build a shadow by hand instead of going through the family.
raw_shadows = []
for f in _swift:
    if f.name == "View+HeidiShadow.swift":
        continue
    txt = read_swift(f)
    for m in re.finditer(r"\.shadow\(", txt):
        depth, i = 1, m.end()
        while i < len(txt) and depth:
            depth += (txt[i] == "(") - (txt[i] == ")")
            i += 1
        args = " ".join(txt[m.end():i - 1].split())
        if not args or "style." in args:
            continue
        raw_shadows.append((f.relative_to(ROOT / "HeidiNative").as_posix(), args))


def shadow_css(sh, alpha=None):
    a = sh["alpha"] if alpha is None else alpha
    if a is None:
        # A style that names a flat SwiftUI colour instead of toning Bark 950. The name is
        # also a CSS keyword, so the preview shows the colour the call site really gets.
        return f'{sh["x"]:g}px {sh["y"]:g}px {sh["r"] * 2:g}px {sh["literal"].split(".")[-1]}'
    # SwiftUI and CSS define blur differently; ~2x the token radius reads closest.
    return (f'{sh["x"]:g}px {sh["y"]:g}px {sh["r"] * 2:g}px '
            f'{rgba(SHADOW_TONE, a)}')


def shadow_value(sh):
    tone = (f'Bark 950 &middot; {round(sh["alpha"] * 100)}%' if sh["alpha"] is not None
            else html.escape(sh["literal"]))
    return f'x {sh["x"]:g} &middot; y {sh["y"]:g} &middot; radius {sh["r"]:g}<br>{tone}'


ps_rows = []
for sh in shadows:
    uses = SHADOW_USES[sh["name"]]
    note = sh["doc"] or ""
    note += (f' <i class="unused">{uses} call site{"" if uses == 1 else "s"}</i>' if uses
             else ' <i class="unused">not applied anywhere</i>')
    ps_rows.append([
        tk(f'.{sh["name"]}'),
        pv(f'<i class="shwell"><i class="shsw" style="box-shadow:{shadow_css(sh)}"></i></i>',
           f'{sh["r"]:g}pt blur', f'y {sh["y"]:g}'),
        us(note),
        f'<td class="us"><code>{shadow_value(sh)}</code></td>',
    ])

psh = ('<h2>HeidiShadowStyle<span class="ct">' + str(len(shadows)) + '</span></h2>'
       '<p class="lede sub">Applied with <code>.heidiShadow(_:)</code>. The tone is '
       '<code>HHBark.s950</code> rather than black, so elevation stays in the warm neutral '
       'family; opacity separates the steps.</p>'
       + ttable([("Token", "20%"), ("Preview", "26%"), ("Notes", "32%"), ("Value", "22%")],
                ps_rows))

if raw_shadows:
    black = [(f, a) for f, a in raw_shadows if ".black" in a]
    psh += (f'<h2>Built by hand<span class="ct">{len(raw_shadows)}</span></h2>'
            '<p class="lede sub">Call sites that pass offsets and a colour straight to '
            '<code>.shadow(&hellip;)</code> instead of naming a style. '
            + (f'{len(black)} of them use <code>.black</code>, which leaves the warm neutral '
               'family the tokens exist to hold.' if black else '')
            + '</p>'
            + ttable([("Site", "34%"), ("Arguments", "66%")],
                     [[f'<td class="tk">{html.escape(f)}</td>',
                       f'<td class="us"><code>{html.escape(a)}</code></td>']
                      for f, a in sorted(raw_shadows)]))


# ---------------------------------------------------------- page: avatars
# AvatarView's whole variant space, driven by the same rules as the Swift view: the hue
# comes from the name, so these are the real pairings rather than four chosen colours.
AVATAR_HUES = ["bark", "sky", "forest", "sunlight"]


def avatar_hue(name):
    """Mirror of HHAccentHue.stableHue(forName:) — sum of scalars, modulo the hue count."""
    return AVATAR_HUES[abs(sum(ord(c) for c in name)) % len(AVATAR_HUES)]


def avatar_initials(name):
    """Mirror of AvatarView.initials: first letter of each component, digits dropped, max 2."""
    firsts = [part[0] for part in name.split() if part]
    return "".join(c.upper() for c in firsts if not c.isdigit())[:2]


# Rough stand-ins for the SF Symbols AvatarView falls back to. The caption names the real
# symbol so nobody reads these as the shipped glyph.
SF_LINK = ('<path d="M9.5 14.5l5-5"/><path d="M12.5 7.5l1.2-1.2a3.2 3.2 0 014.5 4.5l-1.2 1.2"/>'
           '<path d="M11.5 16.5l-1.2 1.2a3.2 3.2 0 01-4.5-4.5l1.2-1.2"/>')
SF_PERSON = '<circle cx="12" cy="9" r="3.4"/><path d="M5.5 19.5a6.5 6.5 0 0113 0"/>'


def avatar(name=None, size=44, placeholder=False, glyph=None):
    if placeholder:
        bg, fg = "var(--fillSecondary)", "var(--foregroundSecondary)"
    elif name is None:
        bg, fg = "var(--fillPrimary)", "var(--foregroundSecondary)"
    else:
        hue = avatar_hue(name)
        bg, fg = f"var(--fill{hue.capitalize()})", f"var(--foreground{hue.capitalize()})"
    inner = ""
    if glyph:
        g = round(size * 20 / 44)
        inner = (f'<svg viewBox="0 0 24 24" width="{g}" height="{g}" fill="none" '
                 f'stroke="{fg}" stroke-width="1.8" stroke-linecap="round" '
                 f'stroke-linejoin="round">{glyph}</svg>')
    elif name:
        inner = avatar_initials(name)
    dash = (';border:1px dashed var(--border)') if placeholder else ""
    return (f'<span class="avx" style="width:{size}px;height:{size}px;background:{bg};'
            f'color:{fg};font-size:{round(size * 16 / 44, 1)}px{dash}">{inner}</span>')


def avatar_row(items):
    cells = "".join(f'<span class="avcell">{av}<em>{cap}</em></span>' for av, cap in items)
    return f'<div class="avrow">{cells}</div>'


AV_HUE_NAMES = ["Priya Raman", "Marc Antoine", "Dr Olivia Reed", "Tom Walsh"]
pa = ('<h2>Accent hue<span class="ct">4</span></h2>'
      '<p class="lede sub">The hue is derived from the name, so the same '
      'person is always the same colour. <code>HHAccentHue</code> sums the name&rsquo;s unicode '
      'scalars and indexes <code>[bark, sky, forest, sunlight]</code>.</p>'
      + two_up(avatar_row([(avatar(n), f"{n} &middot; {avatar_hue(n)}") for n in AV_HUE_NAMES]))
      + '<h2>Initials</h2>'
      '<p class="lede sub">First letter of each name component, '
      'capitalised, digits dropped, first two kept.</p>'
      + two_up(avatar_row([
          (avatar("Heidi"), "Heidi &rarr; H"),
          (avatar("Marc Antoine"), "Marc Antoine &rarr; MA"),
          (avatar("Dr Olivia Reed"), "Dr Olivia Reed &rarr; DO"),
          (avatar("4 Corners Clinic"), "4 Corners Clinic &rarr; CC"),
      ]))
      + '<h2>Fallbacks</h2>'
      '<p class="lede sub">With no usable initials the view falls back to '
      'an SF Symbol. No name at all is a different case from a name that yields nothing.</p>'
      + two_up(avatar_row([
          (avatar(None, glyph=SF_LINK), "name nil &middot; <code>link</code> on fillPrimary"),
          (avatar("123", glyph=SF_PERSON), "name &ldquo;123&rdquo; &middot; <code>person.fill</code>"),
          (avatar("Sam Idris", placeholder=True, glyph=SF_PERSON),
           "<code>placeholderStyled</code> &middot; dashed border"),
      ]))
      + '<h2>Sizes<span class="ct">3</span></h2>'
      '<p class="lede sub">44pt is the default. Initials and the '
      'placeholder glyph scale proportionally, so any size stays optically the same avatar.</p>'
      + two_up(avatar_row([
          (avatar("Marc Antoine", size=32), "32pt &middot; <code>avatarSmall</code>"),
          (avatar("Marc Antoine", size=44), "44pt &middot; <code>avatarMedium</code> (default)"),
          (avatar("Marc Antoine", size=64), "64pt &middot; <code>avatarLarge</code>"),
      ])))


# ---------------------------------------------------------- page: buttons
# Buttons are the one component family with a real shared implementation, so this page is
# parsed rather than written: the ButtonStyle files give the specs, and a repo-wide sweep
# gives adoption plus everything that bypasses them. The curated notes on the bespoke
# controls carry a regex anchor that has to match exactly once, so a control that is moved,
# renamed or deleted fails the build instead of leaving the page quietly wrong.
BTN_DIR = ROOT / "HeidiNative/Styles/ButtonStyles"
# Paths are shown relative to HeidiNative/, which is how they read in a grep.
SRC = {f.relative_to(ROOT / "HeidiNative").as_posix(): read_swift(f) for f in _swift}
WIDGET_SRC = {f.relative_to(ROOT / "HeidiNativeWidgets").as_posix(): read_swift(f)
              for f in swift_sources(ROOT / "HeidiNativeWidgets")}

# Every length token, so a parsed expression can be resolved to points and, more usefully,
# reported as a token or as a raw literal.
LEN = {f"HHSpacing.{n}": v for n, v, _ in SPACING}
LEN.update({f"HHSizing.{n}": v for n, v, _ in _sizing_all})
LEN.update({f"HHRadius.{n}": v for n, v, _ in RADIUS})

# The SwiftUI text styles the button styles reach for. None of them is an HHFont token,
# which is the finding — asserting the mapping means a new one can't slip past unlabelled.
SWIFT_TYPE = {".headline": (17, 600, "SF Pro headline &middot; 17pt semibold"),
              ".subheadline.weight(.semibold)": (15, 600,
                                                 "SF Pro subheadline &middot; 15pt semibold")}


def sweep(pattern, src=None):
    """[(path, [lines], occurrences)] for a regex, in path order.

    The corpus is already debug-free — `SRC` is built from `swift_sources` and every
    `#if DEBUG` branch in it is blanked — so no caller has to remember to opt out."""
    out = []
    for path, txt in sorted((src if src is not None else SRC).items()):
        lines, n = [], 0
        for i, ln in enumerate(txt.splitlines(), 1):
            hits = len(re.findall(pattern, ln))
            if hits:
                lines.append(i)
                n += hits
        if lines:
            out.append((path, lines, n))
    return out


def total(rows):
    return sum(n for _, _, n in rows)


def plural(n, word):
    return "%s %s%s" % (n, word, "" if n == 1 else "s")


def sitelist(rows, label=None):
    """Collapsed file:line list. Long by nature, so it opens on demand."""
    if not rows:
        return ""
    n, files = total(rows), len(rows)
    head = label or plural(n, "call site") + " in " + plural(files, "file")
    # One `path:lines` per row, in the shape you would paste into an editor's go-to-file —
    # the column is a list of source references, so it is set as code rather than as prose.
    body = "".join(f'<div><span class="p">{html.escape(p)}</span>'
                   f'<span class="l">:{", ".join(str(x) for x in ls)}</span></div>'
                   for p, ls, _ in rows)
    return (f'<details class="sites"><summary>{head}</summary>'
            f'<div class="sitelist">{body}</div></details>')


def paren_arg(txt, marker, start=0):
    """The balanced argument of the first `marker` (which ends in `(`) after `start`."""
    i = txt.find(marker, start)
    if i < 0:
        return None
    i += len(marker)
    depth, j = 1, i
    while j < len(txt) and depth:
        depth += (txt[j] == "(") - (txt[j] == ")")
        j += 1
    return txt[i:j - 1].strip()


def pt(expr, statics=None):
    """A Swift length expression as {expr, v, tok} — tok says whether it named a token."""
    if expr is None:
        return None
    expr = expr.strip()
    if expr in LEN:
        return dict(expr=expr, v=LEN[expr], tok=True)
    if statics and expr in statics:
        return dict(expr=expr, v=statics[expr], tok=False)
    try:
        return dict(expr=expr, v=float(expr), tok=False)
    except ValueError:
        return dict(expr=expr, v=None, tok=False)


def g(pattern, text, cast=None):
    m = re.search(pattern, text)
    if not m:
        return None
    return cast(m.group(1)) if cast else m.group(1)


def pts(x):
    """Points, without a trailing .0 on whole numbers."""
    return f"{x:g}pt" if x is not None else "&mdash;"


# ------------------------------------------------------------ parse the styles
BSTYLES = []
for _f in swift_sources(BTN_DIR):
    src = read_swift(_f)
    sname = re.search(r"struct (\w+): ButtonStyle", src).group(1)
    if is_debug(sname):
        continue
    statics = {f"Self.{m.group(1)}": float(m.group(2))
               for m in re.finditer(r"static let (\w+): CGFloat = ([\d.]+)", src)}
    params = [(m.group(1), m.group(2), m.group(3).strip())
              for m in re.finditer(r"^\s+var (\w+): (\w+) = (.+)$", src, re.M)]
    defaults = {n: v for n, _, v in params}
    # Shorthands live in an `extension ButtonStyle where Self == …` under the struct.
    shorthands = []
    if "extension ButtonStyle" in src:
        ext = src[src.index("extension ButtonStyle"):]
        for m in re.finditer(r"static (var|func) (\w+)(\([^)]*\))?", ext):
            labels = ""
            if m.group(1) == "func":
                labels = "(" + "".join(f"{a.split(':')[0].strip()}:"
                                       for a in m.group(3)[1:-1].split(",")) + ")"
            shorthands.append("." + m.group(2) + labels)

    # A style can carry more than one layout. HeidiSecondaryButtonStyle's makeBody only
    # picks between two private bodies, so the bodies — not the file — are the variants.
    heads = list(re.finditer(r"^[ \t]*(?:private )?func (\w+)\(configuration: Configuration\)"
                             r"[^\n]*$", src, re.M))
    trigger = {}
    for i, h in enumerate(heads):
        body = src[h.end():(heads[i + 1].start() if i + 1 < len(heads) else len(src))]
        body = body.split("\n}")[0]
        if ".background(" in body:
            continue                      # a real layout, handled below
        cond = re.search(r"if (\w+) \{\s*(\w+)\(configuration", body)
        alt = re.search(r"\} else \{\s*(\w+)\(configuration", body)
        if cond:
            trigger[cond.group(2)] = f"{cond.group(1)}: true"
            if alt:
                trigger[alt.group(1)] = f"{cond.group(1)}: false (default)"

    for i, h in enumerate(heads):
        fn = h.group(1)
        body = src[h.end():(heads[i + 1].start() if i + 1 < len(heads) else len(src))]
        body = body.split("\n}")[0]
        if ".background(" not in body:
            continue
        pad = pt(g(r"\.padding\(([\w.]+)\)", body), statics)
        pad_h_extra = pt(g(r"\.padding\(\.horizontal, ([\w.]+)\)", body), statics)
        min_h = pt(g(r"minHeight: ([\w.]+)", body), statics)
        capsule = "Capsule()" in body
        radius_x = g(r"RoundedRectangle\(cornerRadius: ([\w.]+)\)", body)
        radius = None if capsule else pt(defaults.get(radius_x, radius_x), statics)
        fill = paren_arg(body, ".fill(") or ""
        font_x = paren_arg(body, ".font(")
        assert font_x in SWIFT_TYPE, f"{sname}: unmapped font {font_x!r}"
        disabled = re.findall(r"isEnabled \? [^\n]*? : (HHSizing\.\w+)", body)
        BSTYLES.append(dict(
            style=sname, fn=fn, file=_f.relative_to(ROOT / "HeidiNative").as_posix(),
            line=src[:h.start()].count("\n") + 1,
            variant=(re.sub(r"(?<!^)(?=[A-Z])", " ", fn.replace("Body", "")).lower()
                     if fn != "makeBody" else ""),
            trigger=trigger.get(fn, ""), params=params, shorthands=shorthands,
            pad_v=pad, pad_h_extra=pad_h_extra, min_h=min_h, capsule=capsule,
            radius=radius, full=("maxWidth: .infinity" in body),
            fill=fill, fill_tok=g(r"HHColors\.(\w+)", fill),
            fg=g(r"foregroundStyle\(\s*\n?\s*HHColors\.(\w+)", body),
            font=font_x,
            pressed=g(r"isPressed \? ([\d.]+)", body, float),
            scale=g(r"scaleEffect\(configuration\.isPressed \? ([\d.]+)", body, float),
            anim=g(r"easeOut\(duration: ([\d.]+)\)", body, float),
            disabled=sorted(set(disabled)),
            loading=("ProgressView(" in body),
            spinner_tint=g(r"ProgressView\(\)\s*\n?\s*\.tint\(\.(\w+)\)", body),
            spinner_gap=g(r"Spacer\(\)\.frame\(width: (\d+)\)", body, float),
            spinner_small=("controlSize(.small)" in body),
            shadow=g(r"heidiShadow\(\.(\w+)\)", body),
            border=("strokeBorder" in body),
            border_w=pt(g(r"lineWidth: ([\w.]+)", body), statics),
            line_limit=g(r"lineLimit\((\d+)\)", body, int),
            min_scale=g(r"minimumScaleFactor\(([\d.]+)\)", body, float),
            hides_icon=("hidingLabelIcon" in body),
        ))

# One extra conformance lives outside the folder; it is private to its own view, which is
# exactly why it is worth naming here.
_dial = read_swift(ROOT / "HeidiNative/Common/Components/PhoneDialPad.swift")
assert "private struct PhoneDialPadKeyButtonStyle: ButtonStyle" in _dial
_other_styles = [(p, ls) for p, ls, _ in sweep(r"struct \w+: ButtonStyle")
                 if not p.startswith("Styles/ButtonStyles/")]

BVARIANTS = len(BSTYLES)
BTYPES = len({b["style"] for b in BSTYLES})


# --------------------------------------------------------------- the previews
def bcolor(expr, alpha=1.0):
    """A Swift fill expression as a CSS colour, dimmed to `alpha` where asked."""
    m = re.search(r"HHColors\.(\w+)", expr or "")
    base = (f"var(--{m.group(1)})" if m else
            "var(--uiSystemGrouped)" if "systemGroupedBackground" in (expr or "") else
            "transparent")
    if alpha >= 1:
        return base
    return f"color-mix(in srgb, {base} {alpha * 100:g}%, transparent)"


BSTATES = ["default", "pressed", "disabled", "loading"]


def bdemo(v, state, label="Start session"):
    """One button, in one state, with every number taken from the parsed style."""
    size, weight, _ = SWIFT_TYPE[v["font"]]
    pad_v = (v["pad_v"] or {}).get("v") or 0
    pad_h = pad_v + ((v["pad_h_extra"] or {}).get("v") or 0)
    css = [f"font-size:{size}px", f"font-weight:{weight}",
           f"padding:{pad_v:g}px {pad_h:g}px",
           f'border-radius:{999 if v["capsule"] else ((v["radius"] or {}).get("v") or 0):g}px']
    if v["min_h"]:
        css.append(f'min-height:{v["min_h"]["v"] + 2 * pad_v:g}px')
    # The disabled opacities are per-style: some dim only the fill, Outline also dims the
    # border and the label, and two capsule styles have no disabled treatment at all.
    fill_a = fg_a = 1.0
    if state == "pressed":
        fill_a = v["pressed"] or 1.0
        css.append(f'transform:scale({v["scale"] or 1})')
    if state == "disabled":
        toks = v["disabled"]
        fill_a = LEN.get(toks[0], 1.0) if toks else 1.0
        fg_a = LEN.get("HHSizing.opacityDisabled") if "HHSizing.opacityDisabled" in toks else 1.0
        if len(toks) == 1 and toks[0] == "HHSizing.opacityDisabled" and not v["border"]:
            fg_a = 1.0
    css.append(f'background:{bcolor(v["fill"], fill_a)}')
    css.append(f'color:{bcolor("HHColors." + (v["fg"] or "foregroundPrimary"), fg_a)}')
    shade = []
    if v["border"]:
        w = (v["border_w"] or {}).get("v") or 1
        shade.append(f'inset 0 0 0 {w:g}px {bcolor("HHColors.border", fill_a)}')
    if v["shadow"]:
        shade.append(shadow_css(next(s for s in shadows if s["name"] == v["shadow"])))
    if shade:
        css.append("box-shadow:" + ",".join(shade))
    spin = '<i class="bspin"></i>' if state == "loading" else ""
    wide = " wide" if v["full"] else ""
    return f'<span class="bx{wide}" style="{";".join(css)}">{spin}{label}</span>'


def bstates(v):
    cells = []
    for s in BSTATES:
        if s == "loading" and not v["loading"]:
            continue
        if s == "disabled" and not v["disabled"]:
            continue
        cells.append(f'<div class="bstate"><em>{s}</em>{bdemo(v, s)}</div>')
    return f'<div class="bstates">{"".join(cells)}</div>'


def bname(v):
    return v["style"] + (f' · {v["variant"]}' if v["variant"] else "")


# ------------------------------------------------------------------- adoption
def adoption(v):
    """Direct-init and shorthand call sites for a style, minus the style's own file."""
    direct = [r for r in sweep(r"\.buttonStyle\(\s*" + v["style"] + r"\(")
              if not r[0].startswith("Styles/ButtonStyles/")]
    short = {}
    for sh in v["shorthands"]:
        stem = r"\.buttonStyle\(\s*" + re.escape(sh.split("(")[0])
        # The parameterised shorthand and the bare one are different call sites.
        short[sh] = sweep(stem + (r"\(" if sh.endswith(")") else r"\b(?!\()"))
    return direct, short


# ------------------------------------------------------ tab 1 — shared styles
b_specs = []
for v in BSTYLES:
    pad_v = (v["pad_v"] or {}).get("v") or 0
    pad_h = pad_v + ((v["pad_h_extra"] or {}).get("v") or 0)
    height = (f'{v["min_h"]["v"] + 2 * pad_v:g}pt' if v["min_h"] else "hugs the label")
    if v["min_h"] and pad_v:
        height += f' <span class="gap">({pts(v["min_h"]["v"])} + {pts(pad_v)} padding)</span>'
    shape = ("Capsule" if v["capsule"]
             else f'RoundedRectangle {pts((v["radius"] or {}).get("v"))}')
    if v["border"]:
        shape += f' + {pts((v["border_w"] or {}).get("v"))} border'
    b_specs.append([
        tk(bname(v), v["trigger"]),
        us("full width" if v["full"] else "fits its label"),
        us(shape),
        us(f'{height}<br><span class="gap">padding {pts(pad_v)} / {pts(pad_h)}</span>'),
        us(f'<code>{html.escape(v["font"])}</code><br>'
           f'<span class="gap">{SWIFT_TYPE[v["font"]][2]}</span>'),
        us((f'<code>{v["fill_tok"]}</code>' if v["fill_tok"]
            else f'<i class="warnv"><code>{html.escape(v["fill"])}</code></i>')
           + f'<br><span class="gap">on <code>{v["fg"]}</code></span>'),
    ])

b_state_rows = []
for v in BSTYLES:
    dis = (", ".join(f'<code>{t.split(".")[1]}</code>' for t in v["disabled"])
           if v["disabled"] else '<i class="warnv">no disabled state</i>')
    load = (f'spinner tinted <code>{v["spinner_tint"]}</code>'
            + (f', {pts(v["spinner_gap"])} gap' if v["spinner_gap"] else "")
            + (", small control size" if v["spinner_small"] else "")
            + (", label icon hidden" if v["hides_icon"] else "")
            if v["loading"] else '<i class="warnv">no loading state</i>')
    b_state_rows.append([
        tk(bname(v)),
        us(f'fill &times;{v["pressed"]:g}, scale {v["scale"]:g}, '
           f'<span class="gap">{v["anim"]:g}s ease-out</span>'),
        us(dis),
        us(load),
        us(f'<code>.{v["shadow"]}</code>' if v["shadow"] else '<span class="gap">none</span>'),
    ])

b_adopt_rows, b_dead = [], []
seen_style = set()
for v in BSTYLES:
    if v["style"] in seen_style:
        continue
    seen_style.add(v["style"])
    direct, short = adoption(v)
    sh_cells = []
    for sh, rows in short.items():
        n = total(rows)
        sh_cells.append(f'<code>{sh}</code> &middot; {n}' if n
                        else f'<code>{sh}</code> <i class="warnv">unused</i>')
        if not n:
            b_dead.append(sh)
    b_adopt_rows.append([
        tk(v["style"]),
        us(f'{total(direct)}'),
        us("<br>".join(sh_cells) if sh_cells else '<span class="gap">none defined</span>'),
        f'<td class="us">{sitelist(direct, f"{len(direct)} files") or "&mdash;"}</td>',
    ])

# The literals every style repeats. Derived from the parse, so the table can't claim a
# number the source has stopped using.
lit_rows, lits = [], {}
for v in BSTYLES:
    for label, val, why in [
        ("pressed fill opacity", v["pressed"], "no <code>HHSizing</code> token for it"),
        ("pressed scale", v["scale"], "not a token family"),
        ("press animation", v["anim"], "not a token family"),
        ("padding", (v["pad_v"] or {}).get("v") if not (v["pad_v"] or {}).get("tok") else None,
         "<code>HHSpacing.space1_5</code> is the same 6pt"),
        ("min height", (v["min_h"] or {}).get("v") if v["min_h"] and not v["min_h"]["tok"] else None,
         "<code>HHSizing.buttonHeightS</code> is 40pt; 38 is not a token"),
        ("corner radius", (v["radius"] or {}).get("v") if v["radius"] and not v["radius"]["tok"] else None,
         "<code>HHRadius</code> has no 14"),
        ("spinner gap", v["spinner_gap"], "<code>HHSpacing.space2</code> is the same 8pt"),
        ("minimum scale factor", v["min_scale"], "typography, not geometry"),
    ]:
        if val is None:
            continue
        lits.setdefault((label, val, why), []).append(bname(v))
for (label, val, why), users in lits.items():
    lit_rows.append([tk(f"{val:g}", label), us(", ".join(users)), us(why)])
lit_rows.append([tk(", ".join(sorted({v["font"] for v in BSTYLES})), "type"),
                 us("every style"),
                 us("Apple text styles, not <code>HHFont</code> &mdash; the button label is the "
                    "one piece of type in the app that does not come from the type ramp")])

pb_styles = (
    f'<h2>The shared styles<span class="ct">{BVARIANTS} across {BTYPES} types</span></h2>'
    '<p class="lede sub">Every state below is rendered from the values parsed out of '
    f'<code>Styles/ButtonStyles/</code>. A state that is missing from a row is missing from '
    'the style: two capsule styles have no disabled treatment, and the outline style has no '
    'loading treatment.</p>'
    + "".join(
        f'<section class="comp"><div class="comp-h"><b>{bname(v)}</b>'
        f'<code>{v["fill_tok"] or html.escape(v["fill"])}</code> &middot; <code>{v["fg"]}</code></div>'
        + two_up(bstates(v)) + '</section>' for v in BSTYLES)
    + '<h2>Geometry</h2>'
    '<p class="lede sub">The height a call site actually gets is the frame plus the padding '
    'outside it, which is why a 38pt minimum reads as a 50pt control.</p>'
    + ttable([("Style", "22%"), ("Width", "10%"), ("Shape", "18%"), ("Height", "20%"),
              ("Type", "16%"), ("Colour", "14%")], b_specs)
    + '<h2>States</h2>'
    + ttable([("Style", "22%"), ("Pressed", "22%"), ("Disabled", "18%"),
              ("Loading", "26%"), ("Shadow", "12%")], b_state_rows)
    + '<h2>Adoption</h2>'
    '<p class="lede sub">Direct initialiser versus the <code>.heidi&hellip;</code> shorthand. '
    'Both spellings are live, and only three of the six types have a shorthand at all.</p>'
    + ttable([("Style", "26%"), ("Direct", "10%"), ("Shorthand", "26%"), ("Where", "38%")],
             b_adopt_rows)
    + '<h2>Values that are not tokens</h2>'
    '<p class="lede sub">Repeated literals, and the token that already holds the same '
    'value where one exists.</p>'
    + ttable([("Value", "20%"), ("Styles", "44%"), ("Note", "36%")], lit_rows))


# ------------------------------------------------------ tab 2 — built by hand
# Curated, because "this is a button wearing a Circle" is a judgement no regex makes. The
# anchor is not curated: it has to match its file exactly once, so the line number is
# always current and a control that is renamed or deleted breaks the build.
bad_anchors = []


def anchor_line(path, anchor):
    txt = SRC.get(path, WIDGET_SRC.get(path.replace("HeidiNativeWidgets/", "")))
    if txt is None:
        bad_anchors.append(f"{path}: no such file")
        return 0
    hits = [i for i, ln in enumerate(txt.splitlines(), 1) if re.search(anchor, ln)]
    if len(hits) != 1:
        bad_anchors.append(f"{path}: {anchor!r} matched {len(hits)}x {hits[:6]}")
        return hits[0] if hits else 0
    return hits[0]


# (control, path, anchor, chrome, states, values that are not tokens)
BESPOKE = [
    ("Recording", [
        ("Record / stop orb", "App/Features/Session/HHSessionView.swift",
         r"private func volumeIndicator\(",
         "100pt <code>Circle</code> with the state icon knocked out of the fill; "
         "<code>.onTapGesture</code>, not a <code>Button</code>",
         "ready &middot; recording &middot; paused &middot; stopped; dimmed to "
         "<code>opacityDisabled</code> while a lifecycle transition is in flight",
         "100 circle, 46 / 36 icon, 0.5s duplicate-tap throttle"),
        ("Resume overlay", "App/Features/Session/HHSessionView.swift",
         r"lastResumeTapTime = now",
         "second 100pt circle, stroked, sliding out from under the orb; tap gesture",
         "shown only while <code>showingResumeOption</code>; hit-testing gated separately "
         "from visibility", "100 circle, 46 icon, &plusmn;70 offset"),
        ("Pause control", "App/Features/Session/HHSessionView.swift",
         r"private func pauseControl\(",
         "<code>Button</code>, rounded rectangle, hand-built shadow",
         "hidden but still laid out when not recording; disabled with the orb",
         "radius 12, width 120, shadow <code>.black.opacity(0.05) r1 y1</code>"),
        ("File-upload orb", "App/Features/Session/HHSessionView.swift",
         r"private func fileUploadButton\(",
         "100pt filled <code>Circle</code>, icon knocked out; tap gesture with "
         "<code>.isButton</code> added by hand", "single state",
         "100 circle, 46 icon"),
        ("Session settings", "App/Features/Session/HHSessionView.swift",
         r"private func sessionSettingsButton\(",
         "<code>BackgroundPlatter</code> chrome, <code>@ScaledMetric</code> 44 height",
         "none", "<code>Color.primary</code> tint"),
        ("Dictation cleanup mode", "App/Features/Session/HHSessionView.swift",
         r"private func dictationCleanupModeButton\(",
         "a <code>Menu</code> dressed as the settings button above",
         "none", "chevron at <code>size: 12</code>"),
        ("Session dismiss", "App/Features/Session/HHSessionDismissButton.swift",
         r"struct HHSessionDismissButton",
         "bare chevron <code>Image</code> in the toolbar &mdash; no frame, no background",
         "none", "&mdash;"),
        ("Patient name / rename", "App/Features/Session/HHPatientTitleView.swift",
         r"struct HHPatientTitleView", "<code>Button</code>, <code>.plain</code>",
         "titled &middot; untitled", "<code>@ScaledMetric</code> pencil size"),
        ("Voice dictation mic", "Common/VoiceDictation/VoiceDictationButton.swift",
         r"struct VoiceDictationButton",
         "40pt rounded square, hairline border, no shared style",
         "idle &middot; recording &middot; transcribing (spinner, disabled)",
         "icon 16, border 1"),
    ]),
    ("Evidence", [
        ("Submit / stop", "App/Features/Evidence/EvidenceView.swift",
         r"let isPrimaryActionActive = isAwaitingResponse",
         "one <code>Button</code> doing two jobs, fill swaps with intent",
         "submit &middot; stop &middot; disabled", "icon <code>size: 16</code>"),
        ("Attachment add", "App/Features/Evidence/EvidenceView.swift",
         r"private struct EvidenceAttachmentAddButton",
         "40pt square, <code>fillSecondary</code>, <code>HHRadius.lg</code>", "none",
         "icon <code>size: 18</code>"),
        ("Shortcuts", "App/Features/Evidence/EvidenceView.swift",
         r"private struct EvidenceShortcutsButton", "same chrome as the add button",
         "disabled dims the label", "<code>opacity(0.4)</code> rather than the token"),
        ("Sources", "App/Features/Evidence/EvidenceView.swift",
         r"private struct EvidenceSourcesButton", "same chrome, icon + label", "none",
         "&mdash;"),
        ("Collapsed input pill", "App/Features/Evidence/EvidenceView.swift",
         r"private var collapsedPill",
         "whole pill re-expands the composer; <code>.onTapGesture</code> with "
         "<code>.isButton</code>, wrapping a real stop <code>Button</code>",
         "awaiting response &middot; idle", "toolbar button size 40, icon 16"),
        ("Chat history / new chat", "App/Features/Evidence/EvidenceView.swift",
         r"private func chatHistoryButton\(", "toolbar icons, no style, no frame", "none",
         "<code>Layout.iconFontMedium = 16</code>"),
        ("Scroll to latest", "App/Features/Evidence/Components/EvidenceScrollToLatestButton.swift",
         r"struct EvidenceScrollToLatestButton",
         "40pt visual, <code>minTapTarget</code> hit area &mdash; deliberately different sizes",
         "none", "<code>shadowOpacity 0.14</code>"),
        ("Response footer (thumbs, copy, share)",
         "App/Features/Evidence/Components/EvidenceResponseFooterView.swift",
         r"struct EvidenceResponseFooterView", "44pt icon buttons, <code>.plain</code>",
         "thumb selected swaps the glyph and the foreground role", "tap target 44"),
        ("Citation pill", "App/Features/Evidence/Components/CitationAttachment.swift",
         r"struct CitationAttachment: Attachment",
         "<code>RoundedRectangle</code> at <code>HHRadius.md</code>, no border; not a "
         "<code>Button</code> at all &mdash; taps arrive as <code>citation://N</code> links",
         "web &middot; user document &middot; +N count",
         "<code>caption</code> 12, icon 12, radius 8"),
        ("Mini player", "App/Features/Evidence/Components/EvidenceMiniPlayerBar.swift",
         r"struct EvidenceMiniPlayerBar", "<code>Capsule</code> specced in Figma pixels",
         "live volume bars", "83 &times; 25, bars 8 / 12 / 3 / 2"),
        ("Image attachment remove",
         "App/Features/Evidence/Components/EvidenceAttachmentChip.swift",
         r"struct EvidenceImageAttachmentChip", "circular badge over the thumbnail",
         "uploading overlay", "88 tile, 22 badge, 10 glyph"),
        ("Inline CTA — <heidi-button>",
         "App/Features/Evidence/Components/HeidiCtaButtonView.swift",
         r"struct HeidiCtaButtonView",
         "the shared fit-content secondary style &mdash; the one bespoke-looking control "
         "that is not bespoke", "inherits the style's states", "&mdash;"),
    ]),
    ("Work chat", [
        ("Send", "Interfaces/WorkChat/WorkChatComposer.swift", r"private var sendButton",
         "40pt square, fill swaps on enablement", "enabled &middot; disabled", "&mdash;"),
        ("Collapsed composer pill", "Interfaces/WorkChat/WorkChatComposer.swift",
         r"private var collapsedPill",
         "tap gesture with <code>.isButton</code>; a copy of Evidence's, deliberately "
         "not shared", "editable &middot; locked", "editor max height 250"),
        ("Toolbar / slash / sources stubs", "Interfaces/WorkChat/WorkChatComposer.swift",
         r"private struct WorkChatComposerToolbarButton",
         "three buttons wired to an empty closure &mdash; visible chrome only",
         "permanently disabled at <code>opacityDisabled</code>", "&mdash;"),
        ("Scroll to latest", "Interfaces/WorkChat/WorkChatScrollToLatestButton.swift",
         r"struct WorkChatScrollToLatestButton",
         "twin of the Evidence one, plus an unread badge",
         "new content &middot; action needed", "<code>shadowOpacity 0.14</code>"),
        ("Approve / deny", "Interfaces/WorkChat/ResolutionBar.swift", r"struct ResolutionBar",
         "filled pill for the affirmative verdict, ghost text for deny",
         "pending &middot; resolving &middot; resolved", "&mdash;"),
        ("Clarification option row", "Interfaces/WorkChat/WorkChatClarificationCard.swift",
         r"private func optionRow", "selectable row, badge + fill swap",
         "selected &middot; multi-select checkbox", "&mdash;"),
    ]),
    ("Sessions, home and templates", [
        ("Start session", "App/Features/SessionsList/StartSessionButton.swift",
         r"struct StartSessionButton",
         "system <code>.borderedProminent</code> with a Heidi tint painted on",
         "system pressed only", "<code>minHeight: 34</code>"),
        ("Compact session FAB", "App/Features/SessionsList/HHSessionListView.swift",
         r"private struct CompactSessionFAB",
         "circular FAB, fully tokenised", "none",
         "<i class=\"warnv\">no call sites &mdash; kept for a future tab bar</i>"),
        ("Session row", "App/Features/SessionsList/HHSessionRowView.swift",
         r"struct HHSessionRowView: View",
         "row is a shape with <code>contentShape</code>; the caller attaches the tap",
         "avatar tap links a patient, error glyph retries the upload",
         "icon 20 &times; 20"),
        ("Appointment row", "App/Features/SessionsList/HHAppointmentRowView.swift",
         r"struct HHAppointmentRowView", "row tap gesture",
         "in-flight swaps in a bare <code>ProgressView</code>", "vertical padding 4"),
        ("Sync status actions", "App/Features/SessionsList/HHSyncStatusView.swift",
         r"private func successView\(",
         "two inline buttons that a comment says match each other",
         "success &middot; error",
         "they do not match: <code>space2/space1/sm</code> against "
         "<code>space4/space2/md</code>"),
        ("Search close", "App/Features/SessionsList/HHSessionSearchView.swift",
         r"private var closeButton",
         "56pt circle on the shared <code>promptGlassBackground</code> material", "none",
         "&mdash;"),
        ("Home header cluster", "Interfaces/Home/HomeHeaderView.swift",
         r"private var actionsPill",
         "capsule and circles on the glass material", "none", "&mdash;"),
        ("Template button", "App/Features/TemplateButton/HHTemplateButtonView.swift",
         r"struct HHTemplateButtonView",
         "<code>BackgroundPlatter</code> chrome; two near-identical private builders",
         "loading spinner in one builder only",
         "spacing 6, icons 18 / 12, insets 10 / 16, height 44"),
        ("Background platter", "Interfaces/Shared/BackgroundPlatter.swift",
         r"struct BackgroundPlatter",
         "the shared chrome under the template and settings buttons", "none",
         "default radius 12, border 1"),
    ]),
    ("Settings and account", [
        ("Settings rows", "Interfaces/SettingsView/SettingsView.swift",
         r"SettingsInteractiveRow\(\.microphone\)",
         "every row hand-wraps its own <code>Button</code> + <code>.plain</code> around "
         "<code>SettingsRow</code>", "selection via a trailing checkmark", "&mdash;"),
        ("Chronicle device row", "Interfaces/SettingsView/SettingsView.swift",
         r"private var chronicleSettingsRow",
         "the one settings row built on <code>.onTapGesture</code> instead of a "
         "<code>Button</code>", "status icon", "&mdash;"),
        ("Delete account", "Interfaces/SettingsView/SettingsView.swift",
         r"legacySettingsDeleteAccount\)",
         "destructive by foreground colour only &mdash; no <code>role</code>", "none",
         "&mdash;"),
        ("Log out / log out everywhere", "Interfaces/SettingsView/SettingsView.swift",
         r"if viewModel\.loadingSignOut \{",
         "<code>Button(role: .destructive)</code>, label swaps for a spinner",
         "loading", "<code>.tint(.gray)</code>"),
        ("Delete account confirm", "Interfaces/AccountDeleteView/AccountDeleteView.swift",
         r"Button\(action: viewModel\.confirmDeleteAccount\)",
         "row-background colour carries the destructive intent, not the button",
         "invalid &middot; valid &middot; loading", "<code>.tint(.gray)</code> spinner"),
        ("Toggle", "Common/Components/HeidiToggle.swift", r"struct HeidiToggle",
         "a <code>UISwitch</code> in a <code>UIViewRepresentable</code>, tinted with "
         "<code>fillAccent</code>",
         "the label row carries a second, hidden tap surface over the switch", "&mdash;"),
        ("Workspace row", "App/Features/WorkspacePicker/WorkspacePickerView.swift",
         r"private func workspaceRow", "row button, <code>.plain</code>",
         "selected shows a checkmark rather than a fill", "&mdash;"),
    ]),
    ("Auth and onboarding", [
        ("Continue with email / social", "App/Features/UnifiedLogin/UnifiedLoginView.swift",
         r"private func socialButton",
         "shared primary and secondary styles &mdash; the best-behaved screen in the app",
         "loading &middot; disabled", "<code>\"apple.logo\"</code> as a string literal"),
        ("Sign in (signed-out state)",
         "Interfaces/SignedOutZeroState/SignedOutZeroState.swift",
         r"struct SignedOutZeroState",
         "<code>BorderedProminentButtonStyle()</code> &mdash; the same system style as "
         "<code>.borderedProminent</code>, spelled differently", "system", "&mdash;"),
        ("Specialty retry", "Interfaces/RegionSetupView/RegionSetupView.swift",
         r"private var specialtySection", "three states rendered as three different rows",
         "loading &middot; error retry &middot; normal",
         "<code>\"arrow.clockwise\"</code> as a string literal"),
        ("Connect later",
         "App/Features/ChronicleSettings/ChronicleBluetoothPermissionSheet.swift",
         r"struct ChronicleBluetoothPermissionSheet",
         "ghost text button under a shared primary &mdash; no style, just a tap target",
         "none", "<code>minHeight: 44</code>"),
        ("Carousel call to action", "Interfaces/OnboardingCarousel/OnboardingCarousel.swift",
         r"struct OnboardingCarousel", "shared primary style; label changes per page",
         "&mdash;", "&mdash;"),
    ]),
    ("Chrome, widgets and UIKit", [
        ("Close toolbar item", "Interfaces/Shared/CloseToolbarItem.swift",
         r"struct CloseToolbarItem",
         "the closest thing to a shared dismiss: <code>role: .close</code> on iOS 26, "
         "<code>role: .cancel</code> + xmark below", "none", "&mdash;"),
        ("Circle dismiss", "Interfaces/Shared/DismissButton.swift",
         r"struct CircleDismissButton", "40pt filled circle with a chevron",
         "none", "<i class=\"warnv\">no call sites</i>; 40, 18"),
        ("Upload status indicator", "Interfaces/Shared/UploadStatusIndicator.swift",
         r"struct UploadStatusIndicator", "icon with a tap gesture", "needs upload &middot; failed",
         "<i class=\"warnv\">no call sites</i>; icon 24"),
        ("Dial pad key", "Common/Components/PhoneDialPad.swift",
         r"private struct PhoneDialPadKeyButtonStyle",
         "the only <code>ButtonStyle</code> outside the folder, private to one view",
         "disabled only &mdash; <i class=\"warnv\">no pressed state at all</i>", "&mdash;"),
        ("Live Activity transport", "HeidiNativeWidgets/Views/RecordingViews.swift",
         r"struct RecordingButtonsView",
         "<code>Button(intent:)</code> App Intents &mdash; pause, resume, end",
         "compact variant for the Dynamic Island", "height 32 / 44"),
        ("Toast action", "Interfaces/ToastHost/ToastView.swift", r"class ToastView",
         "UIKit <code>UIButton</code> plus a tap recogniser on the whole card",
         "four toast styles recolour the title",
         "insets 16 / 12, icon 16, shadow 0.2 / 10, <code>.white</code> title"),
        ("QR scanner cancel",
         "Interfaces/CibaEnrollmentView/CibaQRCodeScannerView.swift",
         r"let button = UIButton\(type: \.system\)",
         "UIKit <code>UIButton</code> over the camera preview", "none",
         "<code>black.withAlphaComponent(0.5)</code>, radius 8, height 44, width &ge; 88"),
    ]),
]

bes_rows = []
for group, items in BESPOKE:
    bes_rows.append([f'<td class="bgroup" colspan="4">{group}</td>'])
    for name, path, anchor, chrome, states, raw in items:
        ln = anchor_line(path, anchor)
        bes_rows.append([
            tk(name, f'<code>{html.escape(path.split("/")[-1])}:{ln}</code>'),
            us(chrome), us(states), us(raw),
        ])
assert not bad_anchors, "bespoke anchors:\n  " + "\n  ".join(bad_anchors)
BESPOKE_N = sum(len(i) for _, i in BESPOKE)

pb_bespoke = (
    f'<h2>Built by hand<span class="ct">{BESPOKE_N}</span></h2>'
    '<p class="lede sub">Controls that carry their own chrome instead of a shared style. '
    'Line numbers are resolved at build time from a symbol that has to still exist, so '
    'this table cannot drift from the source it describes.</p>'
    + ttable([("Control", "26%"), ("Chrome", "30%"), ("States", "24%"),
              ("Not tokens", "20%")], bes_rows))


# ---------------------------------------------------------- tab 3 — bypasses
BTN_RE = r"\bButton\s*[({]"
n_buttons = total(sweep(BTN_RE))
n_styled = total(sweep(r"\.buttonStyle\("))
heidi_applied = total(sweep(r"\.buttonStyle\(\s*(?:Heidi\w+|\.heidi\w+)"))

SYSTEM_STYLES = [
    (".plain", r"\.buttonStyle\(\s*(?:\.plain\b|PlainButtonStyle\()",
     "no chrome at all &mdash; the label is the button"),
    (".borderedProminent", r"\.buttonStyle\(\s*(?:\.borderedProminent\b|BorderedProminentButtonStyle\()",
     "Apple's filled button, tinted per call site"),
    (".bordered", r"\.buttonStyle\(\s*\.bordered\b(?!P)", "Apple's tinted button"),
    (".borderless", r"\.buttonStyle\(\s*\.borderless\b", "Apple's text button"),
]
sys_rows = []
for label, pat, note in SYSTEM_STYLES:
    hits = sweep(pat)
    sys_rows.append([
        tk(label), us(f"{total(hits)}"), us(note),
        f'<td class="us">{sitelist(hits, plural(len(hits), "file")) or "&mdash;"}</td>'])

CHROME = [
    ("CloseToolbarItem", "Interfaces/Shared/CloseToolbarItem.swift", r"CloseToolbarItem\s*[({]",
     "version-branched toolbar close &mdash; the intended one"),
    ("HHSessionDismissButton", "App/Features/Session/HHSessionDismissButton.swift",
     r"HHSessionDismissButton\s*[({]", "bare chevron for the session sheet"),
    ("CircleDismissButton", "Interfaces/Shared/DismissButton.swift", r"CircleDismissButton\s*[({]",
     "filled circle chevron"),
]
chrome_rows = []
for name, home, pat, note in CHROME:
    rows = [r for r in sweep(pat) if r[0] != home]
    n = total(rows)
    chrome_rows.append([
        tk(name, f'<code>{html.escape(home)}</code>'),
        us(f"{n}" if n else '<i class="warnv">unused</i>'), us(note),
        f'<td class="us">{sitelist(rows, plural(len(rows), "file")) or "&mdash;"}</td>'])
xmark = sweep(r'SFSymbols\.xmark\b|systemName: "xmark"')
back = sweep(r'systemName: "chevron\.left"|SFSymbols\.chevronBackward')
chrome_rows.append([tk("hand-rolled xmark", "no shared component"), us(f"{total(xmark)}"),
                    us("close glyphs built inline, each with its own frame and colour"),
                    f'<td class="us">{sitelist(xmark, f"{len(xmark)} files")}</td>'])
chrome_rows.append([tk("hand-rolled back chevron", "no shared component"), us(f"{total(back)}"),
                    us("two screens replace the system back button with their own"),
                    f'<td class="us">{sitelist(back, f"{len(back)} files")}</td>'])

ROLES = [
    ("Button(role: .destructive)", r"Button\([^)]*role: \.destructive"),
    ("Button(role: .cancel)", r"Button\([^)]*role: \.cancel"),
    ("Button(role: .close)", r"Button\([^)]*role: \.close"),
    ("ButtonState(role: .destructive)", r"ButtonState\([^)]*role: \.destructive"),
    ("ButtonState(role: .cancel)", r"ButtonState\([^)]*role: \.cancel"),
]
role_rows = []
for label, pat in ROLES:
    rows = sweep(pat)
    role_rows.append([tk(label), us(str(total(rows))),
                      f'<td class="us">{sitelist(rows, plural(len(rows), "file"))}</td>'])

taps = sweep(r"\.onTapGesture\b")
taps_isbutton = [r for r in taps if "accessibilityAddTraits(.isButton)" in SRC[r[0]]]
NOT_BUTTON = [
    (".onTapGesture", taps,
     f"tap on a shape. {len(taps_isbutton)} of the {len(taps)} files also add "
     "<code>.isButton</code> to the accessibility traits, which is the code admitting "
     "what the control is"),
    ("Menu", sweep(r"\bMenu\s*[({]"), "a button that opens a list of buttons"),
    ("Picker", sweep(r"\bPicker\("), "segmented and menu pickers"),
    ("Link / ShareLink", sweep(r"\b(?:Share)?Link\("),
     "buttons that leave the app"),
    ("UIButton", sweep(r"\bUIButton\b"), "UIKit, outside every SwiftUI style"),
    ("UIBarButtonItem", sweep(r"\bUIBarButtonItem\b"),
     "UIKit toolbars in the note editor, Quick Look and the web view"),
    ("Button(intent:)", sweep(r"Button\(intent:", src=WIDGET_SRC),
     "widget and Live Activity transport controls (HeidiNativeWidgets)"),
]
nb_rows = [[tk(label), us(f"{total(rows)}"), us(note),
            f'<td class="us">{sitelist(rows, plural(len(rows), "file")) or "&mdash;"}</td>']
           for label, rows, note in NOT_BUTTON]

# The local packages are in the sweep's blind spot unless someone checks, so check.
for _pkg in ("Quill/Sources", "Packages"):
    _hits = [p for p in (ROOT / _pkg).rglob("*.swift")
             if re.search(r"\bButton\s*[({]|ButtonStyle", p.read_text(errors="replace"))]
    assert not _hits, f"{_pkg} now defines buttons: {_hits}"

pb_bypass = (
    f'<h2>System styles<span class="ct">{total(sweep(r"|".join(p for _, p, _ in SYSTEM_STYLES)))}</span></h2>'
    '<p class="lede sub">Apple\'s own button styles, applied directly. '
    '<code>.plain</code> is usually deliberate: it strips chrome from a row or a '
    'card that is doing its own drawing. The bordered family is not: it puts Apple\'s '
    'button on a Heidi screen.</p>'
    + ttable([("Style", "18%"), ("Count", "10%"), ("What it is", "36%"),
              ("Where", "36%")], sys_rows)
    + '<h2>Dismiss and back</h2>'
    '<p class="lede sub">Five ways to close a screen, one of which is used nowhere.</p>'
    + ttable([("Implementation", "24%"), ("Uses", "8%"), ("What it is", "34%"),
              ("Where", "34%")], chrome_rows)
    + '<h2>Roles</h2>'
    '<p class="lede sub">Destructive and cancel intent, declared twice over: in SwiftUI '
    'at the call site, and in TCA <code>ButtonState</code> inside a reducer.</p>'
    + ttable([("Spelling", "34%"), ("Count", "10%"), ("Where", "56%")], role_rows)
    + f'<h2>Not a Button<span class="ct">{total(taps)} tap gestures</span></h2>'
    '<p class="lede sub">Controls a sweep for <code>Button</code> would miss entirely. '
    'The record orb, the file-upload orb and around twenty tap-to-edit rows live here.</p>'
    + ttable([("Construct", "24%"), ("Count", "10%"), ("What it is", "32%"),
              ("Where", "34%")], nb_rows))


# ---------------------------------------------------------- tab 4 — coverage
def area(path):
    p = path.split("/")
    if len(p) == 1:
        return "(root)"
    if p[0] == "App" and len(p) > 3:
        return "/".join(p[:3])
    return "/".join(p[:2]) if len(p) > 2 else p[0]


STYLE_BADGE = {b["style"]: b["style"].replace("Heidi", "").replace("ButtonStyle", "")
               for b in BSTYLES}
cov = {}
for path, txt in SRC.items():
    nb, nt = len(re.findall(BTN_RE, txt)), len(re.findall(r"\.onTapGesture\b", txt))
    if not (nb or nt) or path.startswith("Styles/ButtonStyles/"):
        continue
    used = [short for full, short in sorted(STYLE_BADGE.items())
            if re.search(r"\.buttonStyle\(\s*" + full, txt)]
    used += [sh for sh in sorted({s for b in BSTYLES for s in b["shorthands"]})
             if re.search(r"\.buttonStyle\(\s*" + re.escape(sh.split("(")[0]) + r"\b", txt)]
    sysd = [label for label, pat, _ in SYSTEM_STYLES if re.search(pat, txt)]
    cov.setdefault(area(path), []).append((path, nb, nt, used, sysd))

cov_rows = []
for a in sorted(cov, key=lambda k: (-sum(f[1] + f[2] for f in cov[k]), k)):
    files = sorted(cov[a], key=lambda f: (-(f[1] + f[2]), f[0]))
    nb, nt = sum(f[1] for f in files), sum(f[2] for f in files)
    cov_rows.append([f'<td class="bgroup" colspan="4">{html.escape(a)} '
                     f'<span class="gap">&middot; {plural(nb, "button")}, '
                     f'{plural(nt, "tap")}, {plural(len(files), "file")}</span></td>'])
    for path, b, t, used, sysd in files:
        badges = ", ".join(f"<code>{u}</code>" for u in used) or ""
        sysb = ", ".join(f'<code>{s}</code>' for s in sysd)
        cov_rows.append([
            tk(path.split("/")[-1], html.escape("/".join(path.split("/")[:-1]))),
            us(str(b) if b else '<span class="gap">0</span>'),
            us(str(t) if t else '<span class="gap">0</span>'),
            us(" &middot; ".join(x for x in (badges, sysb) if x)
               or '<span class="gap">no style applied</span>')])

cov_files = sum(len(v) for v in cov.values())
pb_cover = (
    f'<h2>Every file with a button<span class="ct">{cov_files}</span></h2>'
    '<p class="lede sub">The whole surface, nothing collapsed: each file that constructs a '
    '<code>Button</code> or attaches a tap gesture, and which styles it reaches for. '
    '<code>no style applied</code> means the buttons in that file take whatever their '
    'context gives them.</p>'
    + ttable([("File", "40%"), ("Buttons", "10%"), ("Taps", "10%"), ("Styles used", "40%")],
             cov_rows))


# ------------------------------------------------------------------ assembly
BTN_TABS = [("styles", "Shared styles", pb_styles), ("bespoke", "Built by hand", pb_bespoke),
            ("bypass", "Bypasses", pb_bypass), ("coverage", "Coverage", pb_cover)]

pbtn = (audit_note(
            f'{n_buttons} button constructions across {cov_files} files: {BTYPES} shared '
            f'styles against {BESPOKE_N} built by hand.')
        + '<div class="ptabs" role="tablist">' + "".join(
            f'<a href="#{s}" id="tab-{s}" role="tab">{l}</a>' for s, l, _ in BTN_TABS)
        + "</div>"
        + "".join(f'<section class="tabpanel" id="panel-{s}">{b}</section>'
                  for s, _, b in BTN_TABS)
        + '<script>'
        'const BL=["' + '","'.join(s for s, _, _ in BTN_TABS) + '"];'
        'function bshow(s){if(!BL.includes(s))s=BL[0];'
        'BL.forEach(x=>{const p=document.getElementById("panel-"+x),t=document.getElementById("tab-"+x);'
        'p.hidden=x!==s;t.setAttribute("aria-selected",x===s);'
        'const sb=document.querySelector(`.side .sub a[href$="#${x}"]`);'
        'if(sb)sb.classList.toggle("on",x===s);});}'
        'bshow(location.hash.slice(1));'
        'addEventListener("hashchange",()=>bshow(location.hash.slice(1)));'
        '</script>')

BUTTONS_LEDE = (
    f'{n_buttons} buttons across the shipped app, {heidi_applied} of them wearing one of '
    f'the {BTYPES} shared styles. Below: the styles, the controls that go their own way, '
    'and the ones that are not buttons at all.')

# systemGroupedBackground is a UIKit colour one capsule style still fills with; the page
# has to render it, so it gets the two iOS values rather than a Heidi token.
BUTTONS_CSS = ".light{--uiSystemGrouped:#F2F2F7}.dark{--uiSystemGrouped:#000000}"

# (href, title, lede, content) — order here is the order they get written.
# ----------------------------------------------------------- page: motion
# There is no motion token — no HHMotion enum, no shared curve. Durations are literals at
# the call site. So this page is an inventory like Buttons: it reports the spread rather
# than prescribing a scale, and the numbers move on their own as the app changes.
CURVE_RE = (r"\.(easeInOut|easeIn|easeOut|linear|spring|snappy|bouncy|smooth|"
            r"interpolatingSpring|timingCurve)\(")
# `duration:` and the older `response:` both set the length of a SwiftUI animation.
MOTION_RE = CURVE_RE + r"[^)]*?(?:duration|response): *([0-9]*\.?[0-9]+)"


def motion_hits():
    """[(curve, seconds, path, line)] for every literal-timed animation that ships."""
    out = []
    for path, txt in sorted(SRC.items()):
        for i, ln in enumerate(txt.splitlines(), 1):
            for curve, secs in re.findall(MOTION_RE, ln):
                out.append((curve, float(secs), path, i))
    return out


MOTION = motion_hits()
# A duration is only a candidate token if more than one place reached for it.
MOTION_BY_SECS = {}
for _c, _s, _p, _l in MOTION:
    MOTION_BY_SECS.setdefault(_s, []).append((_c, _p, _l))
MOTION_BY_CURVE = {}
for _c, _s, _p, _l in MOTION:
    MOTION_BY_CURVE.setdefault(_c, []).append(_s)

# Durations named at the call site instead of inlined — the closest thing to a token the
# app has, and the point is that each one is local to a single feature.
NAMED_RE = r"static (?:let|var) (\w*(?:[Dd]uration|[Dd]elay))\w* *[:=]"
named_rows = sweep(NAMED_RE)

_reduce = sweep(r"reduceMotion")
_anim = sweep(r"withAnimation\(|\.animation\(")

pm = (
    audit_note(
        'There is no motion token yet. Every duration below is a literal at its call '
        'site, swept from source.')
    + f'<h2>Durations<span class="ct">{len(MOTION_BY_SECS)} distinct</span></h2>'
    '<p class="lede sub">Sorted by how often each appears. A duration used once is a '
    'one-off; the ones at the top are the de facto scale.</p>'
    + ttable([("Seconds", "16%"), ("Uses", "12%"), ("Curves", "34%"), ("Where", "38%")],
             [[f'<td class="tk"><span class="tok" title="Copy">{secs:g}s</span></td>',
               f'<td>{len(hits)}</td>',
               us(", ".join(f"`{c}`" for c in sorted({h[0] for h in hits}))),
               f'<td class="us">{sitelist([(p, [l for _, pp, l in hits if pp == p], 1) for p in sorted({h[1] for h in hits})], plural(len({h[1] for h in hits}), "file")) or "&mdash;"}</td>']
              for secs, hits in sorted(MOTION_BY_SECS.items(),
                                       key=lambda kv: (-len(kv[1]), kv[0]))])
    + f'<h2>Curves<span class="ct">{len(MOTION_BY_CURVE)}</span></h2>'
    '<p class="lede sub">Which easing the app reaches for, and the range of speeds it is '
    'asked to run at.</p>'
    + ttable([("Curve", "26%"), ("Uses", "14%"), ("Range", "26%"), ("Distinct durations", "34%")],
             [[f'<td class="tk"><span class="tok" title="Copy">.{curve}</span></td>', f'<td>{len(secs)}</td>',
               us(f"{min(secs):g}s &ndash; {max(secs):g}s" if min(secs) != max(secs)
                  else f"{min(secs):g}s"),
               us(", ".join(f"{s:g}s" for s in sorted(set(secs))))]
              for curve, secs in sorted(MOTION_BY_CURVE.items(),
                                        key=lambda kv: -len(kv[1]))])
    + f'<h2>Named durations<span class="ct">{total(named_rows)}</span></h2>'
    '<p class="lede sub">Timings given a name rather than inlined. Each is scoped to one '
    'feature, so two screens can hold different values under the same intent.</p>'
    + (sitelist(named_rows, plural(total(named_rows), "constant") + " in "
                + plural(len(named_rows), "file")) or "&mdash;")
    + '<h2>Reduce Motion</h2>'
    f'<p class="lede sub">{total(_reduce)} of the app&rsquo;s {total(_anim)} animation '
    'call sites check the accessibility setting before animating.</p>'
    + (sitelist(_reduce) or "&mdash;"))



# ------------------------------------------------------------- page: welcome
# Counts are generated, so the landing page can't drift from the pages it summarises.
INVENTORY = [
    # Fifth field is the Lucide glyph that leads the row. Chosen for what the foundation
    # *is*, not for its page: swatches for the ramps, a corner for radius, a curve for the
    # easing on Motion. Keyed by name, not by source file — HHSpacing.swift backs both
    # Spacing and Sizing, so a file-keyed lookup would give them the same icon.
    ("colors.html#primitives", "Primitives",
     f"{sum(len(v) for v in ramps.values())} stops · {len(ramps)} ramps",
     "HHColorPrimitives.swift", "swatch-book"),
    ("colors.html#semantics", "Semantic colours",
     f"{sum(1 for t in sems if t['section'] in ('Foreground', 'Fill', 'Surface', 'Border'))}"
     " tokens · light/dark pairs", "HHColors.swift", "palette"),
    ("fonts.html", "Type", f"{len(fonts)} tokens · Exposure and Inter", "HHFont.swift", "type"),
    ("spacing.html", "Spacing", f"{len(SPACING)} stops · 0&ndash;64pt", "HHSpacing.swift",
     "between-horizontal-start"),
    ("radius.html", "Radius", f"{len(RADIUS)} radii · 4&ndash;36pt", "HHRadius.swift",
     "square-round-corner"),
    ("sizing.html", "Sizing", f"{len(SIZING)} control, avatar and icon sizes", "HHSpacing.swift",
     "proportions"),
    ("shadows.html", "Shadows", f"{len(shadows)} elevation styles", "View+HeidiShadow.swift",
     "layers"),
    ("motion.html", "Motion", f"{len(MOTION_BY_SECS)} durations &middot; {len(MOTION_BY_CURVE)} curves",
     "no token &mdash; call sites", "activity"),
    ("icons.html", "Icons", f"{len(registered)} Lucide glyphs in use", "CustomIcons.swift",
     "shapes"),
]

# Every glyph above must resolve upstream, or a row silently loses its icon.
for _h, _n, _c, _s, _g in INVENTORY:
    assert lucide_svg(_g), f"{_n}: '{_g}' is not a Lucide {LUCIDE_VERSION} glyph"


# Both cards are hand-rolled because sectionise() only wraps content it finds under an h2,
# and this page's h2s are already inside the cards.
p0 = ('<div class="scard">'
      + '<div class="shead"><h2>Foundations</h2>'
        '<p class="lede sub">Tokens inspired by the web, purpose-built for native.'
        '</p></div>'
      + ttable([("Foundation", "24%"), ("Contents", "34%"), ("Source", "28%"), ("Status", "14%")],
               [[f'<td class="tk"><span class="fico">{lucide_svg(glyph)}</span>'
                 f'<a class="rowlink" href="{href}">{name}</a></td>', us(count),
                 f'<td class="us"><code>{src}</code></td>',
                 f'<td class="stcell">{pstat(href)}</td>']
                for href, name, count, src, glyph in INVENTORY])
      + '</div>'
      + '<div class="scard">'
      + '<div class="shead"><h2>Guiding principles</h2>'
        '<p class="lede sub">The beliefs behind how we work and what we build.</p></div>'
      + "".join(f'<section class="prin">'
                f'<h3>{html.escape(title)}</h3>'
                f'<p>{body}</p></section>'
                for title, body in PRINCIPLES)
      + '</div>'
      # Last thing on the page, no card and no heading: it is the punchline to the
      # principles above it, and a section head would explain the joke.
      + '<figure class="closer"><img src="welcome-closer.jpg" width="1600" height="1031" '
        'loading="lazy" alt="Alec Baldwin in Glengarry Glen Ross at a blackboard reading '
        '&ldquo;A always, B be, C componetising&rdquo;"></figure>')


# ----------------------------------------------------------- page: sheets
# The only page not derived from Swift. Frames are exported from Figma by hand into
# .context/sheets/ and described by frames.json, which also carries the export date — a
# rebuild must not restamp it, or the page would claim to be fresher than it is.
TEXTURE_DIR = ROOT / ".context/textures"
# Grid reads the thumbs; the link hands over the full-size file. Naming is the contract
# between the two, so a texture is one <name>.jpg plus one <name>-thumb.jpg and nothing
# has to be listed anywhere.
TEXTURES = sorted(p.stem for p in TEXTURE_DIR.glob("*.jpg")
                  if not p.stem.endswith("-thumb"))
assert TEXTURES, "no textures in .context/textures"
for _n in TEXTURES:
    assert (TEXTURE_DIR / f"{_n}-thumb.jpg").exists(), f"{_n} has no -thumb.jpg beside it"


# ------------------------------------------------------------- page: assets
def texture_cell(name):
    """One tile: the image and nothing else. The anchor is the download — `download` turns a
    same-origin navigation into a save, so one click gets the full-size file. The name still
    reaches a reader through the title, which is all that names the tile now."""
    return (f'<a class="texcell" href="textures/{name}.jpg" download="hh-{name}.jpg" '
            f'title="Download {name}.jpg">'
            f'<img src="textures/{name}-thumb.jpg" alt="" loading="lazy">'
            f'<span class="texdl"><i>{DL_ICON}</i></span>'
            f'</a>')


PEOPLE_DIR = ROOT / ".context/people"
# This list is the inventory, not the running order — PEOPLE_SHUFFLE_SEED below reorders it,
# so a new tile goes wherever it reads best here and the grid reflows on its own.
# `still` means the source is one image, whatever its format: sources are mirrored into the
# Pages repo, and a 1.3 MB PNG of photographic gradient costs ~5x the JPEG that looks the
# same at this size — the same reason the derivatives below are JPEG.
PEOPLE = [("swing-lift", "Lift", "mp4"), ("swing-behind", "Swing", "mp4"),
          ("check-up", "Check-up", "mp4"), ("on-call", "On call", "mp4"),
          ("lift", "Mid-air", "still"), ("laughing", "Laughing", "still"),
          ("embrace", "Embrace", "still"), ("hands", "Hands", "still"),
          ("seated", "Seated", "still"),
          ("window", "Window", "still"),
          ("reflected", "Reflected", "still"), ("upward", "Upward", "still"),
          ("sunlit", "Sunlit", "still"),
          ("open-sky", "Open sky", "still"), ("at-home", "At home", "still"),
          ("beaming", "Beaming", "still"), ("poised", "Poised", "still"),
          ("consult", "Consult", "still"), ("explaining", "Explaining", "still"),
          ("desk", "Desk", "still"),
          ("listening", "Listening", "still"), ("speaking", "Speaking", "still"),
          ("greeting", "Greeting", "still"),
          ("notes", "Notes", "still"),
          ("vitals", "Vitals", "still"), ("reassure", "Reassure", "still"),
          ("team", "Team", "still"), ("huddle", "Huddle", "still"),
          ("headset", "Headset", "still"), ("intake", "Intake", "still"),
          ("phones", "Phones", "still"), ("front-desk", "Front desk", "still"),
          ("bedside", "Bedside", "still"), ("rounds", "Rounds", "still"),
          ("ward-bed", "Ward", "still"),
          ("attending", "Attending", "still"), ("eye-level", "Eye level", "still"),
          ("bedside-talk", "Bedside talk", "still"),
          ("briefing", "Briefing", "still"), ("handover", "Handover", "still"),
          ("admin", "Admin", "still"),
          ("station", "Station", "still"), ("charting", "Charting", "still"),
          ("operations", "Operations", "mp4")]
STILL_EXT = ("png", "jpg", "jpeg", "webp")

# The grid is shuffled so it reads as a set of people rather than as sorted runs — every clip,
# then the warm frames, then the clinical ones, which is how it had drifted.
#
# Seeded, and sorted before shuffling, for two reasons that both bite silently. An unseeded
# shuffle would reorder the page on every rebuild, so each publish would diff as a rewritten
# grid and no screenshot would ever match the next build. Sorting first makes the order depend
# only on *which* tiles exist, not on where they were typed in the list above — otherwise
# moving a line for readability would quietly reshuffle the whole grid.
#
# The value carries no meaning beyond being the first one that satisfies the constraint below,
# so it is not worth restating here — re-pick it whenever a tile is added and let the assertion
# say whether the new draw is usable.
PEOPLE_SHUFFLE_SEED = 24
PEOPLE = sorted(PEOPLE)
random.Random(PEOPLE_SHUFFLE_SEED).shuffle(PEOPLE)
# Four tiles autoplay. Two touching would put competing motion in one corner of the eye, and
# .pgrid is auto-fill (2–6 columns depending on width), so a gap of 7 is what clears both the
# horizontal and the vertical neighbour at every count a reader can land on.
_pclips = sorted(i for i, (_s, _l, e) in enumerate(PEOPLE) if e == "mp4")
_pgaps = [b - a for a, b in zip(_pclips, _pclips[1:])]
assert all(g >= 7 for g in _pgaps), (
    f"people: clips land {_pgaps} apart at seed {PEOPLE_SHUFFLE_SEED} — re-pick the seed")


def people_source(slug):
    """The dropped-in original for a still, whatever it was named."""
    return next((p for e in STILL_EXT if (p := PEOPLE_DIR / f"{slug}.{e}").exists()), None)
for _s, _l, _e in PEOPLE:
    if _e == "mp4":
        assert (PEOPLE_DIR / f"{_s}.mp4").exists(), f"people asset missing: {_s}.mp4"
        # A clip with no poster is a black rectangle until it decodes, which on a grid of ten
        # reads as a broken tile rather than a loading one.
        assert (PEOPLE_DIR / f"{_s}-poster.jpg").exists(), f"{_s} has no poster"
    else:
        assert people_source(_s), f"people asset missing: {_s}.[{'|'.join(STILL_EXT)}]"
_pnamed = {p.name for s, _l, e in PEOPLE if e != "mp4" and (p := people_source(s))} \
    | {f"{s}.mp4" for s, _l, e in PEOPLE if e == "mp4"} \
    | {f"{s}-poster.jpg" for s, _l, e in PEOPLE if e == "mp4"}
_pstray = sorted(p.name for p in PEOPLE_DIR.glob("*") if p.name not in _pnamed)
assert not _pstray, f"file in .context/people/ is in no tile: {_pstray}"


def person_cell(item):
    """One tile: the frame and nothing else, like a texture. A still is a download; a clip
    is not — it plays where it sits, so it gets no download affordance. The label reaches a
    reader through the title, which is all that names the tile now."""
    slug, label, ext = item
    if ext == "mp4":
        return (f'<div class="texcell pcell" title="{label}">'
                f'<video src="people/{slug}.mp4" poster="people/{slug}-poster.jpg" '
                f'autoplay muted loop playsinline preload="metadata"></video></div>')
    return (f'<a class="texcell pcell" href="people/{slug}.jpg" download="hh-{slug}.jpg" '
            f'title="Download {slug}.jpg">'
            f'<img src="people/{slug}-thumb.jpg" alt="" loading="lazy">'
            f'<span class="texdl"><i>{DL_ICON}</i></span></a>')


# Both sections are h2s, so sectionise() cards them the same way — no hand-rolled wrapper
# here, or Textures would end up double-carded.
# No counts on either heading: a token table's count is the inventory, but a reader
# downloading a backdrop is not checking whether nine of them arrived.
passets = ('<h2>People</h2>'
           + '<p class="lede sub">Care between people, in stills and short clips.</p>'
           # Generated, and the page has to say so where it cannot be missed. A reader who
           # assumes these are photographs will put them in front of clinicians as if they
           # were evidence of real care, and the people in them do not exist. Plain note,
           # not .audit: that tint is the mark for a current-usage inventory, and spending
           # it on a second meaning is how it stops reading as either.
           + '<div class="note"><b>Generated imagery.</b> Not photography &mdash; nobody '
             'in these frames is real. Fine for mood and layout, not for evidence.</div>'
           + '<div class="texgrid pgrid">' + "".join(person_cell(n) for n in PEOPLE)
           + '</div>'
           + '<h2>Textures</h2>'
           + '<p class="lede sub">Warm, out-of-focus light for covers, empty states and '
             'launch screens. Depth behind a headline that never competes with it.</p>'
           + '<div class="texgrid">' + "".join(texture_cell(n) for n in TEXTURES)
           + '</div>')




SHEETS_DIR = ROOT / ".context/sheets"
SHEETS = json.loads((SHEETS_DIR / "frames.json").read_text())
FIG = {f["id"]: f for f in SHEETS["frames"]}
FIG_URL = (f"https://www.figma.com/design/{SHEETS['file_key']}/{SHEETS['file_name']}"
           "?node-id=%s")
# Every frame described must exist, and every PNG present must be described — otherwise a
# renamed export leaves a broken image or a silently unused file.
_on_disk = {p.stem for p in SHEETS_DIR.glob("*.png")}
assert _on_disk == set(FIG), f"frames.json and .context/sheets/*.png disagree: " \
                             f"{sorted(_on_disk ^ set(FIG))}"


def figframe(fid):
    """A Figma export with its provenance under it, so a reader can date and re-check it."""
    f = FIG[fid]
    # Exports are 2x, so half the pixel width is the size that renders 1:1 on a retina
    # screen. Without the cap a 450pt phone column stretches to the full card and goes soft.
    return (f'<figure class="figwrap">'
            f'<img class="fig" src="sheets/{fid}.png" width="{f["w"]}" height="{f["h"]}" '
            f'style="max-width:{f["w"] // 2}px" alt="Figma frame: {fid}" loading="lazy">'
            f'<figcaption class="figsrc"><span>Figma &middot; exported '
            f'{SHEETS["exported"]}</span>'
            f'<a href="{FIG_URL % f["node"]}">open frame</a></figcaption></figure>')


SHEET_FAMILIES = [
    ("share", "Share", "Session share, the nested push-to-EHR step, and send-to-patient."),
    ("settings", "Session settings",
     "Transcribe and dictate, with nested voice, scribe and language steps."),
    ("template", "Template", "Template picker, default and search."),
    ("patient", "Patient", "Empty, populated, search and create-new."),
    ("merge", "Session merge", "Merge prompt, the enable step, and patient linking."),
    ("other", "Consent", "Obtain patient consent."),
    ("remote", "Remote", "Connection, permission prompts and the takeover state."),
]

psheets = (
    design_note("The sheet surface has not been refactored onto tokens yet. This is the "
                "target, not what the app renders today.")
    + '<h2>Detents<span class="ct">2</span></h2>'
    '<p class="lede sub">Medium presents the sheet at a medium height, keeping the '
    'underlying content visible, for lightweight, contextual tasks. Large presents '
    'it at maximum height, for immersive, content-rich or multi-step tasks.</p>'
    + figframe("detents")
    + '<h2>Anatomy</h2>'
    '<p class="lede sub">Grabber, toolbar, title and controls, content sections, and the '
    'action area, with the tokens each part is drawn from.</p>'
    + figframe("anatomy")
    + '<h2>Props<span class="ct">4</span></h2>'
    '<p class="lede sub">The knobs on the Figma component.</p>'
    + ttable([("Prop", "26%"), ("Values", "74%")],
             [[tk("Detent"), us("`Large` &middot; `Medium`")],
              [tk("Title"), us("`Default` &middot; `Large`")],
              [tk("isResizable"), us("Boolean")],
              [tk("ShowTitle"), us("Boolean")]])
    + '<h2>Toolbars<span class="ct">8</span></h2>'
    '<p class="lede sub">Minimised, default, large, nested and search, each in '
    'sheet and full-screen form.</p>'
    + figframe("toolbars")
    + "".join(f'<h2>{name}</h2><p class="lede sub">{desc}</p>{figframe(fid)}'
              for fid, name, desc in SHEET_FAMILIES))


# ----------------------------------------------------------- page: who we are
# Every string below is transcribed from the brand documents, not written here. The
# order follows the Brand Book: what we are aiming at, then what we believe, then what we
# promise, and only then how we behave.
FOUNDATIONS = [
    ("Our vision", "Every clinician practising with an AI partner in care.",
     "AI will define the next era of healthcare: a future where clinicians lead care with "
     "AI alongside &mdash; indispensable at every step."),
    ("Our mission", "Doubling healthcare&rsquo;s capacity without dehumanising it.",
     "When AI chases efficiency over humanity, care suffers. When it works with clinicians "
     "&mdash; not against them &mdash; they can focus fully on patients, and care reaches "
     "more people while staying deeply human."),
    ("Our perspective", "Healthcare needs a better rhythm.",
     "Too often, care comes in bursts and gaps. Patients are seen in moments, then left "
     "waiting. Clinicians give everything in the room, with little space before or after to "
     "stay connected. A steadier rhythm is possible &mdash; one that supports patients "
     "continuously and sustains clinicians over time."),
    ("Our belief", "AI isn&rsquo;t just about saving time. It&rsquo;s about keeping care "
     "continuous.",
     "Technology should do what&rsquo;s otherwise impossible: connect what happens in the "
     "visit to what happens after &mdash; ensuring patients feel supported across the whole "
     "journey, not just in the room."),
    ("Our promise", "To protect and extend the human touch in healthcare.",
     "Heidi isn&rsquo;t here to replace clinicians. It restores focus, attention, and "
     "presence so care feels more personal, not less. By handling work in the background, "
     "Heidi gives clinicians the time and focus to practise as they were trained &mdash; "
     "with people always at the center."),
    ("Our role", "The clinician&rsquo;s indispensable partner.",
     "Heidi is more than technology. It&rsquo;s a trusted ally &mdash; standing alongside "
     "clinicians today and evolving with them to shape the future of healthcare."),
    ("Our proposition", "Care begins and ends with the clinician. Heidi takes care of the "
     "rest.",
     "From documentation to insight, Heidi puts clinicians first &mdash; supporting the "
     "rhythm of care and keeping every patient at the center."),
    ("Our edge", "Transforming care with clinicians&rsquo; trust.",
     "Heidi is the most used &mdash; and most loved &mdash; platform of its kind. That "
     "trust gives us the foundation for a new rhythm of care. And we&rsquo;ll deliver it "
     "only by holding to the highest bar: the standard clinicians set for patient care."),
]

VALUES = [
    ("Live Forever", "We build for healthcare&rsquo;s next decade, not next quarter.", [
        ("Set outrageous targets",
         "We&rsquo;re doubling healthcare&rsquo;s capacity. Free products today, AI doctors "
         "tomorrow. While others debate next year, we&rsquo;re building for the next decade. "
         "The world&rsquo;s health is at stake, our ambitions must have existential urgency."),
        ("Lead healthcare forward",
         "Sometimes we build what&rsquo;s needed before it&rsquo;s wanted. Prevention beats "
         "a cure &mdash; we treat tomorrow&rsquo;s problems today. We&rsquo;re partners in "
         "shaping healthcare&rsquo;s future, not order-takers. Even when that&rsquo;s "
         "uncomfortable."),
        ("Follow the evidence",
         "Data doesn&rsquo;t care about your opinions. We pursue truth like a diagnosis "
         "&mdash; methodically, relentlessly. However, when the subjective and the objective "
         "disagree, we trust the subjective. We treat the patient, not the numbers. Ego is a "
         "comorbidity we can&rsquo;t afford."),
    ]),
    ("Practice Ownership", "Everyone here carries the company.", [
        ("Raise the bar",
         "Exceptional outcomes need exceptional people. We hire for what someone will "
         "become, not just what they are. Values first, aptitude second and skills last. "
         "Skills can be taught &mdash; character cannot."),
        ("Own the outcome",
         "Never be the bystander. When something&rsquo;s broken, fix it fast. When systems "
         "decay, rebuild them. Raise problems with solutions. We solve end to end. We "
         "don&rsquo;t point fingers."),
        ("Focus on what matters",
         "Organisations resist. Systems slow things down. We push through anyway. High "
         "agency means creating a path when none exists. Debate fiercely, decide quickly and "
         "commit fully. The work matters more than the org chart."),
    ]),
    ("Move Fast, Fix Faster", "The more we do, the more we learn.", [
        ("Ship atoms daily",
         "A button today, a workflow tomorrow. We release in precise, perfect pieces &mdash; "
         "A/B tested, measured, enterprise-ready. Every pixel matters. Every millisecond "
         "matters. Each detail builds trust."),
        ("Learn from every release",
         "Each output teaches us something &mdash; a product deploy, a process change, a "
         "proposal, a conversation. We measure, refine, and go again. More iterations beat "
         "better planning, every time."),
        ("Be precise at pace",
         "Speed for consumers. Stability for enterprise. We&rsquo;re not reckless &mdash; "
         "we&rsquo;re precise at pace. Trust is hard to earn, and even harder to win back."),
    ]),
    ("Get Better", "The best clinicians teach. So do we.", [
        ("Live in clinicians&rsquo; reality",
         "Not the ideal workflow, the actual one. The twenty-patients-before-lunch reality. "
         "We build for exhausted clinicians, not marketing wins."),
        ("Bring warmth to the work",
         "We&rsquo;re transforming healthcare. We better be decent humans while we do it. "
         "Direct and open feedback, kindness when it&rsquo;s hard. Life&rsquo;s too short "
         "for anything else."),
        ("Clarity, not cleverness",
         "Clarity is kindness. Brevity is strength. We share context broadly, give feedback "
         "directly, and trust people with truth. No politics, no games."),
    ]),
]

# Supplied copy, not a transcription: this no longer tracks the Brand Book's manifesto page,
# so do not "restore" it by diffing against that deck — the two have deliberately diverged.
# One tuple per stanza and one string per line, matching the breaks the copy was written
# with. Collapsing stanzas into paragraphs is what let the wording drift last time.
MANIFESTO = [
    ("To care for another person is one of life&rsquo;s greatest callings.",),
    ("And every clinician knows that care is more than the work around it.",
     "It&rsquo;s attention. Judgement. Trust. Human connection."),
    ("As healthcare changes, we believe those things should become more present, not less.",),
    ("Patients should feel seen.",
     "Clinicians should have the freedom to focus on what they were trained to do.",
     "And care shouldn&rsquo;t stop when the appointment ends."),
    ("Technology can make that possible. Not by replacing the human parts of care, but by "
     "taking care of everything around them.",),
    ("By listening, understanding and carrying the work forward.",
     "By connecting the moments in the room with everything that happens between visits.",
     "By giving clinicians more time and capacity for the work only they can do."),
    ("That&rsquo;s why Heidi exists.",),
    ("To stand alongside those who care.",
     "To help care flow further.",
     "And to keep healthcare human."),
]

# The four voice principles, each with the Brand Book's clinical simile — the simile is what
# makes the principle usable, so it travels with it rather than being summarised away.
VOICE = [
    ("Clarity, not cleverness", "Be smart in what you say, not in how you say it.",
     "Like the doctor who takes a complex diagnosis, strips away the jargon, and leaves you "
     "with words you&rsquo;ll remember at home."),
    ("Calm, not inflated", "Confidence is steady and grounded, never loud or exaggerated.",
     "Like the nurse who steadies your hand, meets your eyes with quiet assurance, and makes "
     "the moment of the needle feel smaller."),
    ("Warmth, not pretense", "Let genuine care come through, not a polished front.",
     "Like the physio who catches your smallest progress, smiles, and says, "
     "&ldquo;That&rsquo;s it &mdash; you&rsquo;re getting stronger,&rdquo; turning effort "
     "into encouragement."),
    ("Simple, not cluttered", "Plain words that explain what matters, not jargon that "
     "confuses.",
     "Like the surgeon who walks you through each step, so you know what&rsquo;s coming, and "
     "never feel left in the dark."),
]

# The persona is the premise the four principles hang off — each one is a description of how
# this one person would say a thing — so it reads before them, not as a footnote after.
PERSONA = ("Your most trusted clinician.",
           "Heidi speaks with the presence of the clinician you&rsquo;d trust most: the one "
           "who makes sense of complexity without effort, who gives reassurance in a single "
           "word, and whose warmth shows in the smallest moments &mdash; always by your side. "
           "This is a voice that carries knowledge with compassion, guidance with humanity, "
           "and leaves you certain you&rsquo;re in safe hands.")

# Kept as the Brand Book's own examples rather than rewritten as UI strings: these pairs are
# the only part of the voice section a sentence can be checked against, and an example
# reworded to suit a screen would be a claim about the brand that nobody approved.
DODONT = [
    ("Clarity, not cleverness", [
        ("Be precise",
         "Heidi frees clinicians from note-taking so they can focus on patients.",
         "Heidi makes everything better for clinicians."),
        ("Be plainspoken",
         "AI helps connect what happens in the room with what happens after.",
         "AI helps enable continuity of care pathways across touchpoints."),
    ]),
    ("Calm, not inflated", [
        ("Be grounded",
         "Clinicians helped design Heidi from day one.",
         "Heidi was built with next-generation, cutting-edge innovation."),
        ("Speak with calm confidence",
         "We hold ourselves to high standards of safety and reliability.",
         "We&rsquo;re setting new benchmarks in safety and redefining reliability."),
    ]),
    ("Warmth, not pretense", [
        ("Be encouraging",
         "We stand alongside clinicians in the hard work of care.",
         "We are honored to be the guardian of every clinician&rsquo;s journey."),
        ("Show humanity in small, honest ways",
         "Care is never just about tasks &mdash; it&rsquo;s about people.",
         "Care is more than checklists &mdash; it&rsquo;s about the human element."),
    ]),
    ("Simple, not cluttered", [
        ("Use structure that guides",
         "One purpose: to protect the human touch.",
         "Our purpose is defined by multiple key objectives that collectively advance the "
         "mission of care."),
        ("Keep language simple and direct",
         "Heidi gives clinicians time back &mdash; and patients feel the difference.",
         "Heidi helps clinicians reclaim meaningful time so patients ultimately benefit."),
    ]),
]


REGISTERS = [("Aesop", "chose calm over excitement"),
             ("Stripe", "chose precision over personality"),
             ("Apple", "chose care over cleverness")]




def brand_voice_extra():
    """Persona, do/don't pairs and per-audience tone — the rest of the Brand Book's voice
    section. Split out so pwho takes one line of it."""
    out = ['<h2>Do&rsquo;s and don&rsquo;ts</h2>',
           '<p class="lede sub">Two examples per principle, word for word from the Brand '
           'Book.</p>']
    for principle, pairs in DODONT:
        out.append(f'<h3>{principle}</h3>')
        # The rule name stays in DODONT because it is part of the transcription, but it is
        # not drawn: the pair below it says the same thing in the brand's own words.
        for _rule, do, dont in pairs:
            out.append(f'<div class="dd">'
                       f'<div class="ddpair"><p class="do">{do}</p>'
                       f'<p class="dont">{dont}</p></div></div>')
    return "".join(out)

pwho = (
    # The manifesto opens with no heading: the Brand Book page has none, and the brand
    # speaking for itself is the point. Sitting before the first h2 also keeps sectionise()
    # off it, so it stays one unbroken block instead of a carded section.
    '<div class="mani">'
    + '<img class="mstar" src="star.png" alt="" aria-hidden="true">'
    + "".join(f'<p class="textXL reveal">{"<br>".join(lines)}</p>' for lines in MANIFESTO)
    + '</div>'
    # Brand headings carry no count: a count reads as a measured fact, and these are
    # editorial groupings rather than a swept inventory.
    + '<h2>Where we&rsquo;re headed</h2>'
    '<p class="lede sub">What we aim at, what we believe, and what we promise in '
    'return.</p>'
    + "".join(f'<div class="bstat"><em class="eyebrow">{label}</em>'
              f'<div><b>{claim}</b><p>{body}</p></div></div>'
              for label, claim, body in FOUNDATIONS)
    + '<h2>Voice</h2>'
    '<p class="lede sub">Speak the way that exceptional care feels.</p>'
    + f'<div class="bstat"><em class="eyebrow">Persona</em>'
      f'<div><b>{PERSONA[0]}</b><p>{PERSONA[1]}</p></div></div>'
    + "".join(f'<div class="bstat"><em class="eyebrow">#{i + 1}</em>'
              f'<div><b>{name}</b><p>{rule} {simile}</p></div></div>'
              for i, (name, rule, simile) in enumerate(VOICE))
    + brand_voice_extra())
# --------------------------------------------------------- page: who we serve
# Transcribed from the archetypes doc. Each entry keeps the archetype's own words for the
# quote — a paraphrase would lose the thing that makes an archetype usable in a review.
ARCH_DIR = ROOT / ".context/archetypes"
ARCHETYPES = [
    ("solo-clinician", "The Solo Clinician", "GP / Independent Clinician",
     "I just want to finish my notes before I get home. I don&rsquo;t want to be typing at "
     "9pm again.",
     "General practice, family medicine, primary care",
     ["Solo or small group clinic (1&ndash;5 doctors)",
      "25&ndash;40 back-to-back appointments a day",
      "Heidi runs beside Best Practice, MedicalDirector or Zedmed"],
     ["Finish the note during or right after the appointment",
      "Turn one consult into note, letter, referral and task",
      "Document in their own clinical voice, not generic AI output"],
     ["Notes spill into personal time &mdash; the #1 reason they try Heidi",
      "One appointment generates 3&ndash;5 separate documents",
      "EHR copy-paste friction slows down the last mile"]),
    ("high-pressure", "The High-Pressure Specialist",
     "ED Doctor / Hospitalist / Secondary Care",
     "I&rsquo;m managing 12 patients at once and I can&rsquo;t remember what I ordered for "
     "bed 7. I need a second brain, not another app.",
     "Emergency medicine, general medicine, cardiology, surgery, oncology",
     ["Hospital ED, inpatient ward or outpatient specialty clinic",
      "8&ndash;15 patients at once, in a circular, non-linear flow",
      "Works inside Altera Sunrise, Cerner or Epic"],
     ["Capture clinical information without breaking focus",
      "Track tasks and orders across concurrent patients",
      "Produce discharge summaries and referrals at pace"],
     ["The session-centric model assumes a linear consult",
      "Tasks are completed by nurses who cannot see them",
      "No urgency ordering &mdash; critical in triage"]),
    ("mental-health", "The Mental Health Clinician", "Psychologist / Psychiatrist",
     "My notes need to capture the nuance of what was said. A summary isn&rsquo;t enough "
     "&mdash; I need clinical language that actually reflects the presentation.",
     "Clinical psychology, psychiatry, counselling, neuropsychology",
     ["Private practice, hospital outpatient or psychology clinic",
      "6&ndash;12 sessions a day, 50&ndash;90 minutes each",
      "Note-taking mid-session is often clinically inappropriate"],
     ["A post-session note (SOAP, DAP, progress) that keeps the nuance",
      "NDIS, Medicare and insurance correspondence, quickly",
      "Cut the 30&ndash;60 minutes of admin after every patient"],
     ["Generic notes miss their orientation (CBT, ACT, psychodynamic)",
      "Highly sensitive content makes privacy a prerequisite, not a feature",
      "Structured forms (PHQ-9, K10, risk) are a core workflow gap"]),
    ("practice-champion", "The Practice Champion", "Practice Owner / Medical Director",
     "I need my whole team on this &mdash; it only works if everyone&rsquo;s using it. I "
     "can&rsquo;t have half the practice on Heidi and half still dictating.",
     "General practice, primary care, mixed- and private-billing clinics",
     ["Multi-GP clinic or corporate centre (5&ndash;50+ clinicians)",
      "Still sees patients, and carries P&amp;L for the practice",
      "Watches transcription spend closely (\\$60&ndash;80K+ a year)"],
     ["Get every clinician in the practice using Heidi consistently",
      "Replace the practice&rsquo;s transcription service",
      "Standardise note and letter quality across clinicians"],
     ["Sceptical partners and locums are the hardest internal sell",
      "Individual onboarding doesn&rsquo;t scale",
      "The ROI case has to be concrete, not vague"]),
    ("practice-admin", "The Practice Admin", "Receptionist / Admin / Medical Secretary",
     "My morning is 40 faxes, 20 results to route, and a pile of letters waiting to be sent. "
     "And that&rsquo;s before the phone starts ringing.",
     "GP clinics, specialist practices, day surgeries, outpatients",
     ["Works across Best Practice, HealthLink, Medical-Objects, fax and email",
      "Non-clinical: correspondence, filing, dispatch, front desk",
      "Completely outside Heidi today"],
     ["Process inbound correspondence from a single view",
      "Send clinician-authored letters without reformatting",
      "See the clinician&rsquo;s tasks without a verbal handover"],
     ["Documents arrive through 4&ndash;6 incompatible channels",
      "Repetitive receive &rarr; triage &rarr; format &rarr; file handling",
      "Letter dispatch is manual even when Heidi wrote the letter"]),
    ("support-worker", "The Clinical Support Worker", "Practice Nurse / Ward Nurse",
     "The doctor generates the task. I&rsquo;m the one who actually does it. But I "
     "can&rsquo;t even see it in Heidi &mdash; I have to wait for them to tell me.",
     "Practice nursing, ward nursing, outpatients, procedural clinics",
     ["GP clinic, hospital ward or outpatient department",
      "Clinically trained; executes patient-facing follow-up",
      "Zero access to Heidi today"],
     ["See assigned tasks without being told verbally",
      "Action follow-ups and confirm completion",
      "Carry enough clinical context to act accurately"],
     ["Locked out of Heidi &mdash; the biggest gap in the team workflow",
      "Verbal handover doesn&rsquo;t scale on a busy ward",
      "No feedback loop back to the assigning clinician"]),
    ("practice-manager", "The Practice Manager", "Clinic Operations / Practice Manager",
     "Clinicians come and go, but I&rsquo;m the one who has to make sure everything actually "
     "runs. If this tool creates more tickets for me to handle, it&rsquo;s not worth it.",
     "Multi-GP clinics, corporate centres, specialist groups, day hospitals",
     ["Manages 5&ndash;50+ staff; billing, compliance, EHR config, vendors",
      "Primary evaluator when the Champion wants to scale Heidi",
      "Becomes the Heidi admin owner after rollout"],
     ["Evaluate Heidi against security, compliance and EHR requirements",
      "Roll out to the clinical team with minimal disruption",
      "Monitor adoption and flag issues before they reach patients"],
     ["Due diligence needs documented, shareable answers",
      "No repeatable onboarding path for 10&ndash;20 clinicians",
      "No visibility over who is actually using Heidi"]),
]
PRIMARY_ARCH = 3


ARCH_EXT = ("jpg", "jpeg", "png", "webp")


def arch_source(slug):
    """The dropped-in original, whatever it was named, or None."""
    return next((p for ext in ARCH_EXT
                 if (p := ARCH_DIR / f"{slug}.{ext}").exists()), None)


def arch_slot(slug):
    """The image slot. Named after the archetype so an upload needs no wiring, and says so
    while it is empty rather than leaving a silent grey box. Always points at the .jpg the
    build re-encodes below, whatever the original's format was."""
    if arch_source(slug):
        return (f'<div class="arch-img"><img src="archetypes/{slug}.jpg" '
                f'alt="{slug}" loading="lazy"></div>')
    return ('<div class="arch-img todo"><code>drop a wide image at<br>'
            f'.context/archetypes/{slug}.jpg</code></div>')


def archetype(a, n):
    slug, name, role, quote, specialties, env, jobs, pains = a
    # The name sits in the photograph, bottom left, as an h2 — nested inside .arch-img, so
    # sectionise() and wrap_heads() (which only walk depth-0 elements) still see Primary and
    # Secondary as the page's only sections. exposure_h2's regex does reach it, which is what
    # sets it in Exposure; `onimg` is what draws it white.
    # With no photograph there is nothing to reverse out of, so it stays above the box.
    # Role, name and quote read as one caption, so they live together on the photograph:
    # role above the name, quote below it. Only the facts grid stays on the page beneath.
    head = f'<h2 class="onimg aname">{name}</h2>'
    # Italic carries the quotation; the marks would be a second one saying the same thing.
    cap = f'<p class="role">{role}</p>{head}<blockquote>{quote}</blockquote>'
    # The number rides the image slot in both states, so it keeps counting whether or not a
    # photograph has landed yet — numbering that skipped an empty slot would renumber the set
    # every time one was filled.
    badge = f'<em class="abadge">{n}</em>'
    # No photograph to reverse out of, so the caption sits above the empty slot instead.
    slot = (arch_slot(slug)[:-len("</div>")] + badge + f'<span class="arch-cap">{cap}</span></div>'
            if arch_source(slug)
            else f'<div class="arch-nocap">{cap}</div>'
                 + arch_slot(slug)[:-len("</div>")] + badge + '</div>')
    return (f'<div class="arch">{slot}<div>'
            '<div class="afacts">'
            f'<div><h4>Specialties</h4><p>{specialties}</p></div>'
            '<div><h4>Environment</h4><ul>'
            + "".join(f'<li>{x}</li>' for x in env) + '</ul></div>'
            '<div><h4>Jobs to be done</h4><ul>'
            + "".join(f'<li>{x}</li>' for x in jobs) + '</ul></div>'
            '<div><h4>Pain points</h4><ul>'
            + "".join(f'<li>{x}</li>' for x in pains) + '</ul></div>'
            '</div></div></div>')


pserve = (
    # No counts on brand headings — see pwho.
    '<h2>Primary</h2>'
    '<p class="lede sub">Every roadmap argument starts with one of these three.</p>'
    # Numbered straight through both groups rather than restarting at Secondary: they are one
    # set of archetypes that happens to be split by how often it comes up, and two cards
    # labelled 1 on the same page would read as two lists.
    + "".join(archetype(a, i) for i, a in enumerate(ARCHETYPES[:PRIMARY_ARCH], 1))
    + '<h2>Secondary</h2>'
    '<p class="lede sub">Around every clinician sits a team. Two of them cannot open '
    'Heidi at all, which is exactly why they are here.</p>'
    + "".join(archetype(a, i)
              for i, a in enumerate(ARCHETYPES[PRIMARY_ARCH:], PRIMARY_ARCH + 1)))


# ------------------------------------------------------------------ pages: screens
# Captures of the running app on a simulator, not mockups — the same contract the token
# tables hold to, so a screen that drifts shows up here as a stale capture rather than as
# a drawing nobody has to keep true. Every account behind these is synthetic: this repo is
# HIPAA-regulated and a real consult must never reach a public page.
SHOT_DIR = ROOT / ".context/screens"
# Tiles render ~230px wide, so 620 is comfortably past 2x — a 3x device capture would ship
# six times the bytes for pixels no display asks for.
SHOT_W = 620


def shot(section, slug, mode):
    """One capture, or the slot it is waiting for.

    Named for the screen so a capture needs no wiring, and says which file is missing
    rather than leaving a silent grey rectangle — the same bargain arch_slot() makes."""
    name = f"{slug}-{mode}.jpg"
    if (SHOT_DIR / section / f"{slug}-{mode}.png").exists():
        return (f'<img class="sh {mode}" src="screens/{section}/{name}" '
                f'alt="{slug} in {mode} mode" loading="lazy">')
    return (f'<div class="sh {mode} todo"><code>screens/{section}/<br>{slug}-{mode}.png'
            f'</code></div>')


def screens_page(section, blurb, items):
    """The mosaic. Light and dark ship in the same tile and the toggle swaps which one is
    shown, because a pair side by side halves every tile to say one thing twice."""
    return (f'<p class="lede sub">{blurb}</p>'
            f'<input type="checkbox" id="dk-{section}" class="dktog" hidden>'
            f'<label for="dk-{section}" class="dkbtn"><span>Light</span><span>Dark</span>'
            f'</label>'
            + '<div class="smos">'
            + "".join(f'<figure class="stile"><div class="sframe">'
                      f'{shot(section, slug, "light")}{shot(section, slug, "dark")}</div>'
                      f'<figcaption><b>{name}</b><code>{view}</code></figcaption></figure>'
                      for slug, name, view in items)
            + '</div>')


PAGES = [
    ("who-we-are.html", "By your side",
     # heidihealth.com/en-au's "Your AI Care Partner" line, sentence-cased to sit under the
     # headline above rather than in the site's own title case.
     "Your trusted AI care partner", pwho),
    # The lede is the banner's second line now, so it is one clause rather than the
    # three-clause count it was as a page lede — the split is on the page below it.
    ("who-we-serve.html", "Who we serve",
     f"{PRIMARY_ARCH} clinicians Heidi is built for, and "
     f"{len(ARCHETYPES) - PRIMARY_ARCH} more who live with every decision we make.",
     pserve),
    ("index.html", BRAND,
     "The native design system behind Heidi&rsquo;s iOS apps, maintained by the Platform "
     "team.", p0),
    ("colors.html", "Colors",
     "Semantic roles give every colour a job, and hold it in light and dark.",
     pc, ANATOMY_CSS),
    ("fonts.html", "Text",
     f"{len(fonts)} HHFont tokens across {len(FSECTS)} groups, in the shipped Inter and Exposure faces.",
     pf),
    ("spacing.html", "Spacing",
     f"{len(SPACING)} stops from 0 to 64pt, for padding, stacks and gaps.", p_space),
    ("radius.html", "Radius",
     f"{len(RADIUS)} corner radii, from 4pt to 36pt.", p_radius),
    ("sizing.html", "Sizing",
     f"{len(SIZING)} fixed control, avatar and icon sizes.", p_sizing),
    ("shadows.html", "Shadows",
     f"{len(shadows)} elevation styles, toned with Bark 950 rather than black.", psh),
    ("motion.html", "Motion",
     f"{len(MOTION)} literal-timed animations across {len(MOTION_BY_SECS)} distinct durations "
     f"and {len(MOTION_BY_CURVE)} curves. An audit, not a scale.", pm),
    ("icons.html", "Icons",
     f"{len(registered) + len(loose)} Lucide glyphs referenced by the app, "
     f"from a catalogue of the full set.", pi),
    ("buttons.html", "Buttons", BUTTONS_LEDE, pbtn, BUTTONS_CSS),
    ("avatars.html", "Avatars",
     "Every variant of AvatarView, in light and dark, driven by the same rules as the view.", pa),
    ("toasts.html", "Toasts", "Transient, bottom-anchored status (APP-6740).",
     stub("Success, error, info and warning toasts, and how they differ from HHAlert.")),
    ("toolbars.html", "Toolbars (top)", "Top bars and their title treatments.",
     stub("Top-bar variants — large and inline titles, leading/trailing items, and the flat scrolled state.")),
    ("assets.html", "Assets",
     "Backdrops and faces that make a surface feel like Heidi.",
     passets),
    ("sheets.html", "Sheets",
     f"Detents, anatomy, toolbars and {len(SHEET_FAMILIES)} sheet families, from the iOS "
     "mobile Figma file.", psheets),
    ("empty-state.html", "Empty state", "Empty and zero-data states (APP-6651).",
     stub("Illustration, title, message and call-to-action for each empty state in the app.")),
    ("tabs.html", "Tabs", "Tab bars and segmented controls.",
     stub("The bottom tab bar and the segmented control, with their selected and disabled states.")),
    ("rows.html", "Rows",
     "List rows across the app. Each context tunes the same anatomy.",
     '<div class="next">'
     '<a href="rows-sessions.html"><b>Sessions</b><span>Grouped session list rows.</span></a>'
     '<a href="rows-settings.html"><b>Settings</b><span>Grouped setting rows with values and toggles.</span></a>'
     '<a href="rows-actions.html"><b>Actions</b><span>Action rows and destructive actions.</span></a></div>'),
    ("rows-sessions.html", "Session rows", "Grouped by date on the sessions list.",
     stub("Session list rows, grouped by date, with their dividers and inset.")),
    ("rows-settings.html", "Setting rows", "Grouped rows with leading icons, values and toggles.",
     stub("Setting rows — leading icons, right-aligned values, toggles and destructive actions.")),
    ("rows-actions.html", "Action rows", "Rows that perform an action rather than navigate.",
     stub("Action and destructive-action rows, with their pressed and disabled states.")),
    # Same source as the nav entries, so a group cannot appear in one and not the other.
    # No lede: the count and the light/dark pairing are both visible in the grid below, so
    # the line only restated what the page already shows.
    *((f"screens-{slug}.html", title, "",
       screens_page(slug, blurb, items)) for slug, title, blurb, items in SCREENS),
]

# Every nav destination must exist, or the sidebar links 404. PARENT names off-nav pages,
# so they have to be built too — that is the only thing keeping them lit in the sidebar.
built = {p[0] for p in PAGES}
linked = {"index.html"} | {h for _, items in NAV for h, _ in items} \
    | set(PARENT) | set(PARENT.values())
assert not linked - built, f"nav links to unbuilt pages: {sorted(linked - built)}"
# The sidebar tag promises a banner on the page it points at; keep the two in step.
_audit_content = {p[0]: p[3] for p in PAGES}
assert all('class="note audit"' in _audit_content.get(h, "") for h in AUDIT_PAGES), \
    "an AUDIT_PAGES page is missing its audit_note() banner"
# A STATUS key that names no page is a typo that silently leaves the page on its section
# default — i.e. claiming less than the truth, with nothing to notice it by.
assert not set(STATUS) - built, f"STATUS names unbuilt pages: {sorted(set(STATUS) - built)}"
assert set(STATUS.values()) <= set(STATUS_LABEL), "unknown status key in STATUS"
assert {s for s, _ in NAV} == set(SECTION_STATUS), "every nav section needs a default status"

OUT.mkdir(parents=True, exist_ok=True)
# Content-hashed filename: a reader holding a cached stylesheet can never pair it with
# newer markup. Pages serves site.css with max-age=600, which is exactly long enough to
# show a half-styled page after a nav change.

# Do/don't pairs read as one row of two so the contrast is the point, and they carry the
# Forest/Red tints rather than the status hues, which mean refactor state on this site.
CSS += (".dd{margin:0 0 14px}"
        ".dd .eyebrow{margin:0 0 7px}"
        ".ddpair{display:grid;grid-template-columns:1fr 1fr;gap:10px}"
        ".ddpair p{margin:0;border-radius:14px;padding:13px 15px;font-size:14px;"
        "line-height:1.5}"
        f".ddpair .do{{background:#{_FOREST['s50']};color:#{_FOREST['s900']}}}"
        f".ddpair .dont{{background:#{_RED['s50']};color:#{_RED['s900']}}}"
        # The glyphs are decoration on top of the tint, so they are generated rather than
        # typed into the transcription — the examples stay exactly as the Brand Book has them.
        '.ddpair .do::before{content:"\\2713  ";font-weight:600}'
        '.ddpair .dont::before{content:"\\2717  ";font-weight:600}'
        "@media(max-width:700px){.ddpair{grid-template-columns:1fr}}")

# The token chip is the one rule in the base CSS block that needs a parsed value, and that
# block is a plain string — so the Bark 800 rgb triplet is substituted once, here, before the
# stylesheet is hashed.
CSS = CSS.replace("{_BARK_RGB}",
                  ",".join(str(int(_BARK["s800"][i:i + 2], 16)) for i in (0, 2, 4)))
assert "{_BARK_RGB}" not in CSS

CSS_HREF = f"site.{hashlib.md5(CSS.encode()).hexdigest()[:8]}.css"
for old in OUT.glob("site*.css"):
    old.unlink()
(OUT / CSS_HREF).write_text(CSS)
# Pages caches HTML for 600s too, so a reader can hold markup that still asks for the
# old unhashed path. Keep site.css alive as a copy or that reader gets a bare-HTML page.
(OUT / "site.css").write_text(CSS)
import shutil
for _slug, _, _ in ANATOMY_SLIDES:
    shutil.copyfile(ROOT / f".context/design-system-anatomy-{_slug}.png", OUT / f"anatomy-{_slug}.png")
# The build never wipes OUT, so the single share-sheet diagram these four replaced would
# otherwise sit here unreferenced and still be published.
(OUT / "anatomy.png").unlink(missing_ok=True)
# Driven by HERO rather than named one by one: the config already drops assets that are
# not in .context/, so deriving the copy from it means adding footage is one file drop and
# a hard-coded line can never fall out of step with a hero that references it.
for _cfg in HERO.values():
    for _k in ("video", "poster"):
        _v = _cfg.get(_k)
        # One filename or a list of them — a hero can alternate between clips.
        for _n in ([_v] if isinstance(_v, str) else (_v or [])):
            shutil.copyfile(ROOT / ".context" / _n, OUT / _n)
# hero-brand.jpg was the Who we are still before it had footage. hero-2.mp4 was a second
# Welcome clip. Both are referenced by nothing now, so they stop being copied — and get
# cleared from a previous build's output.
(OUT / "hero-brand.jpg").unlink(missing_ok=True)
(OUT / "hero-2.mp4").unlink(missing_ok=True)
shutil.copyfile(ROOT / ".context/welcome-closer.jpg", OUT / "welcome-closer.jpg")
shutil.copyfile(ROOT / ".context/star.png", OUT / "star.png")
# The quote mark that led the archetype quotes is gone, so the site no longer publishes the
# glyph. The source stays in .context/ (and so in _generator/) rather than being deleted: it
# is 4.6 KB, and restoring the mark is then a CSS rule rather than finding the file again.
# The still the footage replaced — same reason as anatomy.png above.
(OUT / "hero.jpg").unlink(missing_ok=True)
shutil.rmtree(OUT / "textures", ignore_errors=True)
(OUT / "textures").mkdir()
for _n in TEXTURES:
    for _f in (f"{_n}.jpg", f"{_n}-thumb.jpg"):
        shutil.copyfile(TEXTURE_DIR / _f, OUT / "textures" / _f)
# People: the source PNGs are ~1.4 MB each of photographic gradient, which PNG is the wrong
# format for. The download and the thumb are both JPEG — ten of these as PNG would be a
# 14 MB page. Clips ship as-is; they are already compressed.
shutil.rmtree(OUT / "people", ignore_errors=True)
(OUT / "people").mkdir()
for _s, _l, _e in PEOPLE:
    if _e == "mp4":
        shutil.copyfile(PEOPLE_DIR / f"{_s}.mp4", OUT / "people" / f"{_s}.mp4")
        shutil.copyfile(PEOPLE_DIR / f"{_s}-poster.jpg", OUT / "people" / f"{_s}-poster.jpg")
        continue
    from PIL import Image as _Im
    with _Im.open(people_source(_s)) as _im:
        _im = _im.convert("RGB")
        _im.save(OUT / "people" / f"{_s}.jpg", "JPEG", quality=90, optimize=True,
                 progressive=True)
        _th = _im.resize((520, round(_im.height * 520 / _im.width)), _Im.LANCZOS)
        _th.save(OUT / "people" / f"{_s}-thumb.jpg", "JPEG", quality=82, optimize=True,
                 progressive=True)
shutil.rmtree(OUT / "sheets", ignore_errors=True)
(OUT / "sheets").mkdir()
for _f in FIG:
    shutil.copyfile(SHEETS_DIR / f"{_f}.png", OUT / "sheets" / f"{_f}.png")
# Archetype portraits are dropped in by hand, so the build takes whatever is there — a slot
# with no file renders as its own placeholder (arch_slot). Rebuilt from scratch so a renamed
# upload cannot leave the old file published under the old name.
shutil.rmtree(OUT / "archetypes", ignore_errors=True)
(OUT / "archetypes").mkdir()
for _slug, *_ in ARCHETYPES:
    _src = arch_source(_slug)
    if not _src:
        continue
    # Re-encoded rather than copied: the drops are 0.5–0.6 MB straight out of the generator,
    # and seven of those is a 4 MB page for images shown 912px wide. 1600 is 2x that, so the
    # band stays sharp on a retina screen and the page stays under a megabyte.
    from PIL import Image as _Im
    with _Im.open(_src) as _im:
        _im = _im.convert("RGB")
        if _im.width > 1600:
            _im = _im.resize((1600, round(_im.height * 1600 / _im.width)), _Im.LANCZOS)
        _im.save(OUT / "archetypes" / f"{_slug}.jpg", "JPEG", quality=82, optimize=True,
                 progressive=True)
_named = {a[0] for a in ARCHETYPES}
_stray = [p.name for p in ARCH_DIR.glob("*") if p.stem not in _named and p.name != ".keep"]
assert not _stray, f"image in .context/archetypes/ matches no archetype slug: {_stray}"

# Screen captures: PNG in, JPEG out. A device capture is 1206px of flat UI and lossless
# PNG of that is ~1 MB a piece — 32 of them would be a 30 MB page for tiles shown at 230.
# Rebuilt from scratch, for the same reason people/ and archetypes/ are: OUT is never wiped,
# so a capture whose source PNG is withdrawn would otherwise keep being published from a
# previous build — the page would show a screen nobody can trace to a file, and a capture
# pulled for containing PHI would still be live.
shutil.rmtree(OUT / "screens", ignore_errors=True)
for _sec, _t, _b, _items in SCREENS:
    for _slug, _name, _view in _items:
        for _mode in ("light", "dark"):
            _src = SHOT_DIR / _sec / f"{_slug}-{_mode}.png"
            if not _src.exists():
                continue
            (OUT / "screens" / _sec).mkdir(parents=True, exist_ok=True)
            from PIL import Image as _Im
            with _Im.open(_src) as _im:
                _im = _im.convert("RGB")
                if _im.width > SHOT_W:
                    _im = _im.resize((SHOT_W, round(_im.height * SHOT_W / _im.width)),
                                     _Im.LANCZOS)
                _im.save(OUT / "screens" / _sec / f"{_slug}-{_mode}.jpg", "JPEG",
                         quality=88, optimize=True, progressive=True)
# A capture whose name matches no screen is a rename that silently stopped being shown.
_want = {f"{s}/{slug}-{m}.png" for s, _t, _b, its in SCREENS for slug, _n, _v in its
         for m in ("light", "dark")}
_have = {f"{p.parent.name}/{p.name}" for p in SHOT_DIR.rglob("*.png")}
assert not _have - _want, f"capture in .context/screens/ matches no screen: {sorted(_have - _want)}"
_logo = (ROOT / ".context/logo_product.svg").read_text()
(OUT / "logo.svg").write_text(_logo)
# A browser tab can be dark, and the mark is near-black — without this it disappears there.
(OUT / "favicon.svg").write_text(_logo.replace(
    "<g clip-path",
    '<style>@media(prefers-color-scheme:dark){path{fill:#fff}}</style><g clip-path', 1))
assert "<style>" in (OUT / "favicon.svg").read_text(), "favicon dark-mode rule was not injected"
# Inter only. Exposure is licensed from 205TF under terms that forbid sharing the font
# software, so it must never land in the published output — see exposure_specimen().
(OUT / "fonts").mkdir(exist_ok=True)
shutil.copyfile(FONTDIR / "Inter.ttf", OUT / "fonts" / "Inter.ttf")
(OUT / "fonts" / "OFL.txt").write_text(
    "Inter is Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter),\n"
    "licensed under the SIL Open Font License, Version 1.1 — https://openfontlicense.org\n")
for stray in OUT.glob("fonts/Exposure*"):
    stray.unlink()
# Measuring hero contrast means dropping frames into a throwaway copy of a page and
# screenshotting it (see the README). OUT is never wiped, so such a scratch page would
# otherwise be published — a duplicate of a real page, at a public URL, pinned to whichever
# stylesheet hash was current when it was written. `_` prefix marks them; they never ship.
for scratch in OUT.glob("_*.html"):
    scratch.unlink()
# A page may carry its own extra CSS as a fifth field — Buttons needs the two iOS system
# colours that a Heidi token has not replaced yet.
for href, title, lede, content, *extra in PAGES:
    markup = page(href, title, lede, content, extra[0] if extra else "")
    markup = apply_overrides(href, markup)
    # After the overrides, so a heading edited in the browser is the text that gets drawn.
    markup = demote_h2(markup) if href in H3_HEAD_PAGES else exposure_h2(markup)
    # Last line of the debug rule: whatever slipped past the corpus and token filters is
    # caught here, before it is written — a published page is a permanent one. The heading
    # text now travels in alt=, which this sweep still reads.
    assert_no_debug(href, markup)
    # A count on a Brand heading reads as a measured fact — a swept inventory — and these
    # sections are editorial groupings, hand-written and hand-ordered. The rest of the site
    # earns its counts by sweeping the Swift sources; Brand cannot, so it carries none.
    assert not (href in _BRAND_PAGES and 'class="ct"' in markup), \
        f"{href} is a Brand page, so its headings carry no count"
    (OUT / href).write_text(markup)

# An override that matched nothing would be a silently dropped edit, so name it.
_orphans = [i for i in range(len(OVERRIDES)) if i not in _applied]
assert not _orphans, (f"copy overrides {_orphans} never matched a page — check the `page` "
                      f"field: {[OVERRIDES[i]['page'] for i in _orphans]}")

# primitives.html / semantics.html were separate pages and those URLs are already shared,
# so they redirect into the tab rather than 404.
for gone, tab in (("primitives.html", "primitives"), ("semantics.html", "semantics")):
    (OUT / gone).write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<title>Moved · {BRAND}</title>'
        f'<link rel="canonical" href="colors.html#{tab}">'
        f'<meta http-equiv="refresh" content="0;url=colors.html#{tab}">'
        f'<link rel="stylesheet" href="{CSS_HREF}"></head><body><main>'
        f'<p class="lede">Moved to <a href="colors.html#{tab}">Colors → {tab.title()}</a>.</p>'
        f'</main></body></html>')

if parked:
    print(f"  parked (built, no page in the IA yet): {', '.join(parked)}")
print(f"built {OUT}")
for f in sorted(OUT.iterdir()):
    print(f"  {f.name}  {f.stat().st_size:,} bytes")
