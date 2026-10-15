from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.database import create_db_engine
from app.models import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    # Tests (and tooling) may pass an explicit URL; otherwise use app configuration.
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=url.startswith("sqlite"),
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Same engine factory as the application, so PRAGMA foreign_keys=ON applies here too.
    engine = create_db_engine(_database_url())
    with engine.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        if is_sqlite:
            # Batch migrations rebuild tables (copy, DROP, rename). With foreign keys
            # enforced, DROP TABLE of a referenced table fails, so follow SQLite's
            # documented procedure: disable enforcement for the migration, then verify
            # integrity with foreign_key_check before re-enabling. The pragma is ignored
            # inside a transaction, hence the explicit commit of the autobegun one.
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite cannot ALTER most constraints; batch mode recreates tables.
            render_as_batch=is_sqlite,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        if is_sqlite:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            if violations:
                raise RuntimeError(f"Migration left foreign-key violations: {violations[:10]}")
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
