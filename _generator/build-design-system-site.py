#!/usr/bin/env python3
"""Generates the Heidi design-system site from the Swift token sources.

Re-run after changing HHColors.swift or HHColorPrimitives.swift:
    python3 .context/build-design-system-site.py
"""
import json, re, pathlib, html, hashlib

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
    return (f'<img class="h1img" src="titles/{slug}.png" '
            f'style="height:{round(img.height / scale, 1)}px" '
            f'width="{round(img.width / scale)}" height="{round(img.height / scale)}" '
            f'alt="{html.escape(text)}">')


# ------------------------------------------------------------ audit vs specification
# Two kinds of thing live on this site and a reader has to tell them apart before copying
# anything: a value they may reuse, and a swept record of what the app happens to do today.
# The second kind is tinted with the app's own Negative role — the colour the product uses
# to say "look at this" — and marked in the sidebar too, so the distinction survives being
# linked to directly. Pages whose *whole* subject is current usage go in AUDIT_PAGES and
# carry the banner. This is orthogonal to STATUS: status says how far the refactor has
# got, the banner says whether what the page lists is approved.
AUDIT_PAGES = {"buttons.html", "motion.html"}

def audit_note(text):
    """The banner that separates an audit from a specification — same words every time."""
    return ('<div class="note audit"><b>An audit, not a specification.</b> '
            f'{text} Nothing here is approved for reuse by being listed.</div>')


def design_note(text):
    """A third kind of page: neither swept from source nor approved values, but a Figma
    export of what is *intended*. Every other page can promise it matches the build because
    it is parsed from the build; this one cannot, and has to say so in the same breath."""
    return ('<div class="note design"><b>A design, not the current build.</b> '
            f'{text} These frames are exported from Figma by hand, so unlike the rest of '
            'this site nothing verifies them against the app &mdash; check the date.</div>')


# ---------------------------------------------------------------- shell
# (section, [(href, label, [(href, label), ...]), ...]) — sections are labels only, never links.
NAV = [
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
]

# The nav is one level, but these pages still exist and are reached from their parent's
# cards — without this they would leave the sidebar with nothing lit.
PARENT = {"rows-sessions.html": "rows.html", "rows-settings.html": "rows.html",
          "rows-actions.html": "rows.html"}

# How far the app has been refactored onto a token: a dot before the sidebar label, a pill
# on the page itself. The default is per nav section, so a new page inherits its section's
# status rather than silently claiming to be Live; STATUS names only the exceptions.
STATUS_LABEL = {"live": "Live", "wip": "WIP", "todo": "To do"}
# The dot is a claim about the code, not the page: green means call sites have moved onto
# the token, not that the page is written. Welcome's legend is generated from this, so a
# new status cannot ship without an explanation of what its colour means.
STATUS_MEANING = {"live": "In sync with refactors",
                  "wip": "In progress, close",
                  "todo": "Out of sync, needs refactor"}
assert STATUS_LABEL.keys() == STATUS_MEANING.keys(), "every status needs a legend entry"
SECTION_STATUS = {"Foundations": "todo", "Components": "todo"}
STATUS = {"colors.html": "live", "icons.html": "live"}
# Nothing sits at "wip" today. The key stays because the legend documents all three and a
# page moves through it on the way to green — not because it is unused by oversight.


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
    st = status_of(href)
    return f'<i class="dot {st}"></i>' if st else ""


def status_pill(st):
    return f'<span class="pstat {st}"><i></i>{STATUS_LABEL[st]}</span>'


def pstat(href):
    """The dot-and-label pill. Takes a link target, so an in-page anchor resolves too."""
    st = status_of(href.split("#")[0])
    return status_pill(st) if st else ""


def sidenav(active):
    out = [f'<a class="brand{" on" if active == "index.html" else ""}" href="index.html">'
           f'<i class="mark"></i><span class="btxt"><b>{BRAND}</b>'
           f'<i>{BRAND_SUB}</i></span></a>']
    for section, items in NAV:
        out.append(f'<div class="navsec">{section}</div><ul>')
        for href, label in items:
            on = " class=on" if href in (active, PARENT.get(active)) else ""
            out.append(f'<li><a href="{href}"{on}>{dot(href)}{label}</a></li>')
        out.append("</ul>")
    return "".join(out)


BRAND = "HH Design System"
# The platform qualifier is a second line in the sidebar, not part of the name itself, so
# it stays out of BRAND — which also feeds <title> and the homepage hero raster.
BRAND_SUB = "iOS-Native"


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

    The heading block sits inside the card above a divider. Anything before the first h2
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
EDITABLE_SEL = ".shead h2, .shead h3, .lede, .prin h2, .prin p, .note, .eyebrow"

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
    # Welcome reverses out over the hero image, and the title is a raster — CSS cannot
    # recolour it, so it is drawn white rather than inverted after the fact.
    hero = active == "index.html"
    slug = "t-" + active.replace(".html", "")
    h1 = exposure_text(title, 48, slug, (255, 255, 255, 255) if hero else
                       (33, 18, 23, 255)) if head else ""
    head_html = (f'<div class="phead"><h1>{h1}</h1>{pstat(active)}</div>'
                 f'<p class="lede">{lede}</p>') if head else ""
    if hero:
        head_html = (f'<header class="hero"><em class="hbadge">&#8984; iOS</em>'
                     f'{head_html}</header>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{doc_title}</title>
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="stylesheet" href="{CSS_HREF}">
<style>.light{{{theme_vars('light')}}} .dark{{{theme_vars('dark')}}}{extra_css}</style>
</head><body>
<input type="checkbox" id="navtog" hidden>
<label for="navtog" class="navbtn" aria-label="Menu">
<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"
stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></label>
<nav class="side">{nav}</nav>
<label for="navtog" class="navdim"></label>
<main>{head_html}{content}</main>
{EDIT_JS}
</body></html>"""


# Inter is OFL-1.1, so it ships as a webfont. Exposure (205TF) forbids sharing the font
# software, so its specimens are rasterised at build time and the .otf is never published.
CSS = """@font-face{font-family:Inter;src:url(fonts/Inter.ttf);font-weight:100 900;font-display:swap}
*{box-sizing:border-box}
/* The whole page is this one flex row: panel, gutter, content. The gutter is the row's
   gap and the trailing margin repeats it, so the content sits the same distance from the
   panel as from the window edge — nothing here restates the panel's width. */
body{margin:0;background:#F9F4F1;color:#211217;
font:15px/1.55 ui-sans-serif,-apple-system,"SF Pro Text",system-ui,sans-serif;
letter-spacing:-.03em;display:flex;align-items:flex-start;gap:24px;padding:4px 24px 0 4px}
b,strong{font-weight:500}
code{font:12px ui-monospace,"SF Mono",Menlo,monospace}
/* side nav — sticky rather than fixed so it holds a track in the row and cannot overlap
   the content; the two share a top inset, which is what lines the brand up with the h1. */
.side{position:sticky;top:4px;flex:0 0 240px;max-height:calc(100vh - 8px);overflow-y:auto;
z-index:9;padding:16px}
/* On the brand too: it is the Welcome entry and lights up like any other item. */
.side a{border-radius:7px}
.side .brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:#211217;
font-size:13.5px;font-weight:500;line-height:1.25;padding:7px 10px;margin-bottom:20px}
/* Masked rather than an <img> so the mark takes a token colour rather than the flat fill
   baked into the file. */
.side .brand .mark{width:26px;height:26px;flex:0 0 auto;background:#4C2934;
-webkit-mask:url(logo.svg) center/contain no-repeat;mask:url(logo.svg) center/contain no-repeat}
.side .brand .btxt{display:flex;flex-direction:column;gap:1px;min-width:0}
.side .brand b{font-weight:500}
.side .brand i{font-style:normal;font-size:12px;font-weight:400;color:#755760}
.navsec{font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:.07em;
color:#A98993;padding:0 10px;margin:0 0 6px}
.side ul{list-style:none;margin:0 0 22px;padding:0}
.side ul:last-child{margin-bottom:0}
/* Flex, not block: a label that wraps ("Toolbars (top)") must not run under its dot. */
.side a:not(.brand){display:flex;align-items:center;gap:8px;text-decoration:none;
color:#755760;font-size:13.5px;font-weight:500;padding:6px 10px;border-radius:7px}
.side a .dot{flex:0 0 auto}
.side a:hover{background:#F0DFD1;color:#211217}
/* The active item is a white pill, brand included. White on the sand panel is only a two-
   step difference, so the shadow — the same one the carousel arrows use — is what makes it
   read as selected rather than as a gap. */
.side a.on{background:#fff;color:#211217;box-shadow:0 1px 3px rgba(33,18,23,.07)}
.side a.on:hover{background:#fff;color:#211217}
.side a.par{color:#211217}
.side .sub{margin:2px 0 4px;padding-left:11px;border-left:1px solid rgba(33,18,23,.1)}
.side .sub a{font-size:13px;font-weight:400;padding:5px 10px}
/* status — dot in the nav, pill on the page, same three hues in both.
   The dots are saturated rather than tinted because they also sit on the active row's
   #4C2934 fill, where a pale tint would read as another shade of the background. */
.dot{width:7px;height:7px;border-radius:50%;display:inline-block}
.dot.live{background:#2E9B5B} .dot.wip{background:#DF9E22} .dot.todo{background:#D45B5B}
/* Wraps because the title is a fixed-width raster: on a phone it would otherwise push the
   pill off-page instead of giving way to it. The auto margin keeps the pill right-aligned
   once wrapped, where space-between has nothing left to distribute. */
.phead{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}
.phead .pstat{margin-left:auto}
.pstat{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;font-size:11.5px;
font-weight:500;padding:4px 11px 4px 9px;border-radius:99px;white-space:nowrap}
.pstat i{width:7px;height:7px;border-radius:50%;background:currentColor;flex:0 0 auto}
.pstat.live{background:#D8EEDC;color:#1B6B3F} .pstat.wip{background:#F7E5C2;color:#7A4E12}
.pstat.todo{background:#FBD9D9;color:#8E2C2C}
.stcell .pstat{font-size:11px;padding:3px 10px 3px 8px}
/* The Status column's key, in the foot of the card whose column it explains. Legend scale,
   not table scale: the pills are the smallest thing on the page that still reads as the
   pill it maps to. */
.stfoot{display:flex;flex-wrap:wrap;gap:7px 18px;align-items:center;margin-top:18px;
padding-top:12px;border-top:1px solid rgba(33,18,23,.08)}
.stkey{display:inline-flex;align-items:center;gap:6px}
.stfoot .pstat{font-size:10px;gap:5px;padding:1px 7px 1px 6px}
.stfoot .pstat i{width:5px;height:5px}
.stkey em{font-style:normal;font-size:11.5px;color:#A98993}
/* No horizontal padding and no auto margin: the row's gap and the body's trailing margin
   are the only things setting the measure, so there is one number to change, not three.
   The cap only bites past ~1450px, where filling the window would stretch the tables. */
main{flex:1;min-width:0;max-width:1180px;padding:16px 0 56px}
/* display type ships as Exposure rasters — see exposure_text() */
h1 .h1img{display:block;width:auto;margin-left:-2px}
/* Height is pinned because these PNGs are 3x for retina — with width/height:auto the
   intrinsic (3x) size wins over the HTML attributes and the hero renders triple size. */
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
.prin h2{margin:0 0 5px}
.prin p{margin:0;font-size:14px;line-height:1.55;color:#755760;max-width:720px}
.avrow{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px 8px;
align-items:start}
.avcell{display:flex;flex-direction:column;align-items:center;gap:8px;min-width:0}
.avcell em{font-style:normal;font-size:10.5px;line-height:1.35;text-align:center;
color:var(--foregroundTertiary)}
.avcell em code{font-size:10px}
.avx{border-radius:50%;display:flex;align-items:center;justify-content:center;flex:0 0 auto;
font-weight:400;font-family:ui-rounded,"SF Pro Rounded",ui-sans-serif,system-ui,sans-serif}
.shwell{display:flex;align-items:center;justify-content:center;width:76px;height:60px;
border-radius:10px;background:#F4E7DD;flex:0 0 auto}
.shsw{width:40px;height:40px;border-radius:9px;background:#fff}
.stub{border:1px dashed rgba(33,18,23,.18);border-radius:12px;padding:20px 22px;color:#755760}
.stub b{display:block;color:#211217;font-size:14.5px;margin-bottom:4px}
.stub p{margin:0;font-size:14px;line-height:1.55;color:#755760;max-width:720px}
/* burger — only below the sidebar breakpoint */
.navbtn,.navdim{display:none}
@media(max-width:900px){
/* The panel leaves the row and becomes an overlay, so the row collapses to one column. */
body{display:block;padding:0 20px}
/* Needs a surface of its own here, unlike on desktop where it sits on the page: over the
   scrim it is the only opaque thing between the labels and the content behind them.
   Must clear the left inset too, or the panel stays partly on screen when closed. */
.side{position:fixed;top:4px;left:4px;bottom:4px;width:240px;max-height:none;
background:#F9F4F1;border-radius:14px;box-shadow:0 12px 40px rgba(33,18,23,.22);
transform:translateX(calc(-100% - 4px));transition:transform .18s ease}
#navtog:checked~.side{transform:none}
main{max-width:none}
.navbtn{display:flex;position:fixed;top:12px;left:12px;z-index:11;align-items:center;
justify-content:center;width:34px;height:34px;border-radius:9px;color:#211217;cursor:pointer;
background:rgba(249,244,241,.92);backdrop-filter:blur(10px);border:1px solid rgba(33,18,23,.1)}
#navtog:checked~.navdim{display:block;position:fixed;inset:0;z-index:8;background:rgba(33,18,23,.4)}
main{padding-top:58px}
}
h1{font-size:48px;font-weight:500;margin:0 0 5px;letter-spacing:-.021em}
.lede{color:#755760;font-size:14px;line-height:1.55;margin:0 0 30px;max-width:720px}
.lede.sub{margin:-4px 0 12px}
h2{font-size:24px;font-weight:500;color:#211217;letter-spacing:-.03em;
margin:34px 0 11px;display:flex;align-items:baseline;gap:8px}
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
.sw b{font-size:11.5px;font-weight:500} .sw code{font-size:9.5px;opacity:.9}
/* Every h2's content is carded by sectionise() — see that function for what stays out. */
.scard{background:#fff;border-radius:32px;padding:32px;margin:32px 0}
.shead{border-bottom:1px solid rgba(33,18,23,.08);padding-bottom:16px;margin:32px 0 24px}
.shead>:first-child{margin-top:0}
.shead>:last-child{margin-bottom:0}
/* A heading with nothing under it would rule off against the card's own edge. */
.shead:last-child{border-bottom:0;padding-bottom:0;margin-bottom:0}
/* Primitives: a swatch strip is its own label, so a rule per ramp is noise. */
.nodiv .shead{border-bottom:0;padding-bottom:0;margin:24px 0 10px}
/* The card's padding is the gutter now, so a child's own trailing margin would read as
   uneven bottom padding. */
.scard>:last-child{margin-bottom:0}
.scard>:first-child{margin-top:0}
/* tables */
table{width:100%;border-collapse:collapse;margin-bottom:8px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#A98993;
font-weight:500;padding:0 10px 9px 0}
td{padding:9px 10px 9px 0;vertical-align:middle;white-space:nowrap}
tbody tr+tr td{border-top:1px solid rgba(33,18,23,.05)}
td:first-child,th:first-child{padding-left:0}
.tk{font-weight:500;font-size:13.5px;white-space:normal;word-break:break-word}
.tk a{color:#211217;text-decoration:none;border-bottom:1px solid rgba(33,18,23,.22)}
.tk a:hover{border-bottom-color:#4C2934}
.tksub{display:block;font-weight:400;font-size:11px;color:#A98993}
.us{color:#755760;font-size:12.5px;white-space:normal}
.us code{font-size:11px;color:#755760}
.unused{font-style:normal;color:#A98993}
/* per-foundation swatches — same cell anatomy, different preview */
.fspec{font-style:normal;line-height:1;color:#211217;min-width:44px;flex:0 0 auto;
display:flex;align-items:center;justify-content:center;height:40px}
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
.hx{font-size:11px;color:#A98993} .hx code{font-size:11px}
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
.comp-h code{font-size:11px;color:#A98993}
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
.cite{display:inline-flex;align-items:center;gap:3px;background:var(--fillSecondary);border:1px solid var(--border);color:var(--foregroundPrimary);font-size:11px;font-weight:500;padding:1px 7px;border-radius:99px;vertical-align:baseline}
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
.note{background:#F6ECE4;border-radius:12px;padding:14px 16px;font-size:13.5px;
margin:22px 0 0;max-width:720px}
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
.sitelist{margin:9px 0 0;columns:2;column-gap:24px;font-size:12px;line-height:1.75}
@media(max-width:760px){.sitelist{columns:1}}
.sitelist div{break-inside:avoid;color:#A98993}
.sitelist code{font-size:11px;color:#755760}
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
_BARK = dict(ramps["HHBark"])
_SKY = dict(ramps["HHSky"])
CSS += (f".note.audit{{background:#{_RED['s100']};color:#{_RED['s900']}}}"
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
        "justify-content:flex-end;background:#211217 url(hero.jpg) center/cover no-repeat}"
        # The flat 20% is the brief. The gradient is on top of it because the copy sits over
        # sunlit grass, where white measured 1.22:1. Its fade is in px, not a percentage of
        # the hero: the content is bottom-anchored, so a percentage silently slides out from
        # under the title whenever min-height changes (at 560 it read 3.37:1, at 480 2.58:1).
        ".hero::before{content:'';position:absolute;inset:0;z-index:-1;background:"
        "linear-gradient(to top,rgba(0,0,0,.62) 0,rgba(0,0,0,0) 270px),rgba(0,0,0,.2)}"
        # Narrower than the 720px body measure: reversed out over a photograph, a long line
        # is harder to track back, and the wrap keeps the copy clear of the figure.
        ".hero .lede{color:rgba(255,255,255,.82);margin:0;max-width:560px;"
        "text-shadow:0 1px 12px rgba(0,0,0,.45)}"
        ".hero .phead{margin-bottom:10px}"
        # align-self, because .hero is a column flex container and the pill would otherwise
        # stretch the full width of the card.
        f".hero .hbadge{{align-self:flex-start;display:inline-flex;align-items:center;gap:5px;"
        f"font-style:normal;font-size:11.5px;font-weight:500;line-height:1;"
        f"padding:6px 11px;border-radius:999px;margin:0 0 14px;"
        f"background:#{_SUN['s200']};color:#{_BARK['s800']}}}"
        ".hero h1 .h1img{filter:drop-shadow(0 2px 14px rgba(0,0,0,.45))}"
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
    """Token cell — the symbol a view actually types."""
    return (f'<td class="tk">{html.escape(name)}'
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
p1 = f'<div class="scard nodiv">{wrap_heads(p1)}</div>'
p1 += ('<div class="note"><b>Primitives are fixed hex in both themes.</b> Theme adaptation happens in the '
       'semantic layer, never here. Views must not reference a ramp directly — compose a semantic token instead.</div>')

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
        ("Surface","Surface","Containers: pages, sheets, sections, cards — and the scrim behind dialogs."),
        ("Border","Border","Outlines, separators, strokes, hairlines."),
]
def cell(hx,a,nm):
    al = '' if a==1.0 else f'<i class="al">{int(round(a*100))}%</i>'
    return pv(f'<i class="chip" style="background:{rgba(hx,a)}"></i>',
              html.escape(nm), f'<code>{hx}</code>{al}', td=False)
sections = ""
for key,label,desc in CATS:
    rows = [s for s in sems if s['section']==key]
    if not rows: continue
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
# one) plus any Image.lucide("literal") that skipped it. The catalogue holds the whole
# Lucide set, so listing the catalogue would document 1500 icons we don't use.
# Lucide glyphs live in Lucide-Icons.xcassets, but a few (e.g. external-link) sit in the
# main catalogue instead. Both resolve by name at runtime, so both must be searched or the
# page reports a working icon as missing.
ICON_CAT = ROOT / "HeidiNative/Lucide-Icons.xcassets"
ICON_CATS = [ICON_CAT, ROOT / "HeidiNative/Assets.xcassets"]
icons_src = read_swift(ROOT / "HeidiNative/Managers/SymbolHelper/CustomIcons.swift")

registered = {}
for m in re.finditer(r'((?:[ \t]*///[^\n]*\n)*)[ \t]*static let (\w+) = "([^"]+)"', icons_src):
    doc = " ".join(l.strip().lstrip("/").strip() for l in m.group(1).strip().splitlines())
    # The comment opens by naming the glyph ("Book open icon - used for…"); keep the use.
    doc = re.sub(r"^[\w' ]+ icon\s*[-–]\s*", "", doc)
    doc = re.sub(r"^[\w' ]+ \([^)]*\)\s*[-–]\s*", "", doc).strip()
    if not (is_debug(m.group(2)) or is_debug(m.group(3))):
        registered[m.group(3)] = (m.group(2), doc[:1].upper() + doc[1:] if doc else "")

literals = set()
for sw in swift_sources(ROOT / "HeidiNative"):
    literals |= set(re.findall(r'\.lucide\(\s*"([^"]+)"', read_swift(sw)))
loose = sorted(literals - set(registered))


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
      '<p class="lede sub">Named in <code>CustomIcons</code> &mdash; the '
      'sanctioned way to reference a glyph.</p>'
      + grid_reg)
if loose:
    grid_loose, missing_loose = icon_grid(loose)
    pi += (f'<h2>Referenced by string literal'
           f'<span class="ct">{len(loose)}</span></h2>'
           '<p class="lede sub">Passed to <code>Image.lucide</code> as a '
           'literal instead of going through <code>CustomIcons</code>, which '
           '<code>CustomIcons.swift</code> asks callers to prefer.</p>' + grid_loose)
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


def exposure_specimen(otf, size):
    """Rasterise an Exposure specimen. The 205TF licence forbids redistributing the font
    itself, so the site carries a picture of the type rather than the type."""
    from PIL import Image, ImageDraw, ImageFont
    scale = 3
    face = ImageFont.truetype(str(FONTDIR / otf), size * scale)
    box = face.getbbox(SPECIMEN_TEXT)
    img = Image.new("RGBA", (box[2] - box[0] + 4, box[3] - box[1] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((2 - box[0], 2 - box[1]), SPECIMEN_TEXT,
                             font=face, fill=(33, 18, 23, 255))
    name = f"{pathlib.Path(otf).stem.replace('[', '').replace(']', '')}-{size}.png"
    (OUT / "specimens").mkdir(parents=True, exist_ok=True)
    img.save(OUT / "specimens" / name)
    return f"specimens/{name}", img.width // scale, img.height // scale


pf = ""
for fs in FSECTS:
    group = [f for f in fonts if f["section"] == fs]
    if not group:
        continue
    pf += f'<h2>{fs}<span class="ct">{len(group)}</span></h2>'
    rows = []
    for f in group:
        # Specimens use the real face at the real pt size, capped so a 48px heading
        # doesn't blow the row height out.
        shown = min(f["size"], 34)
        if f["fam"] == "Exposure":
            otf = "Exposure[+10].otf" if "+10" in f["ps"] else "Exposure[-10].otf"
            src, w, h = exposure_specimen(otf, shown)
            spec = f'<img class="fspec" src="{src}" width="{w}" height="{h}" alt="Ag">'
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
            # The Dynamic Type anchor belongs under the token, not under the value: it is
            # the native equivalent of the HH name, not a property of the rendered size.
            tk(f'HHFont.{f["name"]}',
               f'Dynamic Type · <code>.{f["anchor"]}</code>' if f["anchor"]
               else "Dynamic Type · inherited"),
            pv(spec, f'{f["size"]}px {f["fam"]} {f["weight"]}'),
            us(prose),
            f'<td class="us"><code>{html.escape(f["src"])}</code></td>',
        ])
    pf += ttable([("Token", "27%"), ("Value", "23%"), ("Notes", "32%"), ("Source", "18%")], rows)


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
COLOR_TABS = [("primitives", "Primitives", p1), ("semantics", "Semantics", p2)]

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
                     "Padding, stacks and gaps. <code>space4</code> (16pt) is the default.")
p_radius = scale_page("HHRadius", RADIUS, "radius",
                      "Corner radii. <code>md</code> (8pt) is the base.")
p_sizing = scale_page("HHSizing", SIZING, "size",
                      "Fixed control, avatar and icon sizes.")

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

LINK = ('<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex:0 0 auto">'
        '<path d="M9 15l6-6"/><path d="M12 6l1-1a4 4 0 0 1 6 6l-1 1"/><path d="M12 18l-1 1a4 4 0 0 1-6-6l1-1"/></svg>')


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
         + '<span class="cite" style="background:var(--fillProMuted);color:var(--foregroundPro);border-color:transparent">'
         + LINK + 'Patient document</span>'
         '<svg viewBox="0 0 24 24" width="17" height="17" fill="var(--foregroundPro)" stroke="none">' + I_FLASH + '</svg>'
         '</div>')

COMPONENTS = [
    ("Text hierarchy", "foregroundPrimary · Secondary · Tertiary · Accent",
     "Four foreground roles carry the whole type ramp; size and weight do the rest.", TEXT),
    ("Avatars — AvatarView", "fillBark/Sky/Forest/Sunlight + matching foreground",
     "44pt circle, initials in 16pt rounded regular; HHAccentHue picks a stable fill/foreground pair per name.", AVATARS),
    ("Pills — CitationPillView & Pro", "fillSecondary + border · fillProMuted · foregroundPro",
     "Citation pill: link icon, source name, +N count. Patient documents take the Pro-muted pair; the Pro flash indicator is icon-only.", PILLS),
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
    "Pills — CitationPillView & Pro": None,
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
        f'<section class="comp"><div class="comp-h"><b>{name}</b><code>{toks}</code></div>'
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
    body = "".join(f'<div><code>{html.escape(p)}</code> '
                   f'{", ".join(str(x) for x in ls)}</div>' for p, ls, _ in rows)
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
        f'<code>{v["fill_tok"] or html.escape(v["fill"])} &middot; {v["fg"]}</code></div>'
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
        ("Citation pill", "App/Features/Evidence/Components/CitationPillView.swift",
         r"struct CitationPillView", "<code>Capsule</code>, hairline, link glyph",
         "single &middot; +N count", "text 13 / 11"),
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
    '<code>.plain</code> is usually deliberate &mdash; it strips chrome from a row or a '
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
            'It was taken ahead of the button refactor, so it records what is in the app '
            f'today &mdash; {BTYPES} shared styles, {BESPOKE_N} controls that carry their '
            f'own chrome, and {n_buttons} button constructions across {cov_files} files '
            '&mdash; rather than what a caller should reach for. Counts and call sites are '
            'swept from the source at build time.')
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
    f'the {BTYPES} shared styles. This page documents all of it: the styles, the controls '
    'that go their own way, and the ones that are not buttons at all.')

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
        'The app has no motion token &mdash; no shared enum, no named curve. Every duration '
        'below is a literal at its call site, so the same gesture can animate at a different '
        'speed in two places. Everything here is swept from source at build time.')
    + f'<h2>Durations<span class="ct">{len(MOTION_BY_SECS)} distinct</span></h2>'
    '<p class="lede sub">Sorted by how often each appears. A duration used once is a '
    'one-off; the ones at the top are the de facto scale.</p>'
    + ttable([("Seconds", "16%"), ("Uses", "12%"), ("Curves", "34%"), ("Where", "38%")],
             [[f'<td class="tk">{secs:g}s</td>',
               f'<td>{len(hits)}</td>',
               us(", ".join(f"`{c}`" for c in sorted({h[0] for h in hits}))),
               f'<td class="us">{sitelist([(p, [l for _, pp, l in hits if pp == p], 1) for p in sorted({h[1] for h in hits})], plural(len({h[1] for h in hits}), "file")) or "&mdash;"}</td>']
              for secs, hits in sorted(MOTION_BY_SECS.items(),
                                       key=lambda kv: (-len(kv[1]), kv[0]))])
    + f'<h2>Curves<span class="ct">{len(MOTION_BY_CURVE)}</span></h2>'
    '<p class="lede sub">Which easing the app reaches for, and the range of speeds it is '
    'asked to run at.</p>'
    + ttable([("Curve", "26%"), ("Uses", "14%"), ("Range", "26%"), ("Distinct durations", "34%")],
             [[f'<td class="tk">.{curve}</td>', f'<td>{len(secs)}</td>',
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
    ("colors.html#primitives", "Primitives",
     f"{sum(len(v) for v in ramps.values())} stops · {len(ramps)} ramps",
     "HHColorPrimitives.swift"),
    ("colors.html#semantics", "Semantic colours",
     f"{sum(1 for t in sems if t['section'] in ('Foreground', 'Fill', 'Surface', 'Border'))}"
     " tokens · light/dark pairs", "HHColors.swift"),
    ("fonts.html", "Type", f"{len(fonts)} tokens · Exposure and Inter", "HHFont.swift"),
    ("spacing.html", "Spacing", f"{len(SPACING)} stops · 0&ndash;64pt", "HHSpacing.swift"),
    ("radius.html", "Radius", f"{len(RADIUS)} radii · 4&ndash;36pt", "HHRadius.swift"),
    ("sizing.html", "Sizing", f"{len(SIZING)} control, avatar and icon sizes", "HHSpacing.swift"),
    ("shadows.html", "Shadows", f"{len(shadows)} elevation styles", "View+HeidiShadow.swift"),
    ("motion.html", "Motion", f"{len(MOTION_BY_SECS)} durations &middot; {len(MOTION_BY_CURVE)} curves",
     "no token &mdash; call sites"),
    ("icons.html", "Icons", f"{len(registered)} Lucide glyphs in use", "CustomIcons.swift"),
]

# No h2 above it — it is the page's opening statement — so sectionise() would skip it. The
# heading is the same eyebrow-in-a-shead the Principles card uses, for the same reason: the
# card needs a label, and an h2 here would compete with the hero.
p0 = ('<div class="scard">'
      + '<div class="shead"><em class="eyebrow">Foundations</em></div>'
      + ttable([("Foundation", "24%"), ("Contents", "34%"), ("Source", "28%"), ("Status", "14%")],
               [[f'<td class="tk"><a href="{href}">{name}</a></td>', us(count),
                 f'<td class="us"><code>{src}</code></td>',
                 f'<td class="stcell">{pstat(href)}</td>']
                for href, name, count, src in INVENTORY])
      # A key, not a section: it explains one column of the table above it, so it rides in
      # the same card as a footer rather than taking a card of its own.
      + '<div class="stfoot">'
      + "".join(f'<span class="stkey">{status_pill(st)}'
                f'<em>{STATUS_MEANING[st]}</em></span>' for st in STATUS_LABEL)
      + '</div></div>'
      # Its own card, with the label inside above a rule — the shape sectionise() gives
      # every other section. The eyebrow stands in for the h2 a section head normally
      # carries, because the principles themselves are the h2s here.
      + '<div class="scard">'
      + '<div class="shead"><em class="eyebrow">Principles we work to</em></div>'
      + "".join(f'<section class="prin">'
                f'<h2>{html.escape(title)}</h2>'
                f'<p>{body}</p></section>'
                for title, body in PRINCIPLES)
      + '</div>')


# ----------------------------------------------------------- page: sheets
# The only page not derived from Swift. Frames are exported from Figma by hand into
# .context/sheets/ and described by frames.json, which also carries the export date — a
# rebuild must not restamp it, or the page would claim to be fresher than it is.
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
    design_note("Sheets is the first page here taken from Figma rather than parsed from "
                "the Swift sources, because the sheet surface has not been refactored onto "
                "tokens yet &mdash; this is the target, not what the app renders today.")
    + '<h2>Detents<span class="ct">2</span></h2>'
    '<p class="lede sub">Medium presents the sheet at a medium height, keeping the '
    'underlying content visible &mdash; for lightweight, contextual tasks. Large presents '
    'it at maximum height, for immersive, content-rich or multi-step tasks.</p>'
    + figframe("detents")
    + '<h2>Anatomy</h2>'
    '<p class="lede sub">Grabber, toolbar, title and controls, content sections, and the '
    'action area &mdash; with the tokens each part is drawn from.</p>'
    + figframe("anatomy")
    + '<h2>Props<span class="ct">4</span></h2>'
    '<p class="lede sub">The knobs on the Figma component.</p>'
    + ttable([("Prop", "26%"), ("Values", "74%")],
             [[tk("Detent"), us("`Large` &middot; `Medium`")],
              [tk("Title"), us("`Default` &middot; `Large`")],
              [tk("isResizable"), us("Boolean")],
              [tk("ShowTitle"), us("Boolean")]])
    + '<h2>Toolbars<span class="ct">8</span></h2>'
    '<p class="lede sub">Minimised, default, large, nested and search &mdash; each in '
    'sheet and full-screen form.</p>'
    + figframe("toolbars")
    + "".join(f'<h2>{name}</h2><p class="lede sub">{desc}</p>{figframe(fid)}'
              for fid, name, desc in SHEET_FAMILIES))


PAGES = [
    ("index.html", BRAND,
     "Reference for the colour, type, spacing and icons used by the Heidi iOS app. Every value "
     "here is parsed from the Swift sources when the site is built, so what you read is what "
     "ships &mdash; there is no second copy to keep in step.", p0),
    ("colors.html", "Colors",
     "One token model: primitives compose semantic roles, one spelling per job, correct in light and dark.",
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
     f"and {len(MOTION_BY_CURVE)} curves &mdash; an audit, not a scale.", pm),
    ("icons.html", "Icons",
     f"{len(registered)} Lucide glyphs referenced by the app, from a catalogue of the full set.", pi),
    ("buttons.html", "Buttons", BUTTONS_LEDE, pbtn, BUTTONS_CSS),
    ("avatars.html", "Avatars",
     "AvatarView — every variant, in light and dark, driven by the same rules as the view.", pa),
    ("toasts.html", "Toasts", "Transient, bottom-anchored status (APP-6740).",
     stub("Success, error, info and warning toasts, and how they differ from HHAlert.")),
    ("toolbars.html", "Toolbars (top)", "Top bars and their title treatments.",
     stub("Top-bar variants — large and inline titles, leading/trailing items, and the flat scrolled state.")),
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
# Rasters are named for the heading that wants them, so a heading that stops being Exposure
# leaves its PNG behind — and publish copies whatever is in here. Regenerated every build.
import shutil as _shutil; _shutil.rmtree(OUT / "titles", ignore_errors=True)
# Content-hashed filename: a reader holding a cached stylesheet can never pair it with
# newer markup. Pages serves site.css with max-age=600, which is exactly long enough to
# show a half-styled page after a nav change.
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
shutil.copyfile(ROOT / ".context/hero.jpg", OUT / "hero.jpg")
shutil.rmtree(OUT / "sheets", ignore_errors=True)
(OUT / "sheets").mkdir()
for _f in FIG:
    shutil.copyfile(SHEETS_DIR / f"{_f}.png", OUT / "sheets" / f"{_f}.png")
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
# A page may carry its own extra CSS as a fifth field — Buttons needs the two iOS system
# colours that a Heidi token has not replaced yet.
for href, title, lede, content, *extra in PAGES:
    markup = page(href, title, lede, content, extra[0] if extra else "")
    markup = apply_overrides(href, markup)
    # Last line of the debug rule: whatever slipped past the corpus and token filters is
    # caught here, before it is written — a published page is a permanent one.
    assert_no_debug(href, markup)
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
