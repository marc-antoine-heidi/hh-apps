#!/usr/bin/env python3
"""Rebuilds the design-system site and publishes it to GitHub Pages.

    python3 .context/publish-design-system-site.py            # build, push, print URL
    python3 .context/publish-design-system-site.py --dry-run   # build + diff, no push

Live at https://marc-antoine-heidi.github.io/hh-colors/ (Pages serves main/ root).

The Exposure typeface is licensed from 205TF under terms that forbid redistributing the
font software, so this script refuses to publish an Exposure binary — the builder
rasterises those specimens instead. Do not remove that check.
"""
import argparse, filecmp, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / ".context/design-system"
WORK = ROOT / ".context/.pages-checkout"
REPO = "git@github.com:marc-antoine-heidi/hh-colors.git"
URL = "https://marc-antoine-heidi.github.io/hh-colors/"

# The toolchain rides along in _generator/ so the site and the thing that built it are one
# artefact. .context/ is gitignored, so without this the generator exists only in whichever
# workspace last touched it and "which copy is canonical" is settled by mtime. Names match
# .context/ exactly: `cp -R _generator/. .context/` restores a working workspace.
GENERATOR = ["build-design-system-site.py", "check-design-system-site.py",
             "publish-design-system-site.py", "snapshot-legacy-tokens.py",
             "apply-brand-voice-sections.py", "apply-principles-h3.py",
             "apply-status-legend-sidebar.py",
             "design-system-README.md", "hhfont-resolution-finding.md",
             "legacy-tokens.json", "design-system-anatomy.png", "logo_product.svg",
             "design-system-anatomy-search.png", "design-system-anatomy-header.png",
             "design-system-anatomy-toast.png", "design-system-anatomy-row.png",
             "lucide-cache", "sheets", "copy-overrides.json", "archetypes", "textures",
             "screens",
             # Every hero asset the build copies. Miss one and a bootstrapped workspace
             # fails on copyfile before it writes a page.
             "hero.mp4", "hero-poster.jpg",
             "who-we-are.mp4", "who-we-are-poster.jpg",
             "who-we-serve.mp4", "who-we-serve-poster.jpg",
             "welcome-closer.jpg"]


def run(*cmd, cwd=None, quiet=False):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if r.returncode:
        sys.exit(f"$ {' '.join(cmd)}\n{r.stdout}{r.stderr}")
    if not quiet and r.stdout.strip():
        print(r.stdout.strip())
    return r.stdout


ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

# A tool added to .context/ but not to GENERATOR would publish a site nobody can rebuild.
loose = sorted(p.name for p in (ROOT / ".context").glob("*.py") if p.name not in GENERATOR)
if loose:
    sys.exit(f"tool(s) missing from GENERATOR, so _generator/ would be incomplete: {loose}")

print("· building from the Swift sources")
run(sys.executable, str(ROOT / ".context/build-design-system-site.py"), quiet=True)

print("· sweeping every page for stylesheet, shell and link integrity")
run(sys.executable, str(ROOT / ".context/check-design-system-site.py"))

print("· syncing the Pages checkout")
if not (WORK / ".git").exists():
    shutil.rmtree(WORK, ignore_errors=True)
    run("git", "clone", "--depth", "1", REPO, str(WORK), quiet=True)
else:
    run("git", "-C", str(WORK), "fetch", "--depth", "1", "origin", "main", quiet=True)
    run("git", "-C", str(WORK), "reset", "--hard", "origin/main", quiet=True)

def same(a, b):
    """filecmp.cmp compares stat signatures for directories, so lucide-cache always
    looks changed. Recurse instead."""
    if not (a.exists() and b.exists()) or a.is_dir() != b.is_dir():
        return False
    if not a.is_dir():
        return filecmp.cmp(a, b, shallow=False)
    names = sorted(p.name for p in a.iterdir())
    return names == sorted(p.name for p in b.iterdir()) and all(same(a / n, b / n) for n in names)


was = WORK / "_generator"
stale = [n for n in GENERATOR
         if (was / n).exists() and not same(was / n, ROOT / ".context" / n)] if was.exists() else []

for item in WORK.iterdir():
    if item.name != ".git":
        shutil.rmtree(item) if item.is_dir() else item.unlink()
shutil.copytree(SITE, WORK, dirs_exist_ok=True)
# Pages runs Jekyll by default, which would skip any future _-prefixed asset.
(WORK / ".nojekyll").write_text("")

gen = WORK / "_generator"
gen.mkdir()
for name in GENERATOR:
    src = ROOT / ".context" / name
    if not src.exists():
        sys.exit(f"generator file is missing from this workspace: {name}")
    shutil.copytree(src, gen / name) if src.is_dir() else shutil.copy2(src, gen / name)
if stale:
    print(f"  _generator/ differs from the published copy — overwriting {', '.join(stale)}")

# The site's licence guard sweeps the build output; this one sweeps everything that will
# actually land in a public repo, including _generator/.
strays = [f.name for f in WORK.rglob("*")
          if f.suffix.lower() in (".otf", ".ttf") and f.name != "Inter.ttf"]
if strays:
    sys.exit(f"licensed font binary would be published: {strays}")

sha = run("git", "-C", str(ROOT), "rev-parse", "--short", "HEAD", quiet=True).strip()
run("git", "-C", str(WORK), "add", "-A", quiet=True)
status = run("git", "-C", str(WORK), "status", "--porcelain", quiet=True)


def links(rev):
    return (f"  {URL}            (may be cached for up to 10 min)"
            f"\n  {URL}?v={rev}   ← share this one; bypasses the cache")


if not status.strip():
    rev = run("git", "-C", str(WORK), "rev-parse", "--short", "HEAD", quiet=True).strip()
    print("· no changes — the live site already matches this build\n" + links(rev))
    sys.exit(0)
print(f"· {len(status.strip().splitlines())} file(s) changed")

if args.dry_run:
    print(run("git", "-C", str(WORK), "diff", "--cached", "--stat", quiet=True))
    sys.exit(0)

run("git", "-C", str(WORK), "commit", "-m",
    f"Rebuild design-system site from heidinative-ios {sha}", quiet=True)
run("git", "-C", str(WORK), "push", "origin", "HEAD:main", quiet=True)

# Pages serves HTML with max-age=600 and no way to override it, so anyone who opened the
# site in the last ten minutes sees the previous build and reasonably concludes the change
# didn't ship. A query string is a separate cache key, so this link is always the new one.
rev = run("git", "-C", str(WORK), "rev-parse", "--short", "HEAD", quiet=True).strip()
print("· published\n" + links(rev))
