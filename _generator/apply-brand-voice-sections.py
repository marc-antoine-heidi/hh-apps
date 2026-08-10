#!/usr/bin/env python3
"""Adds the Brand Book's Persona, Do's & Don'ts and Tone-of-voice sections to Who we are.

    python3 .context/apply-brand-voice-sections.py

Idempotent and re-runnable on purpose. A parallel session edits the same generator every
half-minute or so and its writes silently revert edits made by hand, so every step below
skips if its marker is already present and anchors on text that survives their churn.
Re-run after any build that comes back missing a section, then check the built HTML.
"""
import pathlib
import re
import sys

GEN = pathlib.Path(__file__).resolve().parent / "build-design-system-site.py"
src = GEN.read_text()
before = src
did, skipped = [], []


def step(name, marker, fn):
    global src
    if marker in src:
        skipped.append(name)
        return
    out = fn(src)
    if out == src:
        sys.exit(f"anchor for {name!r} not found — the generator moved, re-read it")
    src = out
    did.append(name)


def block(name, pattern, text, anchor):
    """Insert a whole block, replacing any earlier version of itself.

    A plain skip-if-present would leave a stale copy in place the moment the block's own
    text changes, which is how a fixed bug comes back on the next run."""
    global src
    if text in src:
        skipped.append(name)
        return
    found = re.search(pattern, src, re.S)
    if found:
        src = src[:found.start()] + src[found.end():]
        name += " (replaced stale)"
    if anchor not in src:
        sys.exit(f"anchor for {name!r} not found — the generator moved, re-read it")
    src = src.replace(anchor, text + anchor, 1)
    did.append(name)


# ---- 1. Forest ramp, for the "do" tint. The other ramps are aliased the same way.
step("forest ramp", "_FOREST = dict",
     lambda s: s.replace('_BARK = dict(ramps["HHBark"])',
                         '_BARK = dict(ramps["HHBark"])\n'
                         '_FOREST = dict(ramps["HHForest"])', 1))

# ---- 2. The three transcriptions. Placed before REGISTERS so they sit with the other
#         brand constants rather than next to the page that renders them.
CONSTANTS = '''# The persona is the premise the four principles hang off — each one is a description of how
# this one person would say a thing — so it reads before them, not as a footnote after.
PERSONA = ("Your most trusted clinician.",
           "Heidi speaks with the presence of the clinician you&rsquo;d trust most: the one "
           "who makes sense of complexity without effort, who gives reassurance in a single "
           "word, and whose warmth shows in the smallest moments &mdash; always by your side. "
           "This is a voice that carries knowledge with compassion, guidance with humanity, "
           "and leaves you certain you&rsquo;re in safe hands.")

'''

# ---- 3. The markup helper. A function, so wiring it into pwho is a one-line edit and their
#         next rewrite of that block has one line of mine to clobber instead of forty.
HELPER = '''

def brand_voice_extra():
    """Persona, do/don't pairs and per-audience tone — the rest of the Brand Book's voice
    section. Split out so pwho takes one line of it."""
    out = ['<h2>Do&rsquo;s and don&rsquo;ts<span class="ct">8</span></h2>',
           '<p class="lede sub">The Brand Book&rsquo;s own examples, kept word for word. '
           'Two per principle &mdash; this is the part a sentence can be checked against.</p>']
    for principle, pairs in DODONT:
        out.append(f'<h3>{principle}</h3>')
        for rule, do, dont in pairs:
            out.append(f'<div class="dd"><em class="eyebrow">{rule}</em>'
                       f'<div class="ddpair"><p class="do">{do}</p>'
                       f'<p class="dont">{dont}</p></div></div>')
    out.append(f'<h2>Tone of voice<span class="ct">{len(TONE)}</span></h2>')
    out.append('<p class="lede sub">Same voice, different weighting. The app speaks to two '
               'of these; the rest are here because a line written for any of them still '
               'has to sound like the same product.</p>')
    for who, in_app, purpose, dials in TONE:
        # Inside the <b>, which is display:block — outside it the pill takes its own line.
        # Its own class rather than .atag: that one belongs to the audit banners.
        tag = '<span class="inapp">in the app</span>' if in_app else ''
        out.append(f'<div class="bstat"><em class="eyebrow">{who}</em>'
                   f'<div><b>{purpose}{tag}</b><dl class="dial">'
                   + "".join(f'<dt>{t}</dt><dd>{d}</dd>' for t, d in dials)
                   + '</dl></div></div>')
    return "".join(out)
'''

step("brand constants", "PERSONA = (",
     lambda s: s.replace('REGISTERS = [("Aesop"', CONSTANTS + 'REGISTERS = [("Aesop"', 1))

# Must land above pwho, which calls it while the module is still executing.
step("markup helper", "def brand_voice_extra",
     lambda s: s.replace('\npwho = (', HELPER + '\n\npwho = (', 1))

# ---- 4. Persona ahead of the principles, and the two new sections after them.
step("persona in pwho", "PERSONA[0]",
     lambda s: s.replace(
         "    + '<h2>Voice</h2>'",
         "    + '<h2>Voice</h2>'\n"
         "    + f'<div class=\"bstat\"><em class=\"eyebrow\">Persona</em>'\n"
         "      f'<div><b>{PERSONA[0]}</b><p>{PERSONA[1]}</p></div></div>'", 1))

step("sections in pwho", "+ brand_voice_extra())",
     lambda s: s.replace(
         "              for i, (name, rule, simile) in enumerate(VOICE)))",
         "              for i, (name, rule, simile) in enumerate(VOICE))\n"
         "    + brand_voice_extra())", 1))

# ---- 5. Styling. Appended as its own CSS += so it never lands inside the block the other
#         session is editing; must precede the hash that names the stylesheet.
CSS_BLOCK = '''
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
        '.ddpair .do::before{content:"\\\\2713  ";font-weight:600}'
        '.ddpair .dont::before{content:"\\\\2717  ";font-weight:600}'
        ".dial{margin:11px 0 0;display:grid;grid-template-columns:auto 1fr;gap:3px 12px}"
        ".dial dt{font-size:13px;font-weight:500;color:#211217}"
        ".dial dd{margin:0;font-size:13px;line-height:1.5;color:#755760}"
        f".inapp{{display:inline-block;margin-left:10px;vertical-align:5px;padding:3px 9px;"
        f"border-radius:999px;font-size:11px;font-weight:500;letter-spacing:0;"
        f"background:#{_SUN['s200']};color:#{_BARK['s800']}}}"
        "@media(max-width:700px){.ddpair{grid-template-columns:1fr}"
        ".dial{grid-template-columns:1fr;gap:0 0}.dial dd{margin:0 0 7px}}")

'''

step("do/don't css", ".ddpair{",
     lambda s: s.replace('CSS_HREF = f"site.', CSS_BLOCK + 'CSS_HREF = f"site.', 1))

if src != before:
    GEN.write_text(src)
print(f"applied: {did or 'nothing'}")
print(f"already present: {skipped or 'none'}")
