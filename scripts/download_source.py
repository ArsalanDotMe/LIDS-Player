"""Download pinned native sources with atomic writes and bounded retries."""
import hashlib
import shutil
import time
import urllib.request


def fetch(url, target, checksum=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        try:
            if not target.exists():
                temporary = target.with_suffix(target.suffix + '.partial')
                with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                temporary.replace(target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if checksum and digest != checksum:
                target.unlink()
                raise RuntimeError(f'Checksum mismatch: {url}')
            return digest
        except (OSError, RuntimeError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)

