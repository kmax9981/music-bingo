import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .errors import best_effort, rollback_quietly

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL is not set')

_pool = {} if DATABASE_URL.startswith('sqlite') else {
    # The default (5 connections, 10 more on demand, 30 s wait) runs dry when a few dozen phones act at once
    'pool_size': 20, 'max_overflow': 30, 'pool_timeout': 15,
}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, **_pool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        rollback_quietly(db)
        raise
    finally:
        with best_effort():
            db.close()
