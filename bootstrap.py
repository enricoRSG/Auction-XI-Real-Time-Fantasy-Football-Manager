"""Launch with project-local packages, including embedded Python distributions."""
import hashlib
import importlib
import os
from pathlib import Path
import subprocess
import sys

def main():
    root=Path(__file__).resolve().parent
    os.chdir(root)
    if sys.version_info<(3,12):
        raise SystemExit('Serve Python 3.12 o successivo. Installa Python da python.org e riapri Auction XI.')
    packages=root/'.runtime_packages'
    sys.path.insert(0,str(packages));sys.path.insert(0,str(root))
    modules=['fastapi','uvicorn','jinja2','multipart','sqlalchemy','openpyxl']
    digest=hashlib.sha256((root/'requirements.txt').read_bytes()).hexdigest()
    marker=packages/'auctionxi-requirements.sha256'
    ready=marker.exists() and marker.read_text()==digest
    if ready:
        try:
            for module in modules:importlib.import_module(module)
        except ImportError:ready=False
    if not ready:
        print('Installazione dipendenze Auction XI nella cartella dell’app…')
        subprocess.check_call([sys.executable,'-m','pip','install','--upgrade','--target',str(packages),'-r',str(root/'requirements.txt')])
        marker.write_text(digest)
        # Restart to avoid partially imported modules from a failed check.
        os.execv(sys.executable,[sys.executable,str(root/'bootstrap.py'),*sys.argv[1:]])
    if '--restore' in sys.argv:
        from restore_checkpoint import main as restore
        restore();return
    if '--check' in sys.argv:
        from app.main import app
        print('Auction XI 1.1.0-rc1: runtime pronto.');return
    import runpy
    runpy.run_path(str(root/'launcher.py'),run_name='__main__')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(f'Avvio non riuscito: {exc}');sys.exit(1)
