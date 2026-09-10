#!/usr/bin/env python3
"""Compile the actual iOS package and export its tokens and native previews."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import os
import struct


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def uncomment(source):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)


def prepare(repo, work, site):
    source = repo / 'DesignSystem/Sources/DesignSystem'
    groups = {}
    for filename, names in {
        'HHColors.swift': ['HHColors'],
        'HHColorPrimitives.swift': ['HHSand', 'HHBark', 'HHSky', 'HHForest', 'HHSunlight', 'HHNeutral', 'HHGreen', 'HHRed', 'HHOrange', 'HHBlue', 'HHPro'],
        'HHSpacing.swift': ['HHSpacing', 'HHSizing', 'HHBaselineOffset'],
        'HHRadius.swift': ['HHRadius'], 'HHOpacity.swift': ['HHOpacity'],
        'HHMarkdownUnorderedListMarker.swift': ['HHMarkdownUnorderedListMarker'],
    }.items():
        text = uncomment((source / 'Theme' / filename).read_text())
        for name in names:
            body = re.search(r'public enum ' + name + r'\b[^\{]*\{(.*?)\n\}', text, re.S)
            if not body:
                raise ValueError(f'Missing token family: {name}')
            symbols = re.findall(r'public static let (\w+)\s*(?::[^=]+)?=', body[1])
            if not symbols:
                raise ValueError(f'Empty token family: {name}')
            groups[name] = [symbol for symbol in symbols if 'debug' not in symbol.lower()]
    scalar = {'HHSpacing', 'HHSizing', 'HHBaselineOffset', 'HHRadius', 'HHOpacity'}
    for path in (source / 'Theme').glob('*.swift'):
        for match in re.finditer(r'public enum (\w+)[^{]*\{(.*?)\n\}', uncomment(path.read_text()), re.S):
            if 'public static let' in match[2] and match[1] not in groups and match[1] != 'HHMarkdownTextStyle':
                raise ValueError(f'New token family needs an export contract: {match[1]}')
    shadows = re.findall(r'public static let (\w+) = HeidiShadowStyle', uncomment((source / 'View+HeidiShadow.swift').read_text()))
    shadows = [name for name in shadows if 'debug' not in name.lower()]
    expressions = []
    for family, symbols in groups.items():
        colors = family not in scalar and family != 'HHMarkdownUnorderedListMarker'
        entries = ',\n'.join(f'"{name}": ' + (f'pair({family}.{name})' if colors else f'{family}.{name}') for name in symbols)
        expressions.append(f'"{family}": [{entries}]')
    generated = '''import DesignSystem
import UIKit

@MainActor
func exportTokens() throws -> Data {
    func pair(_ color: HHColorPair) -> [String: Any] {
        ["light": color.light, "dark": color.dark, "lightAlpha": color.lightAlpha, "darkAlpha": color.darkAlpha]
    }
    var result: [String: Any] = [
''' + ',\n'.join(expressions) + ''']
    let traits = UITraitCollection(preferredContentSizeCategory: .large)
    result["HHSize"] = Dictionary(uniqueKeysWithValues: HHSize.allCases.map { (String(describing: $0), $0.dimension) })
    result["HHTextStyle"] = Dictionary(uniqueKeysWithValues: HHTextStyle.allCases.map { style in
        let font = style.uiFont(compatibleWith: traits)
        precondition(font.fontName == style.fontName, "Missing font: \\(style.fontName), resolved \\(font.fontName)")
        return (String(describing: style), ["size": style.size, "lineHeight": style.lineHeight,
            "lineHeightMultiple": style.lineHeightMultiple, "trackingPercentage": style.trackingPercentage,
            "letterSpacing": style.letterSpacing, "fontName": style.fontName,
            "family": font.familyName, "resolvedFontName": font.fontName,
            "nativeLineHeight": font.lineHeight] as [String: Any])
    })
    result["HHMarkdownTextStyle"] = Dictionary(uniqueKeysWithValues: HHMarkdownTextStyle.allCases.map { style in
        let font = style.uiFont(compatibleWith: traits)
        return (String(describing: style), ["size": style.size, "lineHeightMultiple": style.lineHeightMultiple,
            "trackingPercentage": style.trackingPercentage, "fontName": font.fontName] as [String: Any])
    })
    result.merge(extraTokens(), uniquingKeysWith: { _, new in new })
    return try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
}
'''
    app = work / 'Sources'
    app.mkdir(parents=True)
    generated += '\n@MainActor\nfunc shadowTokens() -> [(String, HeidiShadowStyle)] {\n[' + ',\n'.join(f'("{name}", .{name})' for name in shadows) + ']\n}\n'
    (app / 'GeneratedTokens.swift').write_text(generated)
    for file in (site / 'scripts/ios-preview').glob('*.swift'):
        shutil.copy2(file, app / file.name)
    fonts = app / 'Fonts'
    shutil.copytree(repo / 'HeidiNative/Resources/Fonts', fonts)
    # The package's image helpers load from the main app bundle.
    for assets in (repo / 'HeidiNative').glob('*.xcassets'):
        shutil.copytree(assets, app / assets.name)
    spec = {
        'name': 'IOSDesignPreview',
        'packages': {'DesignSystem': {'path': str(repo / 'DesignSystem')}},
        'targets': {'IOSDesignPreview': {
            'type': 'application', 'platform': 'iOS', 'deploymentTarget': '17.0',
            'sources': [str(app)],
            'dependencies': [{'package': 'DesignSystem'}],
            'settings': {'base': {'PRODUCT_BUNDLE_IDENTIFIER': 'com.heidi.design-preview', 'SWIFT_VERSION': '5.9', 'CODE_SIGNING_ALLOWED': 'NO', 'TARGETED_DEVICE_FAMILY': '1,2'}},
            'info': {'path': str(work / 'Info.plist'), 'properties': {'UILaunchScreen': {}, 'UIAppFonts': [p.name for p in fonts.iterdir() if p.suffix in ['.otf', '.ttf']], 'UISupportedInterfaceOrientations': ['UIInterfaceOrientationPortrait']}}
        }}
    }
    (work / 'project.json').write_text(json.dumps(spec, indent=2))
    tracked = sorted(source.rglob('*.swift')) + [repo / 'DesignSystem/Package.swift', repo / 'DesignSystem/Package.resolved']
    resources = sorted(p for base in [repo / 'HeidiNative/Resources/Fonts', *list((repo / 'HeidiNative').glob('*.xcassets'))] for p in base.rglob('*') if p.is_file())
    metadata = {
        'repository': 'https://github.com/oscerai/HeidiNative-iOS',
        'revision': run('git', '-C', str(repo), 'rev-parse', 'HEAD'),
        'sourceDirty': bool(run('git', '-C', str(repo), 'status', '--porcelain', '--', 'DesignSystem', 'HeidiNative/Resources/Fonts', 'HeidiNative/Assets.xcassets', 'HeidiNative/Lucide-Icons.xcassets')),
        'sourceFiles': {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked + resources},
        'components': [{
            'name': m[1], 'path': str(p.relative_to(repo)),
        } for p in tracked if p.suffix == '.swift' for m in re.finditer(r'^public struct (\w+)(?:<[^\n]+?>)?\s*:\s*(?:View|UIViewRepresentable|UIViewControllerRepresentable|ToolbarContent|ButtonStyle|PrimitiveButtonStyle|LabelStyle)\b', uncomment(p.read_text()), re.M)],
    }
    return metadata


def verify_export(site):
    metadata = json.loads((site / 'lib/ios/source.generated.json').read_text())
    manifest = json.loads((site / 'lib/ios/previews.generated.json').read_text())
    tokens = json.loads((site / 'lib/ios/tokens.generated.json').read_text())
    if metadata.get('generatorHash') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise SystemExit('The exporter changed; regenerate the iOS export.')
    for path, digest in metadata['fixtureFiles'].items():
        if not (site / path).is_file() or hashlib.sha256((site / path).read_bytes()).hexdigest() != digest:
            raise SystemExit(f'Native fixture changed: {path}')
    if hashlib.sha256((site / 'lib/ios/tokens.generated.json').read_bytes()).hexdigest() != metadata.get('tokenHash'):
        raise SystemExit('Generated token data was modified; regenerate it from Swift.')
    if set(metadata['fixtureFiles']) != {str(p.relative_to(site)) for p in (site / 'scripts/ios-preview').glob('*.swift')}:
        raise SystemExit('Native fixture inventory changed; regenerate the iOS export.')
    configurations = {'light', 'dark', 'large-text', 'rtl', 'wide'}
    samples = {}
    for preview in manifest['previews']:
        path = site / 'public/ios/native' / preview['file']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != preview.get('sha256'):
            raise SystemExit(f'Missing or modified capture: {preview["file"]}')
        samples.setdefault(preview['id'], set()).add(preview['configuration'])
    if not samples or any(value != configurations for value in samples.values()):
        raise SystemExit('Native environment coverage is incomplete.')
    covered = {name for p in manifest['previews'] for name in p['components']}
    missing = {c['name'] for c in metadata['components']} - covered - set(metadata['previewExclusions'])
    if missing:
        raise SystemExit(f'Components missing native specimens: {sorted(missing)}')
    if not all('type-' + role in samples for role in tokens['HHTextStyle']):
        raise SystemExit('Semantic typography specimens are incomplete.')
    print(f'Verified {len(manifest["previews"])} capture checksums, native environments and component coverage.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ios-repo', type=Path)
    parser.add_argument('--verify', action='store_true', help='Verify exported artifacts without Xcode or an iOS checkout')
    parser.add_argument('--check', action='store_true', help='Fail if the committed export differs from current iOS sources')
    parser.add_argument('--device', help='Explicit simulator UDID (never a physical device)')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    site = Path(__file__).resolve().parent.parent
    if args.verify:
        verify_export(site)
        return
    if not args.ios_repo:
        parser.error('--ios-repo is required for generation and source freshness checks')
    repo = args.ios_repo.resolve()
    if args.check:
        data = json.loads((site / 'lib/ios/source.generated.json').read_text())
        changed = [p for p, digest in data['sourceFiles'].items() if not (repo / p).is_file() or hashlib.sha256((repo / p).read_bytes()).hexdigest() != digest]
        changed += [p for p, digest in data.get('fixtureFiles', {}).items() if not (site / p).is_file() or hashlib.sha256((site / p).read_bytes()).hexdigest() != digest]
        known = set(data['sourceFiles'])
        current = [*list((repo / 'DesignSystem/Sources/DesignSystem').rglob('*.swift')), *[p for base in [repo / 'HeidiNative/Resources/Fonts', *list((repo / 'HeidiNative').glob('*.xcassets'))] for p in base.rglob('*') if p.is_file()]]
        new = [str(p.relative_to(repo)) for p in current if str(p.relative_to(repo)) not in known]
        new += [str(p.relative_to(site)) for p in (site / 'scripts/ios-preview').glob('*.swift') if str(p.relative_to(site)) not in data.get('fixtureFiles', {})]
        if changed or new:
            raise SystemExit('iOS docs are stale: ' + ', '.join(changed + new))
        verify_export(site)
        print('iOS source, resource and fixture fingerprints match the committed export.')
        return
    if not args.device:
        parser.error('--device is required when generating previews')
    work = Path(tempfile.mkdtemp(prefix='heidi-ios-docs-'))
    print(f'Build and export directory: {work}', flush=True)
    metadata = prepare(repo, work, site)
    metadata['fixtureFiles'] = {str(p.relative_to(site)): hashlib.sha256((work / 'Sources' / p.name).read_bytes()).hexdigest() for p in sorted((site / 'scripts/ios-preview').glob('*.swift'))}
    (work / 'source.json').write_text(json.dumps(metadata, indent=2))
    run('xcodegen', 'generate', '--spec', str(work / 'project.json'), '--project', str(work))
    if args.prepare_only:
        return
    devices = json.loads(run('xcrun', 'simctl', 'list', 'devices', 'available', '-j'))['devices']
    device = next((d for entries in devices.values() for d in entries if d['udid'] == args.device), None)
    if not device:
        raise ValueError('The specified simulator is unavailable')
    subprocess.run(['xcodebuild', '-project', str(work / 'IOSDesignPreview.xcodeproj'), '-scheme', 'IOSDesignPreview', '-destination', f'platform=iOS Simulator,id={args.device}', '-derivedDataPath', str(work / 'build'), '-skipMacroValidation', 'build'], check=True, stdout=(work / 'build.log').open('w'), stderr=subprocess.STDOUT)
    state = json.loads((work / 'build/SourcePackages/workspace-state.json').read_text())
    resolved = {d['packageRef']['identity']: d['state']['checkoutState'] for d in state['object']['dependencies']}
    pinned = {p['identity']: p['state'] for p in json.loads((repo / 'DesignSystem/Package.resolved').read_text())['pins']}
    if {name: value.get('revision') for name, value in resolved.items()} != {name: value.get('revision') for name, value in pinned.items()}:
        raise ValueError('Preview dependency revisions differ from DesignSystem/Package.resolved')
    metadata['dependencies'] = resolved
    print(f'Build succeeded: {work / "build.log"}', flush=True)
    lock = Path('/tmp') / f'maestro-driver-{args.device}.lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise SystemExit(f'Simulator is in use: {lock}. Retry after its owner releases it.')
    (lock / 'pid').write_text(str(os.getpid()))
    try:
        if device['state'] != 'Booted':
            run('xcrun', 'simctl', 'boot', args.device)
        subprocess.run(['xcrun', 'simctl', 'bootstatus', args.device, '-b'], check=True)
        app = work / 'build/Build/Products/Debug-iphonesimulator/IOSDesignPreview.app'
        run('xcrun', 'simctl', 'install', args.device, str(app))
        container = Path(run('xcrun', 'simctl', 'get_app_container', args.device, 'com.heidi.design-preview', 'data'))
        output = container / 'Documents/ios-export'
        if output.exists():
            shutil.rmtree(output)
        run('xcrun', 'simctl', 'launch', '--terminate-running-process', args.device, 'com.heidi.design-preview')
        print(f'Export started: {output}', flush=True)
        (work / 'container.txt').write_text(str(container))
        deadline = time.monotonic() + 240
        while not (output / 'complete.json').exists():
            if time.monotonic() > deadline:
                raise SystemExit(f'Export did not finish within four minutes. Inspect the running app and {output}.')
            time.sleep(1)
        manifest = json.loads((output / 'complete.json').read_text())
        for preview in manifest['previews']:
            png = (output / preview['file']).read_bytes()
            preview['sha256'] = hashlib.sha256(png).hexdigest()
            expected = (int(preview['width'] * preview['scale']), int(preview['height'] * preview['scale']))
            if png[:8] != b'\x89PNG\r\n\x1a\n' or struct.unpack('>II', png[16:24]) != expected:
                raise ValueError(f'Invalid capture dimensions: {preview["file"]}')
        changed_during_export = [p for p, digest in metadata['sourceFiles'].items() if not (repo / p).is_file() or hashlib.sha256((repo / p).read_bytes()).hexdigest() != digest]
        if changed_during_export:
            raise ValueError(f'iOS sources changed during export; run again: {changed_during_export}')
        covered = {name for p in manifest['previews'] for name in p['components']}
        excluded = {'ThemeChangeObserver': 'Infrastructure observer; no visible content of its own.'}
        missing = [c['name'] for c in metadata['components'] if c['name'] not in covered and c['name'] not in excluded]
        if missing:
            raise ValueError(f'Add native specimens for new components: {missing}')
        metadata['previewExclusions'] = excluded
        destination = site / 'public/ios/native'
        staging = Path(tempfile.mkdtemp(prefix='native-staging-', dir=site / 'public/ios'))
        for preview in manifest['previews']:
            shutil.copy2(output / preview['file'], staging / preview['file'])
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
        (site / 'lib/ios/tokens.generated.json').write_bytes((output / 'tokens.json').read_bytes())
        (site / 'lib/ios/previews.generated.json').write_text(json.dumps(manifest, indent=2) + '\n')
        metadata['tokenHash'] = hashlib.sha256((output / 'tokens.json').read_bytes()).hexdigest()
        metadata['generatorHash'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (site / 'lib/ios/source.generated.json').write_text(json.dumps(metadata, indent=2) + '\n')
        print(f'Synced {len(manifest["previews"])} native captures and {len(metadata["components"])} public component records.', flush=True)
    finally:
        (lock / 'pid').unlink(missing_ok=True)
        lock.rmdir()


if __name__ == '__main__':
    main()
