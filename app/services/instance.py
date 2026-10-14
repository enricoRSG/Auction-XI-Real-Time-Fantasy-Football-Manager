"""This SQLite release runs with exactly one server process per database."""
from contextlib import contextmanager

@contextmanager
def instance_guard(db_path):
    path=db_path.with_name(db_path.name+'.server.lock')
    stream=path.open('a+b')
    if path.stat().st_size==0:
        stream.write(b'0');stream.flush()
    stream.seek(0)
    import os
    acquired=False
    try:
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:raise RuntimeError('Auction XI è già aperto con questo database. Chiudi l’altro server; usa un solo processo.') from exc
        else:
            import fcntl
            try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise RuntimeError('Auction XI è già aperto con questo database. Usa un solo processo.') from exc
        acquired=True
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name=='nt':msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        stream.close()
