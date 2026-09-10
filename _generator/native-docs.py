"""Native evidence and compiled values inside the existing documentation shell."""
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys


def esc(value):
    return html.escape(str(value), quote=True)


def number(value):
    return f'{value:.4f}'.rstrip('0').rstrip('.') if isinstance(value, float) else str(value)


CONFIGURATIONS = {'light': 'Light · default text', 'dark': 'Dark · default text',
                  'large-text': 'Accessibility text · AX1', 'rtl': 'Right to left · Arabic locale',
                  'wide': 'Wide · 768pt (same simulator)'}

CSS = '''
.native-gallery{margin:24px 0;padding:20px;border:1px solid #E8D7CF;border-radius:16px;min-width:0}
.native-controls{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px}
.native-controls label{display:grid;gap:6px;min-width:0;font-size:12px;flex:1}
.native-controls select{min-width:0;width:100%;font:inherit;font-size:14px;max-width:100%;padding:10px;border:1px solid #DCC6BA;border-radius:8px;background:white;color:#211217}
.native-stage{overflow:auto;max-height:850px;border:1px solid #E8D7CF;border-radius:12px;background:#F9F4F1}
.native-stage img{display:block;max-width:none;height:auto;margin:0 auto}
.native-caption{font-size:13px;line-height:1.6;margin:12px 0 0;overflow-wrap:anywhere}
.native-meta{font-size:13px;line-height:1.6;padding:16px;background:#F9F4F1;border-radius:12px;margin:16px 0}
.native-table-scroll{overflow-x:auto;max-width:100%}.native-table-scroll table{min-width:580px}
.native-colors{display:flex;gap:12px}.native-color{display:flex;align-items:center;gap:8px;padding:8px;border-radius:8px;min-width:160px}
.native-color i{display:block;width:28px;height:28px;border:1px solid currentColor;border-radius:6px;flex-shrink:0}
@media(max-width:700px){.native-controls label{flex-basis:100%}}
.native-group{margin:24px 0}.native-group summary{cursor:pointer;font-weight:500;padding:12px 0}
'''


def gallery(manifest, ids=None):
    previews = [p for p in manifest['previews'] if ids is None or p['id'] in ids]
    assert previews, f'No previews for {ids}'
    if ids is not None:
        previews.sort(key=lambda p: ids.index(p['id']))
    samples = {p['id']: p for p in previews if p['configuration'] == 'light'}
    first = next(iter(samples.values()))
    encoded = esc(json.dumps(previews, separators=(',', ':')))
    image = lambda p: f'public/ios/native/{p["file"]}?v={p["sha256"][:12]}'
    markup = (f'<div class="native-gallery" data-previews="{encoded}"><div class="native-controls">'
              '<label>Example<select data-native-example>'
              + ''.join(f'<option value="{esc(k)}">{esc(v["title"])}</option>' for k, v in samples.items())
              + '</select></label><label>Environment<select data-native-environment>'
              + ''.join(f'<option value="{k}">{v}</option>' for k, v in CONFIGURATIONS.items())
              + '</select></label></div><div class="native-stage">'
              + f'<img src="{image(first)}" width="{first["width"]}" height="{first["height"]}" '
              + f'alt="{esc(first["title"])} · {CONFIGURATIONS["light"]}" loading="lazy"></div>'
              + f'<p class="native-caption" aria-live="polite">{esc(first["title"])} · {first["width"]} × {first["height"]}pt</p>'
              + '<noscript>Enable JavaScript to switch specimens and environments.</noscript></div>')
    return markup + '''<script>(()=>{
const script=document.currentScript,box=script.previousElementSibling;
const previews=JSON.parse(box.dataset.previews),example=box.querySelector('[data-native-example]'),environment=box.querySelector('[data-native-environment]'),image=box.querySelector('img'),caption=box.querySelector('.native-caption');
function show(){const p=previews.find(p=>p.id===example.value&&p.configuration===environment.value);
image.src='public/ios/native/'+p.file+'?v='+p.sha256.slice(0,12);image.width=p.width;image.height=p.height;
image.alt=p.title+' · '+environment.selectedOptions[0].textContent;
caption.textContent=p.title+' · '+p.width+' × '+p.height+'pt · '+p.scale+'× capture'+(p.components.length?' · '+p.components.join(', '):'');}
example.addEventListener('change',show);environment.addEventListener('change',show);show();
})();</script>'''


def table(headers, rows):
    return ('<div class="native-table-scroll"><table class="tt"><thead><tr>'
            + ''.join(f'<th>{esc(h)}</th>' for h in headers) + '</tr></thead><tbody>'
            + ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in row) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def scalar_table(tokens, family, unit='pt'):
    return table(['Token', 'Resolved value'], [
        [f'<span class="tok">{esc(family)}.{esc(k)}</span>', f'{number(v)}{unit}']
        for k, v in tokens[family].items()])


def value_markup(value):
    if isinstance(value, dict):
        if {'light', 'dark', 'lightAlpha', 'darkAlpha'} <= value.keys():
            return '<div class="native-colors">' + ''.join(
                f'<span class="native-color {mode}" style="background:var(--surfacePrimary);color:var(--foregroundPrimary)">'
                f'<i style="background:rgba({int(value[mode][0:2],16)},{int(value[mode][2:4],16)},{int(value[mode][4:6],16)},{value[mode+"Alpha"]})"></i>'
                f'<span>{mode.title()}<br>#{value[mode]} · {number(value[mode+"Alpha"]*100)}%</span></span>'
                for mode in ['light', 'dark']) + '</div>'
        return '<br>'.join(f'{esc(k)}: {value_markup(v)}' for k, v in value.items())
    if value is None:
        return 'None'
    return esc(number(value))


def integrate(pages, context, out, source, semantics, styles, spacing, sizing, radius):
    site = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, str(site / 'scripts/sync-ios.py'), '--check', '--ios-repo', str(source)], check=True)
    tokens = json.loads((site / 'lib/ios/tokens.generated.json').read_text())
    metadata = json.loads((site / 'lib/ios/source.generated.json').read_text())
    manifest = json.loads((site / 'lib/ios/previews.generated.json').read_text())
    # Both renderers must agree before a native image can vouch for a browser specimen.
    assert {v['name'] for v in semantics} == set(tokens['HHColors']), 'Semantic color inventory differs from compiled Swift'
    for value in semantics:
        native = tokens['HHColors'][value['name']]
        assert (value['lh'], value['dh'], value['la'], value['da']) == (native['light'], native['dark'], native['lightAlpha'], native['darkAlpha']), f'Color mismatch: {value["name"]}'
    for family, values in [('HHSpacing', spacing), ('HHRadius', radius), ('HHSizing', sizing)]:
        for key, value, *_ in values:
            assert value == tokens[family][key], f'Metric mismatch: {family}.{key}'
    assert {style['name'] for style in styles} == set(tokens['HHTextStyle']), 'Semantic type inventory differs from compiled Swift'
    for style in styles:
        native = tokens['HHTextStyle'][style['name']]
        for parsed, compiled in [('size', 'size'), ('postscript', 'fontName'), ('line_multiple', 'lineHeightMultiple'), ('tracking_percent', 'trackingPercentage'), ('tracking', 'letterSpacing')]:
            assert style[parsed] == native[compiled], f'Typography mismatch: {style["name"]}.{parsed}'
    revision = metadata['revision']
    provenance = (f'<div class="native-meta">Rendered from <a href="{metadata["repository"]}/tree/{revision}/DesignSystem">'
                  f'HeidiNative iOS <code>{revision[:10]}</code></a>'
                  + (' with local source changes' if metadata['sourceDirty'] else '')
                  + f' · iOS {esc(manifest["osVersion"])} simulator · synthetic examples.'
                  '<details><summary>Capture details and limitations</summary>These are native captures at their logical point width. Narrow screens scroll horizontally to preserve scale. '
                  'They show layout and appearance; interaction, VoiceOver, older iOS fallbacks and iPad system chrome need separate verification. '
                  'The Arabic configuration checks layout direction with English specimen text.</details></div>')
    component_ids = [p['id'] for p in manifest['previews'] if p['configuration'] == 'light' and p['components']]
    inventory = table(['Component', 'Source', 'Native specimens'], [[
        f'<code>{esc(c["name"])}</code>',
        f'<a href="{metadata["repository"]}/blob/{revision}/{esc(c["path"])}">{esc(Path(c["path"]).name)}</a>',
        esc(', '.join(p['id'] for p in manifest['previews'] if p['configuration'] == 'light' and c['name'] in p['components'])
            or metadata['previewExclusions'].get(c['name'], 'Missing'))]
        for c in metadata['components']])
    native_page = ('native-components.html', 'Native catalogue',
                   'Reusable package components, rendered by SwiftUI and UIKit from the app source.',
                   provenance + gallery(manifest, component_ids) + '<h2>Component coverage</h2>' + inventory)
    token_page = ('native-tokens.html', 'Compiled tokens',
                  'Values exported from the running DesignSystem package, including alpha, layout metrics and font resolution.',
                  provenance + '<p>Numeric layout metrics use points; opacity and trackingPercentage use fractions. '
                  'Color values are sRGB hex plus alpha. Color chips are composited on surfacePrimary. '
                  'See Text for the styled type contract and native specimens.</p>'
                  + ''.join(f'<details class="native-group"><summary>{esc(family)} · {len(values)}</summary>'
                            + table(['Token', 'Compiled value'], [[f'<span class="tok">{esc(family)}.{esc(key)}</span>', value_markup(value)]
                            for key, value in values.items()]) + '</details>' for family, values in tokens.items()))
    routing = {
        'buttons.html': ['button-primary', 'button-secondary', 'button-tertiary', 'legacy-buttons', 'number-pad'],
        'toolbars.html': ['sheet-toolbar', 'sheet-toolbar-back'],
        'sheets.html': ['confirmation', 'confirmation-loading', 'branding-promo', 'country-picker', 'tabs-header'],
        'tabs.html': ['tabs-header'], 'rows-settings.html': ['settings', 'toggle'],
        'rows-actions.html': ['settings'],
        'fonts.html': [p['id'] for p in manifest['previews'] if p['configuration'] == 'light' and p['id'].startswith('type-')],
        'shadows.html': ['shadows'], 'avatars.html': ['accent-hues'],
    }
    replacements = {'toolbars.html', 'tabs.html', 'rows-settings.html', 'rows-actions.html'}
    result = []
    for href, title, lede, content, *extra in pages:
        if href in routing:
            captured = '<h2>Native reference</h2>' + provenance + gallery(manifest, routing[href])
            content = captured + ('' if href in replacements else content)
        if href == 'buttons.html':
            lede = 'HHButton and its primary, secondary and tertiary styles, followed by the existing adoption audit.'
        if href == 'sizing.html':
            content = '<h2>Control sizes · HHSize</h2>' + scalar_table(tokens, 'HHSize') + content
        if href == 'colors.html':
            content += '<h2>State opacity · HHOpacity</h2>' + scalar_table(tokens, 'HHOpacity', '')
        if href == 'spacing.html':
            content += '<h2>Baseline offsets</h2>' + scalar_table(tokens, 'HHBaselineOffset')
        if href == 'screens-notifications.html':
            lede = 'Notification and Live Activity surfaces, their triggers, copy and routing.'
            content = '<p class="native-meta">Existing notification audit and illustrative browser previews. These surfaces are outside the package capture coverage.</p>' + (context / 'notifications.html').read_text()
        if href == 'rows-actions.html':
            content += '<p>Settings actions above use the shared row components. Session-specific actions remain outside this package catalogue.</p>'
        result.append((href, title, lede, content, *extra))
    result.extend([native_page, token_page])
    if out != site:
        for relative in ['public/ios/native', 'lib/ios']:
            shutil.copytree(site / relative, out / relative, dirs_exist_ok=True)
    return result, CSS
