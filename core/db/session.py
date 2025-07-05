# core/db/session.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import DATABASE_URL

# The engine is our “handle” to the database
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # checks connections before use
    future=True              # use SQLAlchemy 2.0 style
)

# Each SessionLocal() instance is a database session
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)
