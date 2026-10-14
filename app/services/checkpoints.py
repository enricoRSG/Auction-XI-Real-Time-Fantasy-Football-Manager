"""Atomic SQLite checkpoints: current plus five previous complete databases."""
import os
import sqlite3
import threading
from datetime import datetime, UTC
from pathlib import Path
from contextlib import closing

_lock = threading.RLock()

def checkpoint_dir(db_path):
    return Path(db_path).parent / 'checkpoints'

def valid_database(path):
    try:
        with closing(sqlite3.connect(f'{Path(path).resolve().as_uri()}?mode=ro', uri=True)) as db:
            return db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and bool(db.execute("SELECT name FROM sqlite_master WHERE name='auctions'").fetchone())
    except sqlite3.Error:
        return False

def save_checkpoint(db_path, label='autosave'):
    db_path = Path(db_path)
    with _lock:
        folder = checkpoint_dir(db_path)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
        target = folder / f'{stamp}-{label}.sqlite'
        temp = target.with_suffix('.tmp')
        try:
            with closing(sqlite3.connect(str(db_path))) as source, closing(sqlite3.connect(str(temp))) as dest:
                source.backup(dest)
            if not valid_database(temp):
                raise RuntimeError('Checkpoint non valido: database non integro.')
            os.replace(temp, target)
            for old in sorted(folder.glob('*.sqlite'), reverse=True)[6:]:
                old.unlink()
            return target
        finally:
            if temp.exists():
                temp.unlink()

def recover_if_corrupt(db_path):
    db_path = Path(db_path)
    backups = sorted(checkpoint_dir(db_path).glob('*.sqlite'), reverse=True)
    if not db_path.exists() and not backups:
        return
    if db_path.exists() and valid_database(db_path):
        return
    import shutil
    for backup in backups:
        if valid_database(backup):
            quarantined = db_path.with_name(f'{db_path.name}.corrotto-{datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")}')
            if db_path.exists():
                shutil.copy2(db_path, quarantined)
            for suffix in ('-journal','-wal','-shm'):
                sidecar=db_path.with_name(db_path.name+suffix)
                if sidecar.exists():
                    os.replace(sidecar,quarantined.with_name(quarantined.name+suffix))
            shutil.copy2(backup, db_path)
            return
    raise RuntimeError('Database danneggiato e nessun checkpoint valido. Conserva i file e usa lo strumento di recupero.')

def checkpoint_status(db_path):
    return [{'name': p.name, 'saved_at': datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat(), 'bytes':p.stat().st_size}
            for p in sorted(checkpoint_dir(db_path).glob('*.sqlite'), reverse=True)]
