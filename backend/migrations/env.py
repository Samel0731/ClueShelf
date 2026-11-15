from alembic import context

from clueshelf.database import Base, database_url, make_engine
from clueshelf import models  # noqa: F401
from clueshelf import youtube_models  # noqa: F401
from clueshelf import taxonomy_models, browse_models  # noqa: F401

if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with make_engine(database_url()).connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
            if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Migration introduced invalid foreign keys")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
