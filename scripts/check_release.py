"""Offline publication boundary scan; never print matched values."""
from pathlib import Path
import hashlib
import json
import re
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]
IGNORED={'.git','data','logs','output','__pycache__','.playwright-cli'}
MEDIA_MANIFEST='docs/images/manifest.json'
PATTERNS={
    'private_key':re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'github_token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'personal_absolute_path':re.compile('/'+r'Users/[^/\s]+/'),
    'credential_literal':re.compile(r'''(?i)(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)\s*[:=]\s*["'][^"'\n]{16,}["']'''),
}


def files():
    try:
        top=subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=ROOT,stderr=subprocess.DEVNULL).decode().strip()
        if Path(top).resolve()==ROOT:
            return [ROOT/p for p in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')if p]
    except (OSError,subprocess.CalledProcessError):pass
    return [p for p in ROOT.rglob('*')if p.is_file()and not any(x in IGNORED for x in p.relative_to(ROOT).parts)]


def reviewed_media(scanned):
    """Only explicitly reviewed, hash-pinned synthetic UI screenshots are allowed."""
    path=ROOT/MEDIA_MANIFEST
    if not path.exists():return {},[]
    try:
        if path not in scanned or path.is_symlink():raise ValueError('manifest must be a scanned regular file')
        document=json.loads(path.read_text())
        if not isinstance(document,dict):raise ValueError('invalid document')
        if document.get('dataset')!='synthetic' or document.get('reviewed')is not True:raise ValueError('review required')
        media=document['files']
        if not isinstance(media,dict):raise ValueError('invalid media list')
        for name,entry in media.items():
            if not re.fullmatch(r'docs/images/[a-z0-9][a-z0-9-]*\.png',name):raise ValueError('invalid path')
            if not isinstance(entry,dict)or not re.fullmatch(r'[a-f0-9]{64}',entry.get('sha256','')):raise ValueError('invalid hash')
            if any(type(entry.get(k))is not int or not 1<=entry[k]<=4096 for k in ('width','height')):raise ValueError('invalid size')
            if ROOT/name not in scanned:raise ValueError('image missing from release')
        return media,[]
    except (OSError,UnicodeError,ValueError,KeyError,TypeError):
        return {},[(MEDIA_MANIFEST,0,'invalid_media_manifest')]


def main():
    scanned=files();media,failures=reviewed_media(scanned);count=0;images=0
    for p in scanned:
        rel=p.relative_to(ROOT);name=rel.as_posix()
        if p.is_symlink():failures.append((name,0,'unreviewed_symlink'));continue
        if any(part in IGNORED for part in rel.parts)or p.suffix in{'.sqlite','.sqlite3','.db','.pdf','.zip','.bin'}or(p.name.startswith('.env')and p.name!='.env.example'):
            failures.append((name,0,'private_or_generated_file'));continue
        if name in media:
            raw=p.read_bytes();entry=media[name]
            if len(raw)<24 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[12:16]!=b'IHDR' or struct.unpack('>II',raw[16:24])!=(entry['width'],entry['height']) or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                failures.append((name,0,'reviewed_image_changed'))
            else:images+=1
            continue
        try:text=p.read_text()
        except UnicodeError:failures.append((name,0,'unreviewed_binary'));continue
        count+=1
        for i,line in enumerate(text.splitlines(),1):
            for category,rx in PATTERNS.items():
                if rx.search(line):failures.append((name,i,category))
    for file,line,category in failures:print(f'{file}:{line}: {category}')
    print(f'Publication scan: {count} text files, {images} approved images, {len(failures)} findings')
    return 1 if failures else 0


if __name__=='__main__':raise SystemExit(main())
