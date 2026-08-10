#!/usr/bin/env python3
"""Demotes the Welcome principles' titles from h2 to h3.

    python3 .context/apply-principles-h3.py

They sit inside a card whose own heading is "Principles we work to", so as h2 they were
siblings of the thing they belong to, and exposure_h2() rendered each one as a display-type
raster that competed with it. As h3 they are plain Inter and the hierarchy reads.

Idempotent and re-runnable: a parallel session edits this generator every half-minute and
its writes silently revert hand edits, so each step skips when it is already applied.
"""
import pathlib
import sys

GEN = pathlib.Path(__file__).resolve().parent / "build-design-system-site.py"
src = GEN.read_text()
before = src
did, skipped = [], []


def step(name, marker, old, new):
    global src
    if marker in src:
        skipped.append(name)
        return
    if old not in src:
        sys.exit(f"anchor for {name!r} not found — the generator moved, re-read it")
    src = src.replace(old, new, 1)
    did.append(name)


step("principle markup", "f'<h3>{html.escape(title)}</h3>'",
     "f'<h2>{html.escape(title)}</h2>'", "f'<h3>{html.escape(title)}</h3>'")

# h3's base margin is 22px 0 8px; inside a hairline-separated row that reads as uneven
# padding, which is what this override was for as an h2 too.
step("principle heading css", ".prin h3{",
     ".prin h2{margin:0 0 5px}", ".prin h3{margin:0 0 5px}")

if src != before:
    GEN.write_text(src)
print(f"applied: {did or 'nothing'}")
print(f"already present: {skipped or 'none'}")
