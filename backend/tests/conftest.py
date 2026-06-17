import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest


TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"loopp-tests-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"
os.environ["LLM_PROVIDER"] = "mock"

from sqlmodel import SQLModel, Session  # noqa: E402

from app.database import engine  # noqa: E402
from app.seed import seed_database  # noqa: E402


@pytest.fixture(autouse=True)
def reset_test_database():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    TEST_DATABASE_PATH.unlink(missing_ok=True)
