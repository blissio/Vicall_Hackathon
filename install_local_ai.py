"""Install an isolated, pinned CPU-only experiment. Run explicitly; never at app startup."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent / '.local-ai'
RUNTIME_URL = 'https://github.com/ggml-org/llama.cpp/releases/download/b11429/llama-b11429-bin-win-cpu-x64.zip'
RUNTIME_SHA = '1283323272b04cd07905816a597a0da810918102de958f4ff6f7bbaa70ed2efe'
MODEL_REPO = 'Qwen/Qwen2.5-0.5B-Instruct-GGUF'
MODEL_NAME = 'qwen2.5-0.5b-instruct-q4_k_m.gguf'


def download(url, target, expected):
    if target.exists() and hashlib.file_digest(target.open('rb'), 'sha256').hexdigest() == expected:
        return
    part = target.with_suffix('.part')
    print('Downloading '+target.name, flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, part.open('wb') as output:
        while chunk := response.read(1024*1024):
            output.write(chunk)
    with part.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != expected:
            raise ValueError('Download checksum mismatch: '+target.name)
    part.replace(target)


def install():
    ROOT.mkdir(exist_ok=True)
    download(RUNTIME_URL, ROOT/'runtime.zip', RUNTIME_SHA)
    with zipfile.ZipFile(ROOT/'runtime.zip') as archive:
        for item in archive.infolist():
            if not (ROOT/'runtime'/item.filename).resolve().is_relative_to(ROOT.resolve()/'runtime'):
                raise ValueError('Invalid archive path')
        archive.extractall(ROOT/'runtime')
    with urllib.request.urlopen('https://huggingface.co/api/models/'+MODEL_REPO+'/tree/main') as response:
        files = json.load(response)
    info = next(item for item in files if item['path'] == MODEL_NAME)
    sha = info['lfs']['oid']
    # Pin the resolved revision before fetching the large file.
    with urllib.request.urlopen('https://huggingface.co/api/models/'+MODEL_REPO) as response:
        revision = json.load(response)['sha']
    download('https://huggingface.co/'+MODEL_REPO+'/resolve/'+revision+'/'+MODEL_NAME, ROOT/MODEL_NAME, sha)
    (ROOT/'installed.json').write_text(json.dumps({'runtime': RUNTIME_URL, 'runtime_sha256': RUNTIME_SHA, 'model': MODEL_REPO, 'revision': revision, 'model_sha256': sha}, indent=2))
    print('Portable local test model installed. No service or startup task was added.', flush=True)


if __name__ == '__main__':
    install()
