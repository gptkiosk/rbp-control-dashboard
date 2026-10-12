#!/usr/bin/env python3
"""Check versioned Markdown links without network access or credentials."""
from pathlib import Path
from urllib.parse import unquote,urlsplit
import re,sys
root=Path(__file__).resolve().parents[1]
errors=[]
for path in [*root.glob('*.md'),*root.glob('.github/*.md'),*root.glob('docs/**/*.md')]:
    text=re.sub(r'```.*?```','',path.read_text(),flags=re.S)
    for match in re.finditer(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+[^)]*)?\)',text):
        link=match.group(1).strip('<>');parsed=urlsplit(link)
        if parsed.scheme or link.startswith('#'): continue
        target=(path.parent/unquote(parsed.path)).resolve()
        if not target.exists(): errors.append(f'{path.relative_to(root)}: {link}')
if errors:
    print('Broken local links:\n'+'\n'.join(sorted(set(errors))))
    sys.exit(1)
print('Markdown file/image links passed; remote links and anchors require review.')
