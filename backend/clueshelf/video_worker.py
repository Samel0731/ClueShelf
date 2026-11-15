"""Durable video queue independent of collection metadata and account sync."""
import argparse
from hashlib import sha256
import logging
from shutil import rmtree
from threading import Event, Thread
import time
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from .ai import AIUnavailable
from .database import database_url, make_engine, session_factory
from .models import Save, VideoAnalysis
from .search import sync_save
from .video_analysis import analyze_video
from .video_models import VideoProgress
from .video_sources import DATA_DIR, VideoSourceError, collect_public_text, transcribe_audio
from .worker import LEASE_SECONDS

log = logging.getLogger("clueshelf.video_worker")
MAX_ATTEMPTS = 3


def claim(factory):
    now = time.time()
    with factory() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        expired = session.scalars(select(VideoAnalysis).where(
            VideoAnalysis.state == "running", VideoAnalysis.lease_until <= now,
        ))
        for video in expired:
            video.state = "failed" if video.attempts >= MAX_ATTEMPTS else "queued"
            video.error = "上次影片解析中斷，可重新解析。"
            video.token, video.lease_until = None, None
            video.progress = None
            if save := session.get(Save, video.save_id):
                save.updated_at = now
        session.flush()
        # Keep at most one video analysis active, including across multiple workers.
        running = session.scalar(select(VideoAnalysis.save_id).where(VideoAnalysis.state == "running").limit(1))
        video = None if running else session.scalar(select(VideoAnalysis).where(
            VideoAnalysis.state == "queued", VideoAnalysis.available_at <= now,
        ).order_by(VideoAnalysis.available_at, VideoAnalysis.save_id).limit(1))
        if video is not None:
            video.state, video.token, video.lease_until = "running", str(uuid4()), now + LEASE_SECONDS
            if video.mode == "transcribe":
                video.progress = VideoProgress(stage="preparing").model_dump()
            video.attempts += 1
            if save := session.get(Save, video.save_id):
                save.updated_at = now
        session.commit()
        return video


def owned(job, now):
    return (
        VideoAnalysis.save_id == job.save_id, VideoAnalysis.state == "running",
        VideoAnalysis.token == job.token, VideoAnalysis.lease_until > now,
    )


def heartbeat(factory, job, stop, lost):
    while not stop.wait(10):
        try:
            with factory() as session:
                now = time.time()
                renewed = session.execute(update(VideoAnalysis).where(*owned(job, now)).values(lease_until=now + LEASE_SECONDS)).rowcount
                session.commit()
            if not renewed:
                lost.set()
                return
        except OperationalError:
            log.warning("video_analysis_lease_renewal_failed")


def finish(factory, job, *, result=None, error=None, retryable=False):
    with factory() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        now = time.time()
        video = session.scalar(select(VideoAnalysis).where(*owned(job, now)))
        if video is None:
            return
        save = session.get(Save, job.save_id)
        video.token, video.lease_until, video.error = None, None, error
        video.progress = None
        if result is not None:
            video.result = result.model_dump()
            video.state = "done"
            sync_save(session, save)
        elif retryable and video.attempts < MAX_ATTEMPTS:
            video.state = "queued"
            video.available_at = now + 30 * 2 ** (video.attempts - 1)
        else:
            video.state = "failed"
        save.updated_at = now
        session.commit()


def reap_audio(factory, scratch):
    if scratch is None or not scratch.is_dir():
        return
    directories = list(scratch.iterdir())
    if not directories:
        return
    with factory() as session:
        active_tokens = set(session.scalars(select(VideoAnalysis.token).where(
            VideoAnalysis.state == "running", VideoAnalysis.lease_until > time.time(),
        )))
    for directory in directories:
        token, separator, _ = directory.name.partition("_")
        try:
            if not separator or str(UUID(token)) != token or token in active_tokens:
                continue
        except ValueError:
            continue
        if directory.is_dir() and not directory.is_symlink() and not directory.is_junction() and directory.resolve().parent == scratch.resolve():
            try:
                rmtree(directory)
            except FileNotFoundError:
                pass
            except OSError:
                log.warning("video_analysis_audio_cleanup_pending")


def run_once(factory, *, scratch=None):
    reap_audio(factory, scratch)
    job = claim(factory)
    if job is None:
        return False
    stop, lost = Event(), Event()
    thread = Thread(target=heartbeat, args=(factory, job, stop, lost), daemon=True)
    thread.start()
    try:
        with factory() as session:
            save = session.get(Save, job.save_id)
            if save is None:
                return True
            url, description = save.url, (save.source or {}).get("author_text", "")
        public = collect_public_text(url, description)
        if lost.is_set():
            return True
        if job.mode == "transcribe":
            def report(progress):
                with factory() as session:
                    written = session.execute(update(VideoAnalysis).where(*owned(job, time.time()))
                                              .values(progress=progress.model_dump())).rowcount
                    session.commit()
                if not written:
                    lost.set()
                    raise InterruptedError

            public.segments.extend(transcribe_audio(url, public, active=lambda: not lost.is_set(),
                                                    scratch=scratch, token=job.token, report=report))
            report(VideoProgress(stage="analyzing"))
        result = analyze_video(public, job.mode, active=lambda: not lost.is_set())
        finish(factory, job, result=result)
    except InterruptedError:
        pass
    except VideoSourceError as error:
        finish(factory, job, error=str(error), retryable=error.retryable)
    except AIUnavailable as error:
        finish(factory, job, error=str(error))
    except Exception:
        log.exception("video_analysis_failed")
        finish(factory, job, error="影片解析失敗，請稍後重試。", retryable=True)
    finally:
        stop.set()
        thread.join(timeout=12)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    url = database_url()
    factory = session_factory(make_engine(url))
    scratch = DATA_DIR / "video-audio" / sha256(url.encode()).hexdigest()[:16]
    while True:
        try:
            worked = run_once(factory, scratch=scratch)
        except OperationalError:
            log.warning("video_analysis_database_unavailable")
            worked = False
        if args.once:
            return
        if not worked:
            time.sleep(2)


if __name__ == "__main__":
    main()
