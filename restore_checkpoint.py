"""Interactive offline recovery. Stop Auction XI before running this tool."""
import os
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from app.services.checkpoints import checkpoint_status, valid_database, save_checkpoint

def main():
    path=Path(os.environ.get('AUCTIONXI_DB_PATH',str(Path(__file__).parent/'app/data/fantacalcio.db'))).resolve()
    saves=checkpoint_status(path)
    print('RIPRISTINA CHECKPOINT — chiudi prima il server Auction XI.')
    print('La copia contiene tutte le aste presenti nel database al momento del salvataggio.')
    if not saves:
        print('Nessun checkpoint disponibile.');return
    for i,s in enumerate(saves,1):
        print(f'{i}. {s["saved_at"]} — {s["name"]}')
    choice=input('Numero checkpoint da ripristinare (Invio = annulla): ').strip()
    if not choice:return
    try:
        selected=saves[int(choice)-1]
        if int(choice)<1:raise ValueError()
    except (ValueError,IndexError):
        print('Selezione non valida.');return
    backup=path.parent/'checkpoints'/selected['name']
    if not valid_database(backup):
        print('Checkpoint non integro: scegli una copia precedente.');return
    if input('Conferma che il server è chiuso e scrivi RIPRISTINA: ').strip()!='RIPRISTINA':return
    from app.services.instance import instance_guard
    guard=instance_guard(path)
    try:guard.__enter__()
    except RuntimeError as exc:
        print(str(exc));return
    # Preserve the current database before changing anything, including corrupt files.
    current=path.with_name(path.name+'.prima-ripristino-'+datetime.now().strftime('%Y%m%d-%H%M%S%f'))
    try:
        if path.exists():shutil.copy2(path,current)
        for suffix in ('-journal','-wal','-shm'):
            sidecar=path.with_name(path.name+suffix)
            if sidecar.exists():os.replace(sidecar,current.with_name(current.name+suffix))
        temp=path.with_suffix('.restore.tmp')
        shutil.copy2(backup,temp)
        os.replace(temp,path)
    finally:
        guard.__exit__(None,None,None)
    print('Ripristino completato. Riapri Auction XI; eventuali chiamate remote saranno in pausa.')

if __name__=='__main__':main()
