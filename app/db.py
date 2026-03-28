from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

from .config import Config


connect_args = {}
if Config.SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, future=True, connect_args=connect_args)
SessionLocal = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))


class Base(DeclarativeBase):
    pass


def get_db():
    return SessionLocal()


def close_db_session():
    SessionLocal.remove()


def init_db():
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            columns = {column["name"] for column in inspect(conn).get_columns("users")}
            if "password_hash" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))
