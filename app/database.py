import os
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = Path(os.environ.get('AUCTIONXI_DB_PATH', str(Path(__file__).resolve().parent / 'data' / 'fantacalcio.db'))).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout":30},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def initialize_database():
    from app.services.checkpoints import recover_if_corrupt, save_checkpoint
    recover_if_corrupt(DB_PATH)
    existing = inspect(engine).get_table_names()
    migrations = {
        'auctions': {'participation_mode': "VARCHAR(20) NOT NULL DEFAULT 'presence'", 'dealer_team_id':'INTEGER',
                     'dealer_order': "TEXT NOT NULL DEFAULT '[]'", 'deadline':'DATETIME',
                     'call_version':'INTEGER NOT NULL DEFAULT 0', 'paused':'BOOLEAN NOT NULL DEFAULT 0',
                     'timer_remaining':'INTEGER', 'last_saved_at':'DATETIME'},
        'teams': {'credit_adjustment':'INTEGER NOT NULL DEFAULT 0'},
    }
    needs_migration = any(table in existing and set(columns) - {c['name'] for c in inspect(engine).get_columns(table)} for table, columns in migrations.items())
    if needs_migration:
        save_checkpoint(DB_PATH, 'prima-migrazione')
    with engine.begin() as conn:
        for table, columns in migrations.items():
            if table not in existing:
                continue
            known = {c['name'] for c in inspect(conn).get_columns(table)}
            for name, definition in columns.items():
                if name not in known:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {definition}'))
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
