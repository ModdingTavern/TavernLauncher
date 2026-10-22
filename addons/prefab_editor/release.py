"""Install the checksum-pinned release runtime for a source-only add-on checkout."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import threading
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
_lock = threading.Lock()
_REQUIRED = ('runtime/node.exe', 'payload/PrefabEditor.dll', 'panel/server.js', 'workbench/server.js')
_ALLOWED = {'runtime', 'payload', 'panel', 'workbench', 'data'}
_MAX_DOWNLOAD = 250 * 1024 * 1024
_MAX_UNPACKED = 800 * 1024 * 1024


def ensure_runtime():
    with _lock:
        manifest = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
        marker = ROOT / '.runtime-version'
        if marker.is_file() and marker.read_text() == manifest['sha256'] and all((ROOT / p).is_file() for p in _REQUIRED):
            return
        with tempfile.TemporaryDirectory(prefix='prefabulator-', dir=str(ROOT)) as directory:
            temp = Path(directory)
            archive = temp / 'runtime.zip'
            digest = hashlib.sha256()
            total = 0
            request = urllib.request.Request(manifest['url'], headers={'User-Agent': 'Tavern-Prefabulator'})
            try:
                with urllib.request.urlopen(request, timeout=30) as response, archive.open('wb') as output:
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > _MAX_DOWNLOAD:
                            raise RuntimeError('Runtime download exceeds the expected size.')
                        digest.update(block)
                        output.write(block)
                if digest.hexdigest() != manifest['sha256']:
                    raise RuntimeError('Runtime checksum did not match. Download was not installed.')
                stage = temp / 'files'
                with zipfile.ZipFile(archive) as bundle:
                    expanded = 0
                    for entry in bundle.infolist():
                        prefix = 'addons/prefab_editor/'
                        if not entry.filename.startswith(prefix):
                            continue
                        relative = PurePosixPath(entry.filename[len(prefix):])
                        if not relative.parts or relative.parts[0] not in _ALLOWED:
                            continue
                        if relative.is_absolute() or '..' in relative.parts or any('\\' in part or ':' in part for part in relative.parts):
                            raise RuntimeError('Invalid runtime archive path.')
                        if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                            raise RuntimeError('Runtime archive contains a symbolic link.')
                        expanded += entry.file_size
                        if expanded > _MAX_UNPACKED:
                            raise RuntimeError('Runtime archive exceeds the expected size.')
                        target = stage.joinpath(*relative.parts)
                        if entry.is_dir():
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with bundle.open(entry) as source, target.open('wb') as output:
                            shutil.copyfileobj(source, output)
                if not all((stage / p).is_file() for p in _REQUIRED):
                    raise RuntimeError('Runtime archive is incomplete.')
                for source in stage.rglob('*'):
                    if source.is_file():
                        target = ROOT / source.relative_to(stage)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(source, target)
                marker.write_text(manifest['sha256'])
            except Exception as error:
                raise RuntimeError('Could not install the Prefabulator runtime. Check your internet connection and retry, or extract the full Player-Addon-and-Mod release beside Tavern Launcher. ' + str(error)) from error
