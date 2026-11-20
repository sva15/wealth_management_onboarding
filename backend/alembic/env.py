"""Alembic environment. Batch mode is required for SQLite ALTERs."""
from alembic import context

from app.adapters.persistence import models  # noqa: F401  (register tables)
from app.adapters.persistence.database import Base, build_engine
from app.config import get_settings

target_metadata = Base.metadata


def _database_url() -> str:
    return context.config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = build_engine(_database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
