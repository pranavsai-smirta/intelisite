"""Database session management"""
import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()
_SessionLocal = None


def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set in .env")
    return create_engine(db_url, pool_pre_ping=True)


def _get_sessionmaker():
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal


def init_sessionmaker():
    """Called once at startup to initialize DB"""
    maker = _get_sessionmaker()
    return maker.kw["bind"]  # returns engine


@contextmanager
def get_session():
    """
    Use as:  with get_session() as session:
    Automatically commits on success, rolls back on error, always closes.
    """
    Session = _get_sessionmaker()
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()