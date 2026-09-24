from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.infrastructure.config.settings import Settings, get_settings


class Base(DeclarativeBase):
    """Declarative base de SQLAlchemy."""


def create_postgres_engine(settings: Settings | None = None) -> Engine:
    current = settings or get_settings()
    return create_engine(
        current.postgres_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": 3},
    )


def create_session_factory(settings: Settings | None = None) -> sessionmaker:
    engine = create_postgres_engine(settings)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )


def ping_postgres(settings: Settings | None = None) -> bool:
    try:
        engine = create_postgres_engine(settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except (SQLAlchemyError, OSError):
        return False


def id_a_entero(valor: str | int) -> int:
    return int(str(valor).strip())


def id_a_dominio(valor: int | str) -> str:
    return str(valor)