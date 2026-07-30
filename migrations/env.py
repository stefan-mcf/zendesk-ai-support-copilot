import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from copilot.config import get_settings
from copilot.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
database_url = settings.resolved_database_url or config.get_main_option("sqlalchemy.url")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = create_async_engine(database_url, pool_pre_ping=True)
    async with connectable.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock(604972417821)"))
        await connection.commit()
        try:
            await connection.run_sync(
                lambda sync_connection: context.configure(
                    connection=sync_connection,
                    target_metadata=target_metadata,
                    compare_type=True,
                )
            )
            async with connection.begin():
                await connection.run_sync(lambda _: context.run_migrations())
        finally:
            if connection.in_transaction():
                await connection.rollback()
            await connection.execute(text("SELECT pg_advisory_unlock(604972417821)"))
            await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
