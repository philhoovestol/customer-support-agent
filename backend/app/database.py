from collections.abc import Generator

from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.seed import seed_database


def _connect_args() -> dict:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    return {}


engine = create_engine(settings.database_url, connect_args=_connect_args())


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def init_db() -> None:
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)

