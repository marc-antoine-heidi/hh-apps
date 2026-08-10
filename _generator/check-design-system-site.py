#!/usr/bin/env python3
"""Sweeps the built site for the failure modes that make a page render as bare HTML.

    python3 .context/check-design-system-site.py

Run by publish-design-system-site.py before every push. Catches:
  · a page pointing at a stylesheet that isn't in the output (the cache-bust hazard)
  · a stylesheet missing the rules the shell markup depends on
  · a page missing the shell markup the stylesheet targets
  · any broken internal link, anchor or asset reference
"""
import re, sys, pathlib

OUT = pathlib.Path(__file__).resolve().parent / "design-system"
# Rules the page shell cannot render without.
REQUIRED_RULES = [".side", ".col{", ".navsec", "main{", "table{", ".chip"]

pages = sorted(OUT.glob("*.html"))
assets = {p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file()}
fails, checked = [], 0

if not pages:
    sys.exit("no pages in the output — run the builder first")

for css in OUT.glob("*.css"):
    text = css.read_text()
    missing = [r for r in REQUIRED_RULES if r not in text]
    if missing:
        fails.append(f"{css.name}: stylesheet is missing rules {missing}")

for p in pages:
    h = p.read_text()
    redirect = 'http-equiv="refresh"' in h
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)"', h)

    if not sheets:
        fails.append(f"{p.name}: no stylesheet linked — would render as bare HTML")
    for s in sheets:
        checked += 1
        if s.split("?")[0] not in assets:
            fails.append(f"{p.name}: links missing stylesheet {s!r}")

    if not redirect and 'class="side"' not in h:
        fails.append(f"{p.name}: no sidenav shell")
    if not redirect and '<div class="col">' not in h:
        fails.append(f"{p.name}: no content column — sidebar would overlap the page")

    ids = set(re.findall(r'\bid="([^"]+)"', h))
    for href in re.findall(r'href="([^"]+)"', h):
        if href.startswith(("http", "mailto:", "data:")):
            continue
        target, _, frag = href.partition("#")
        if target and target not in assets:
            fails.append(f"{p.name}: dead link -> {href}")
        elif not target and frag and frag not in ids and f"tab-{frag}" not in ids:
            fails.append(f"{p.name}: dead anchor -> #{frag}")
    for src in re.findall(r'src="([^"]+)"', h):
        if not src.startswith(("http", "data:")) and src not in assets:
            fails.append(f"{p.name}: missing asset -> {src}")

# The one licence rule that must never regress.
for f in OUT.rglob("*"):
    if f.suffix.lower() in (".otf", ".ttf") and f.name != "Inter.ttf":
        fails.append(f"licensed font binary in output: {f.name}")

print(f"swept {len(pages)} pages, {checked} stylesheet links, {len(assets)} assets")
if fails:
    print(f"\n{len(fails)} problem(s):")
    for f in fails:
        print("  ·", f)
    sys.exit(1)
print("all pages carry a working stylesheet and shell; no dead links")
