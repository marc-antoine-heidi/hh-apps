#!/usr/bin/env python3
"""Renames the green status to "Migrated" and moves the status key into the sidebar.

    python3 .context/apply-status-legend-sidebar.py

The key explains the dots in the nav, so it belongs beside them rather than as a footer on
one card of one page. It sticks to the bottom of the panel: on a short window the nav
scrolls behind it and the key stays readable.

Idempotent and re-runnable: a parallel session edits this generator every half-minute and
its writes silently revert hand edits, so each step skips when it is already applied.
"""
import pathlib
import re
import sys

GEN = pathlib.Path(__file__).resolve().parent / "build-design-system-site.py"
src = GEN.read_text()
before = src
did, skipped = [], []


def step(name, marker, old, new, count=1):
    global src
    if marker in src:
        skipped.append(name)
        return
    if old not in src:
        sys.exit(f"anchor for {name!r} not found — the generator moved, re-read it")
    src = src.replace(old, new, count)
    did.append(name)


# ---- 1. Green is "Migrated". The other two keep their labels.
step("migrated label", '"live": "Migrated"',
     'STATUS_LABEL = {"live": "Live", "wip": "WIP", "todo": "To do"}',
     'STATUS_LABEL = {"live": "Migrated", "wip": "WIP", "todo": "To do"}')

step("migrated in comment", "claiming to be Migrated",
     "status rather than silently claiming to be Live;",
     "status rather than silently claiming to be Migrated;")

# ---- 2. Off the Foundations card. The meanings survive as the dots' tooltips, so the
#         assert pairing every status with an explanation still buys something.
LEGEND_CARD = """      # A key, not a section: it explains one column of the table above it, so it rides in
      # the same card as a footer rather than taking a card of its own.
      + '<div class="stfoot">'
      + "".join(f'<span class="stkey">{status_pill(st)}'
                f'<em>{STATUS_MEANING[st]}</em></span>' for st in STATUS_LABEL)
      + '</div></div>'
"""
def remove(name, old, new):
    """A deletion has no marker of its own — absence of the old text is the marker."""
    global src
    if old not in src:
        skipped.append(name)
        return
    src = src.replace(old, new, 1)
    did.append(name)


remove("legend off the card", LEGEND_CARD, "      + '</div>'\n")

# ---- 3. Into the sidebar, under the nav lists.
step("legend in sidenav", 'class="stleg"',
     '        out.append("</ul>")\n    return "".join(out)',
     '        out.append("</ul>")\n'
     '    # Last, and sticky: it is a key to the dots above it, not a nav destination.\n'
     '    out.append(\'<div class="stleg">\'\n'
     '               + "".join(f\'<span title="{STATUS_MEANING[st]}">\'\n'
     '                         f\'<i class="dot {st}"></i>{STATUS_LABEL[st]}</span>\'\n'
     '                         for st in STATUS_LABEL)\n'
     '               + \'</div>\')\n'
     '    return "".join(out)')

# ---- 4. Styling. Bleeds to the panel edges so the nav cannot show through as it scrolls
#         behind; the negative bottom offset is the panel's own 16px padding, which sticky
#         measures from the scrollport rather than the content box.
OLD_CSS = """.stfoot{display:flex;flex-wrap:wrap;gap:7px 18px;align-items:center;margin-top:18px;
padding-top:12px;border-top:1px solid rgba(33,18,23,.08)}
.stkey{display:inline-flex;align-items:center;gap:6px}
.stfoot .pstat{font-size:10px;gap:5px;padding:1px 7px 1px 6px}
.stfoot .pstat i{width:5px;height:5px}
.stkey em{font-style:normal;font-size:11.5px;color:#A98993}
"""
NEW_CSS = """/* status key — sticky to the foot of the panel, opaque so the nav scrolls behind it
   rather than through it. The meanings are the title attributes. */
.stleg{position:sticky;bottom:-16px;z-index:2;margin:18px -16px -16px;padding:9px 16px 11px;
background:#F9F4F1;border-top:1px solid rgba(33,18,23,.08);
display:flex;flex-wrap:wrap;gap:3px 10px}
.stleg span{display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:500;
letter-spacing:0;color:#A98993;cursor:default}
.stleg .dot{width:6px;height:6px}
"""
step("legend css", ".stleg{", OLD_CSS, NEW_CSS)

if src != before:
    GEN.write_text(src)
print(f"applied: {did or 'nothing'}")
print(f"already present: {skipped or 'none'}")
