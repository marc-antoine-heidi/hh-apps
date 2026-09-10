#!/usr/bin/env python3
"""Build and check the Pages checkout; publish only when --publish is supplied."""
import argparse
from pathlib import Path
import subprocess
import sys

site = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ios-repo', type=Path, required=True)
parser.add_argument('--publish', action='store_true', help='Commit and push this reviewed build to main')
parser.add_argument('--dry-run', action='store_true', help='Build and show changes without publishing (default)')
args = parser.parse_args()
if args.publish and args.dry_run:
    parser.error('--publish and --dry-run are mutually exclusive')
subprocess.run([sys.executable, str(site / 'scripts/build-site.py'), '--ios-repo', str(args.ios_repo.resolve())], check=True)
strays = [str(p.relative_to(site)) for p in site.rglob('*')
          if p.suffix.lower() in {'.otf', '.ttf', '.woff', '.woff2'} and p.name != 'Inter.ttf']
if strays:
    sys.exit(f'Licensed font binaries would be published: {strays}')
subprocess.run(['git', 'diff', '--stat'], cwd=site, check=True)
subprocess.run(['git', 'status', '--short'], cwd=site, check=True)
if not args.publish:
    print('Build verified. Use --publish from main to publish directly.')
    sys.exit(0)
branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=site, text=True).strip()
if branch != 'main':
    sys.exit('Run the publishing command from main.')
origin = subprocess.check_output(['git', 'remote', 'get-url', 'origin'], cwd=site, text=True).strip()
if origin.removesuffix('.git') not in {'https://github.com/marc-antoine-heidi/hh-apps', 'git@github.com:marc-antoine-heidi/hh-apps'}:
    sys.exit(f'Unexpected publishing repository: {origin}')
revision = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=args.ios_repo, text=True).strip()
subprocess.run(['git', 'add', '-A'], cwd=site, check=True)
if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=site).returncode:
    subprocess.run(['git', 'commit', '-m', f'Sync native design system from iOS {revision}'], cwd=site, check=True)
subprocess.run(['git', 'push', 'origin', 'main'], cwd=site, check=True)
print('Published https://marc-antoine-heidi.github.io/hh-apps/')
