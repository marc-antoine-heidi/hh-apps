#!/usr/bin/env python3
"""Snapshots the pre-APP-8407 colour situation into .context/legacy-tokens.json.

The Problems page is generated from this file rather than from git, so the site
builds anywhere and the "before" numbers stay frozen at the merge base. Re-run
only if the merge base moves:

    python3 .context/snapshot-legacy-tokens.py
"""
import json, pathlib, re, subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / ".context/legacy-tokens.json"


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True, cwd=ROOT).stdout


BASE = sh("git", "merge-base", "origin/develop", "HEAD").strip()
print(f"base {BASE}")

# ---------------------------------------------------------------- HHColors, as it was
sem_src = sh("git", "show", f"{BASE}:HeidiNative/Common/Theme/HHColors.swift")
body = sem_src[sem_src.index("enum HHColors {"):]
tokens = []
for m in re.finditer(r"static let (\w+) = HHColorPair\((.*?)\)\n", body, re.S):
    name, blk = m.group(1), m.group(2)
    lm = re.search(r'light: "([0-9A-Fa-f]{6})"', blk)
    dm = re.search(r'dark: "([0-9A-Fa-f]{6})"', blk)
    if not (lm and dm):
        continue
    la = re.search(r"lightAlpha: ([\d.]+)", blk)
    da = re.search(r"darkAlpha: ([\d.]+)", blk)
    al = re.search(r"\balpha: ([\d.]+)", blk)
    A = lambda x: float(x.group(1)) if x else 1.0
    tokens.append(dict(n=name, l=lm.group(1).upper(), d=dm.group(1).upper(),
                       la=A(al) if al else A(la), da=A(al) if al else A(da)))

# ---------------------------------------------------------------- the asset catalogue
def channel(v):
    v = v.strip()
    return int(v, 16) if v.startswith("0x") else int(round(float(v) * 255))


def hexof(c):
    return "%02X%02X%02X" % (channel(c["red"]), channel(c["green"]), channel(c["blue"]))


tree = sh("git", "ls-tree", "-r", BASE, "--name-only").splitlines()
colorsets = {}
for p in tree:
    if not (p.startswith("HeidiNative/Assets.xcassets") and p.endswith(".colorset/Contents.json")):
        continue
    setname = p.split("/")[-2][: -len(".colorset")]
    light = dark = None
    for c in json.loads(sh("git", "show", f"{BASE}:{p}")).get("colors", []):
        comp = c.get("color", {}).get("components")
        if not comp:
            continue
        if c.get("appearances"):
            dark = hexof(comp)
        else:
            light = hexof(comp)
    if light:
        colorsets[setname[0].lower() + setname[1:]] = [light, dark or light]

# ---------------------------------------------------------------- how each spelling was used
swift = [p for p in tree
         if p.startswith("HeidiNative/") and p.endswith(".swift") and "DebugScreens" not in p]
src = "\n".join(sh("git", "show", f"{BASE}:{p}") for p in swift)

ASSET_SYMBOL = re.compile(r"\b(?:Color|UIColor)\.([A-Za-z][A-Za-z0-9]*)\b")
asset_refs = sum(1 for m in ASSET_SYMBOL.finditer(src) if m.group(1) in colorsets)
systems = dict(
    hhcolors=len(re.findall(r"\bHHColors\.\w+", src)),
    catalog=asset_refs + len(re.findall(r'Color\("\w+"\)', src)),
    componentskit=len(re.findall(r"\bUniversalColor\.\w+", src)),
    system=len(re.findall(r"\bColor\.(?:gray|blue|red|green|orange|yellow|white|black|secondary|primary)\b", src)),
)

# ---------------------------------------------------------------- names both systems define
by_name = {t["n"]: t for t in tokens}
collisions = []
for name in sorted(set(by_name) & set(colorsets)):
    t, a = by_name[name], colorsets[name]
    cap = name[0].upper() + name[1:]
    collisions.append(dict(
        n=name, hh=[t["l"], t["d"]], asset=a,
        agrees=[t["l"], t["d"]] == a,
        useHH=len(re.findall(r"\bHHColors\." + name + r"\b", src)),
        useAsset=(len(re.findall(r"\b(?:Color|UIColor)\." + name + r"\b", src))
                  + len(re.findall(r'Color\("' + cap + r'"\)', src))),
    ))
collisions.sort(key=lambda c: (c["agrees"], -(c["useHH"] + c["useAsset"])))

OUT.write_text(json.dumps(dict(base=BASE, tokens=tokens, colorsets=colorsets,
                               systems=systems, collisions=collisions), indent=1))
print(f"{len(tokens)} tokens · {len(colorsets)} colorsets · {len(collisions)} colliding names")
print(f"systems {systems}")
print(f"wrote {OUT}")
