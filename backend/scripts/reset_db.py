from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlmodel import SQLModel, Session, func, select


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: F401,E402 - registers SQLModel tables
from app.config import settings  # noqa: E402
from app.database import engine  # noqa: E402
from app.models import AuditEvent, Customer, Order, OrderItem, RefundCase  # noqa: E402
from app.seed import seed_database  # noqa: E402


def _database_label() -> str:
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        return str(Path(url.database).resolve())

    return settings.database_url


def _count(session: Session, model: type) -> int:
    return session.exec(select(func.count()).select_from(model)).one()


def reset_db() -> dict[str, int]:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        seed_database(session)
        return {
            "customer": _count(session, Customer),
            "order": _count(session, Order),
            "orderitem": _count(session, OrderItem),
            "refundcase": _count(session, RefundCase),
            "auditevent": _count(session, AuditEvent),
        }


def main() -> None:
    print(f"Resetting database: {_database_label()}")
    counts = reset_db()
    print("Seed state restored:")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
