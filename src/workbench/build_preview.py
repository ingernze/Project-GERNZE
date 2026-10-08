"""Bundle the actual workbench into a single offline, non-saving preview page."""
import base64
import hashlib
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent / 'static'


def build(destination):
    html = (ROOT / 'index.html').read_text().replace('data-theme="dark"', 'data-theme="dark" data-preview="true"')
    css = (ROOT / 'style.css').read_text()
    entries = re.findall(r'<script src="([^"]+)"( defer)?></script>', html)
    mark = 'data:image/svg+xml,' + quote((ROOT / 'mark.svg').read_text())
    scripts = [(ROOT / name).read_text().replace("'mark.svg'", repr(mark)) for name, _defer in entries]
    hashes = [base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() for script in scripts]
    css_hash = base64.b64encode(hashlib.sha256(css.encode()).digest()).decode()
    policy = "default-src 'none'; script-src " + ' '.join("'sha256-" + digest + "'" for digest in hashes)
    policy += "; style-src 'sha256-" + css_hash + "'; img-src data:; base-uri 'none'; form-action 'none'; object-src 'none'"
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', '<meta http-equiv="Content-Security-Policy" content="' + policy + '">', html)
    html = re.sub(r'  <link rel="icon"[^>]*>\n', '', html)
    html = re.sub(r'  <link rel="stylesheet"[^>]*>\n', '', html)
    html = re.sub(r'  <script src="[^"]+"(?: defer)?></script>\n', '', html)
    early = '\n'.join('<script>' + script + '</script>' for script, (_name, defer) in zip(scripts, entries) if not defer)
    later = '\n'.join('<script>' + script + '</script>' for script, (_name, defer) in zip(scripts, entries) if defer)
    html = html.replace('</head>', early + '\n<style>' + css + '</style>\n</head>')
    html = html.replace('</body>', later + '\n</body>')
    Path(destination).write_text(html)


if __name__ == '__main__':
    build(sys.argv[1])
