"""Download pinned public weights/runtime. No account, API key or paid inference."""
import hashlib
from pathlib import Path
import subprocess
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parent/'local-model'
RUNTIME_URL='https://github.com/ggml-org/llama.cpp/releases/download/b10964/llama-b10964-bin-win-cpu-x64.zip'
RUNTIME_SHA='917f39c076402c421224824607397af20f53625a60defc20e8dd22446bf4c5d7'
MODEL_URL='https://huggingface.co/ggml-org/Qwen3-0.6B-GGUF/resolve/b5f37287796e5be0ea3dab2e7430873fb3f73e49/Qwen3-0.6B-Q4_0.gguf'
MODEL_SHA='da2572f16c06133561ce56accaa822216f2391ef4d37fba427801cd6736417d4'

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def fetch(url,path,digest):
    if path.exists() and sha(path)==digest:return
    partial=path.with_suffix(path.suffix+'.partial')
    print('Downloading public model/runtime:',path.name,flush=True)
    with urllib.request.urlopen(url,timeout=60) as response, partial.open('wb') as out:
        size=0
        while True:
            block=response.read(1048576)
            if not block:break
            size+=len(block)
            if size>2_000_000_000:raise ValueError('Download exceeds expected limit')
            out.write(block)
    if sha(partial)!=digest:raise ValueError('Checksum mismatch. File will not be used.')
    partial.replace(path)

def prepare():
    ROOT.mkdir(exist_ok=True)
    archive=ROOT/'runtime.zip';model=ROOT/'Qwen3-0.6B-Q4_0.gguf'
    fetch(RUNTIME_URL,archive,RUNTIME_SHA);fetch(MODEL_URL,model,MODEL_SHA)
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            target=(runtime/entry.filename).resolve()
            if not target.is_relative_to(runtime.resolve()):raise ValueError('Invalid archive path')
        for entry in z.infolist():
            target=runtime/entry.filename
            if entry.is_dir():
                target.mkdir(parents=True,exist_ok=True);continue
            data=z.read(entry)
            if target.exists() and sha(target)==hashlib.sha256(data).hexdigest():continue
            target.parent.mkdir(parents=True,exist_ok=True)
            try:target.write_bytes(data)
            except PermissionError as error:
                raise RuntimeError('Close the existing model server before repairing runtime files.') from error
    return runtime/'llama-server.exe',model

if __name__=='__main__':
    print('Cell free local model. First run downloads public files; no API key or paid service. Keep this console open. Ctrl+C stops the model.',flush=True)
    exe,model=prepare()
    try:
        subprocess.run([str(exe),'-m',str(model),'--host','127.0.0.1','--port','8081','--alias','cell-local','--ctx-size','4096','--threads','4','--gpu-layers','0','--offline','--no-agent','--no-ui','--cors-origins','http://127.0.0.1:8765','--no-cors-credentials'],check=True)
    except KeyboardInterrupt:pass
