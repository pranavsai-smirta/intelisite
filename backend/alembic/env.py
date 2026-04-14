import os
from logging.config import fileConfig
from dotenv import load_dotenv

from sqlalchemy import engine_from_config, pool
from alembic import context

# Load .env so DATABASE_URL is available
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Pull the live DATABASE_URL from .env and inject it into Alembic config
db_url = os.getenv("DATABASE_URL")
if not db_url:
    raise RuntimeError("DATABASE_URL not set in .env")
config.set_main_option("sqlalchemy.url", db_url)

# Wire up our SQLAlchemy metadata so autogenerate works
from app.db.session import Base  # noqa: E402
from app.db import models  # noqa: F401, E402  (imports must register all ORM classes)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
