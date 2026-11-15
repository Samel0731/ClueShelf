"""Pending chunk rows are a durable, idempotent local indexing queue."""
import argparse
import logging
import time

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from .embeddings import EmbeddingUnavailable, MODEL_NAME, embed, is_available
from .models import SearchChunk


def index_once(factory):
    if not is_available():
        return False
    with factory() as session:
        rows = session.scalars(select(SearchChunk).where(SearchChunk.embedding_model.is_(None), SearchChunk.embedding_attempts < 3).order_by(SearchChunk.id).limit(8)).all()
        batch = [(row.id, row.save_id, row.fingerprint, row.text) for row in rows]
    if not batch:
        return False
    try:
        vectors = embed([item[3] for item in batch], kind="passage")
    except EmbeddingUnavailable as error:
        with factory() as session:
            for row_id, save_id, fingerprint, _ in batch:
                session.execute(update(SearchChunk).where(SearchChunk.id == row_id, SearchChunk.save_id == save_id, SearchChunk.fingerprint == fingerprint, SearchChunk.embedding_model.is_(None)).values(embedding_attempts=SearchChunk.embedding_attempts + 1, embedding_error=str(error)))
            session.commit()
        return True
    with factory() as session:
        for (row_id, save_id, fingerprint, _), vector in zip(batch, vectors, strict=True):
            session.execute(update(SearchChunk).where(SearchChunk.id == row_id, SearchChunk.save_id == save_id, SearchChunk.fingerprint == fingerprint, SearchChunk.embedding_model.is_(None)).values(embedding=vector, embedding_model=MODEL_NAME, embedding_error=None))
        session.commit()
    return True


def main():
    from .database import database_url, make_engine, session_factory
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    factory = session_factory(make_engine(database_url()))
    try:
        while True:
            try:
                worked = index_once(factory)
            except OperationalError as error:
                if "locked" not in str(error).lower() and "busy" not in str(error).lower():
                    raise
                logging.getLogger(__name__).warning("index_database_busy_retry")
                worked = False
            if args.once:
                return
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
