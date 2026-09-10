#!/usr/bin/env python3
"""Rebuild this Pages checkout from a chosen iOS checkout and verify the result."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ios-repo', type=Path, required=True)
parser.add_argument('--out', type=Path, help='Optional separate output directory')
args = parser.parse_args()
site = Path(__file__).resolve().parent.parent
out = args.out.resolve() if args.out else site
out.mkdir(parents=True, exist_ok=True)
environment = dict(os.environ, HH_SITE_SOURCE_ROOT=str(args.ios_repo.resolve()),
                   HH_SITE_CONTEXT=str(site / '_generator'), HH_SITE_OUT=str(out))
for name in ['build-design-system-site.py', 'check-design-system-site.py']:
    subprocess.run([sys.executable, str(site / '_generator' / name)], env=environment, check=True)
