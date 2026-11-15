"""One official API page per leased transaction; AI and indexing run elsewhere."""
import argparse
import time
import threading
from contextlib import contextmanager
from uuid import uuid4
from sqlalchemy import select, update, func
from sqlalchemy.exc import OperationalError
from .database import database_url, make_engine, session_factory
from .models import Save, Job
from .service import OWNER, enqueue
from .search import sync_save
from .youtube_models import YouTubeConnection, YouTubeSync, YouTubeSource
from .youtube_auth import WindowsTokenStore, GoogleClient, YouTubeError

ACTIVE = ('queued', 'running')
LEASE = 300


def latest(session):
    return session.scalar(select(YouTubeSync).join(YouTubeConnection).where(YouTubeConnection.owner_id == OWNER).order_by(YouTubeSync.created_at.desc()).limit(1))


def sync_view(session, job):
    if job is None:
        return None
    waiting = session.scalar(select(func.count()).select_from(Save).join(YouTubeSource, YouTubeSource.save_id == Save.id).where(YouTubeSource.sync_id == job.id, Save.ai_status.in_(['queued','processing']))) or 0
    keys = ('id','state','read_count','new_count','existing_count','skipped_count','failure_count','skip_reasons','error','cancel_requested','created_at','updated_at')
    return {**{key: getattr(job, key) for key in keys}, 'ai_waiting': waiting}


def start_sync(factory):
    with factory() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        connection = session.scalar(select(YouTubeConnection).where(YouTubeConnection.owner_id == OWNER))
        if not connection or connection.status != 'connected':
            raise ValueError('請先連結 YouTube 帳號。')
        current = session.scalar(select(YouTubeSync).where(YouTubeSync.connection_id == connection.id, YouTubeSync.state.in_(ACTIVE)))
        if current:
            result = sync_view(session, current)
            session.commit()
            return result
        # A quota pause or transient failure resumes its committed cursor on explicit retry.
        previous = latest(session)
        now = time.time()
        if previous and previous.state in {'paused','failed'} and previous.token_key == connection.token_key:
            previous.state, previous.attempts, previous.available_at = 'queued', 0, now
            previous.error, previous.cancel_requested, previous.cursor_restarts = None, False, 0
            job = previous
        else:
            job = YouTubeSync(id=str(uuid4()), connection_id=connection.id, token_key=connection.token_key, state='queued', available_at=now, created_at=now, updated_at=now, skip_reasons={})
            session.add(job)
        session.flush()
        result = sync_view(session, job)
        session.commit()
        return result


def claim(factory):
    now = time.time()
    with factory() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        for job in session.scalars(select(YouTubeSync).where(YouTubeSync.state == 'running', YouTubeSync.lease_until <= now)):
            job.state = 'failed' if job.attempts >= 3 else 'queued'
            job.error = '上次同步中斷，已保留完成的批次。'
        job = session.scalar(select(YouTubeSync).where(YouTubeSync.state == 'queued', YouTubeSync.available_at <= now).order_by(YouTubeSync.available_at).limit(1))
        if not job:
            session.commit()
            return None
        connection = session.get(YouTubeConnection, job.connection_id)
        if job.cancel_requested or connection.status != 'connected' or connection.token_key != job.token_key:
            job.state = 'cancelled'
            session.commit()
            return None
        job.state, job.lease_token, job.lease_until = 'running', str(uuid4()), now + LEASE
        job.attempts += 1
        session.commit()
        return job, connection


def upsert_video(session, connection, job, identity, snippet, now):
    source = session.get(YouTubeSource, (connection.id, identity))
    if source and source.sync_id == job.id:
        return 'existing'
    save = session.scalar(select(Save).where(Save.owner_id == OWNER, Save.platform == 'youtube', Save.content_id == identity))
    is_new = save is None
    if save is None:
        save = Save(id=str(uuid4()), owner_id=OWNER, platform='youtube', content_id=identity, url='https://www.youtube.com/watch?v=' + identity, title='', author_text='', version=1, status='queued', created_at=now, updated_at=now)
        session.add(save)
        session.flush()
    snapshot = {'provider': 'youtube_api', 'original_title': snippet.get('title',''), 'author_text': snippet.get('description',''), 'canonical_url': save.url, 'comments': [], 'comments_ranking': 'not_applicable', 'fetched_count': 0, 'status': 'complete', 'reason': None, 'fetched_at': now}
    old = save.source or {}
    changed = is_new or old.get('provider') != 'youtube_api' or old.get('original_title') != snapshot['original_title'] or old.get('author_text') != snapshot['author_text']
    save.source = snapshot
    save.extraction_status, save.extraction_error = 'complete', None
    if not save.title_manual and save.title_mode != 'ai':
        save.title = snapshot['original_title']
    if not save.text_manual:
        save.author_text = snapshot['author_text']
    if changed:
        if not is_new:
            session.execute(update(Job).where(Job.save_id == save.id, Job.state.in_(['queued','running'])).values(state='superseded'))
            save.version += 1
        save.status, save.updated_at = 'queued', now
        session.flush()
        enqueue(session, save, kind='analyze')
    sync_save(session, save)
    if source is None:
        source = YouTubeSource(connection_id=connection.id, video_id=identity, save_id=save.id, first_seen_at=now, last_seen_at=now, sync_id=job.id, source_status='seen')
        session.add(source)
    else:
        source.save_id, source.last_seen_at, source.sync_id, source.source_status = save.id, now, job.id, 'seen'
    return 'new' if is_new else 'existing'


@contextmanager
def heartbeat(factory, job):
    stop = threading.Event()
    def renew():
        while not stop.wait(10):
            try:
                with factory() as session:
                    now = time.time()
                    changed = session.execute(update(YouTubeSync).where(YouTubeSync.id == job.id, YouTubeSync.state == 'running', YouTubeSync.lease_token == job.lease_token, YouTubeSync.lease_until > now).values(lease_until=now + LEASE)).rowcount
                    session.commit()
                    if not changed:
                        return
            except OperationalError:
                continue
    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=12)


def run_once(factory, store=None, client_factory=GoogleClient):
    claimed = claim(factory)
    if claimed is None:
        return False
    job, connection = claimed
    store = store or WindowsTokenStore()
    try:
        serialized = store.get(job.token_key)
        if not serialized:
            raise YouTubeError('auth', 'Google 授權不存在，請重新連結。')
        with heartbeat(factory, job):
            client = client_factory(serialized)
            ids, videos, cursor = client.page(connection.playlist_id, job.cursor)
        with factory() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            current = session.get(YouTubeSync, job.id)
            connected = session.get(YouTubeConnection, job.connection_id)
            if current.state != 'running' or current.lease_token != job.lease_token or current.lease_until <= time.time() or connected.status != 'connected' or connected.token_key != job.token_key:
                session.rollback()
                return True
            # Store the refreshed token only while this connection generation is still current.
            store.set(job.token_key, client.serialized())
            now = time.time()
            for identity in ids:
                current.read_count += 1
                snippet = videos.get(identity)
                if not snippet:
                    current.skipped_count += 1
                    current.skip_reasons = {**current.skip_reasons, 'unavailable': current.skip_reasons.get('unavailable', 0) + 1}
                    continue
                outcome = upsert_video(session, connected, current, identity, snippet, now)
                if outcome == 'new':
                    current.new_count += 1
                else:
                    current.existing_count += 1
            current.cursor, current.attempts = cursor, 0
            current.state = 'cancelled' if current.cancel_requested else 'queued' if cursor else 'completed'
            current.lease_token, current.lease_until, current.updated_at = None, None, now
            current.available_at, current.error = now, None
            if current.state == 'completed':
                connected.last_complete_scan_at = now
            session.commit()
    except YouTubeError as error:
        fail(factory, job, error)
    except Exception:
        # Provider exceptions may include access tokens or request URLs. Persist only a fixed message.
        fail(factory, job, YouTubeError('transient', '同步發生錯誤，已保留完成的批次。'))
    return True


def fail(factory, job, error):
    with factory() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        current = session.get(YouTubeSync, job.id)
        connection = session.get(YouTubeConnection, job.connection_id)
        if not current or current.state != 'running' or current.lease_token != job.lease_token or current.lease_until <= time.time():
            return
        current.failure_count += 1
        current.error, current.updated_at = str(error), time.time()
        current.lease_token, current.lease_until = None, None
        if current.cancel_requested or connection.status != 'connected' or connection.token_key != job.token_key:
            current.state = 'cancelled'
        elif error.kind == 'cursor' and current.cursor and current.cursor_restarts < 1:
            current.cursor, current.cursor_restarts, current.attempts = None, current.cursor_restarts + 1, 0
            current.state = 'queued'
        elif error.kind == 'transient' and current.attempts < 3:
            current.state, current.available_at = 'queued', time.time() + 2 ** current.attempts
        else:
            current.state = 'paused' if error.kind in {'quota', 'auth'} else 'failed'
            if error.kind == 'auth':
                connection.status = 'reauthorize'
        session.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['worker'], nargs='?', default='worker')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    factory = session_factory(make_engine(database_url()))
    while True:
        try:
            worked = run_once(factory)
        except OperationalError:
            worked = False
        if args.once:
            return
        if not worked:
            time.sleep(1)


if __name__ == '__main__':
    main()
