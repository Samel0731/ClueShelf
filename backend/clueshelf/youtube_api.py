"""Local-only API boundary for official YouTube account linking."""
import json
import secrets
import time
from uuid import uuid4
import webbrowser
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from .service import OWNER
from .youtube_auth import Settings, WindowsTokenStore, GoogleClient, digest, revoke
from .youtube_models import YouTubeConnection, YouTubeOAuthState, YouTubeSync
from .youtube_sync import ACTIVE, latest, start_sync, sync_view

COOKIE = 'clueshelf_youtube_oauth'


def configuration():
    try:
        return Settings.load(), None
    except (OSError, ValueError, KeyError):
        return None, '尚未設定 Google Web OAuth client。請依 docs/youtube.md 設定後連結。'


def create_router(factory, store=None, client_factory=GoogleClient):
    router = APIRouter(prefix='/api/v1/youtube', tags=['youtube'])

    def token_store():
        return store if store is not None else WindowsTokenStore()

    @router.get('/status')
    def status(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        settings, error = configuration()
        with factory() as session:
            connection = session.scalar(select(YouTubeConnection).where(YouTubeConnection.owner_id == OWNER))
            keys = ('id','channel_id','channel_title','status','last_complete_scan_at')
            return {'configured': settings is not None, 'configuration_error': error, 'connection': {key: getattr(connection, key) for key in keys} if connection else None, 'sync': sync_view(session, latest(session))}

    @router.post('/oauth/start')
    def oauth_start(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        settings, error = configuration()
        if not settings:
            raise HTTPException(503, error)
        state, ticket = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        key = 'oauth/' + str(uuid4())
        try:
            flow = settings.flow(state=state)
            url, _ = flow.authorization_url(access_type='offline', prompt='consent', include_granted_scopes='false')
            storage = token_store()
            storage.set(key, json.dumps({'verifier': flow.code_verifier, 'authorization_url': url}))
            with factory() as session:
                expired = session.scalars(select(YouTubeOAuthState).where(YouTubeOAuthState.expires_at <= time.time())).all()
                for item in expired:
                    storage.delete(item.verifier_key)
                    session.delete(item)
                session.add(YouTubeOAuthState(digest=digest(state), browser_digest=digest(ticket), verifier_key=key, expires_at=time.time() + 600))
                session.commit()
            launch = settings.callback.rsplit('/', 1)[0] + '/launch?state=' + state + '&ticket=' + ticket
            if not webbrowser.open(launch, new=1):
                with factory() as session:
                    row = session.get(YouTubeOAuthState, digest(state))
                    if row:
                        session.delete(row)
                        session.commit()
                storage.delete(key)
                raise HTTPException(503, '無法開啟系統瀏覽器，請確認預設瀏覽器設定。')
        except HTTPException:
            raise
        except Exception:
            try:
                with factory() as session:
                    pending = session.get(YouTubeOAuthState, digest(state))
                    if pending:
                        session.delete(pending)
                        session.commit()
                token_store().delete(key)
            except Exception:
                pass
            raise HTTPException(503, '無法準備 Google 授權，請檢查 OAuth 設定與 Windows 認證服務。') from None
        return {'opened': True}

    @router.get('/oauth/launch')
    def oauth_launch(request: Request):
        state, ticket = request.query_params.get('state', ''), request.query_params.get('ticket', '')
        settings, _ = configuration()
        if not settings or not state or not ticket:
            raise HTTPException(400, '授權連結無效或過期。')
        with factory() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            pending = session.get(YouTubeOAuthState, digest(state))
            if not pending or pending.expires_at <= time.time() or not secrets.compare_digest(pending.browser_digest, digest(ticket)):
                raise HTTPException(400, '授權連結無效或已使用。')
            secret = token_store().get(pending.verifier_key)
            if not secret:
                raise HTTPException(400, '授權連結已失效。')
            browser = secrets.token_urlsafe(32)
            pending.browser_digest = digest(browser)
            session.commit()
        response = RedirectResponse(json.loads(secret)['authorization_url'], status_code=303, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
        response.set_cookie(COOKIE, browser, max_age=600, httponly=True, samesite='lax', secure=settings.callback.startswith('https:'), path='/api/v1/youtube/oauth')
        return response

    @router.get('/oauth/callback')
    def oauth_callback(request: Request):
        settings, _ = configuration()
        frontend = settings.frontend if settings else 'http://127.0.0.1:3000/'
        outcome = 'error'
        new_key = None
        try:
            raw_state = request.query_params.get('state', '')
            browser = request.cookies.get(COOKIE, '')
            with factory() as session:
                session.connection().exec_driver_sql('BEGIN IMMEDIATE')
                pending = session.get(YouTubeOAuthState, digest(raw_state))
                if not pending or not raw_state or not browser or not secrets.compare_digest(pending.browser_digest, digest(browser)):
                    raise ValueError('invalid state')
                verifier_key, valid = pending.verifier_key, pending.expires_at > time.time()
                pending.browser_digest = 'consumed'
                session.commit()
            storage = token_store()
            secret = storage.get(verifier_key)
            verifier = json.loads(secret)['verifier'] if secret else None
            storage.delete(verifier_key)
            if not valid or not verifier or not settings:
                raise ValueError('expired state')
            if request.query_params.get('error'):
                outcome = 'denied'
            else:
                flow = settings.flow(state=raw_state, verifier=verifier)
                # Passing only the code avoids logging or reparsing callback URLs.
                flow.fetch_token(code=request.query_params.get('code', ''), code_verifier=verifier, timeout=30)
                from .youtube_auth import SCOPE
                if not flow.credentials.has_scopes([SCOPE]) or not flow.credentials.refresh_token:
                    raise ValueError('missing readonly scope or offline token')
                serialized = flow.credentials.to_json()
                client = client_factory(serialized)
                channel_id, title, playlist = client.channel()
                key = 'youtube/' + str(uuid4())
                new_key = key
                with factory() as session:
                    session.connection().exec_driver_sql('BEGIN IMMEDIATE')
                    pending = session.get(YouTubeOAuthState, digest(raw_state))
                    if not pending or pending.browser_digest != 'consumed' or pending.expires_at <= time.time():
                        raise ValueError('authorization cancelled')
                    session.delete(pending)
                    connection = session.scalar(select(YouTubeConnection).where(YouTubeConnection.owner_id == OWNER))
                    if connection and connection.channel_id != channel_id:
                        raise ValueError('account switching requires disconnect')
                    old_key = connection.token_key if connection else None
                    storage.set(key, client.serialized())
                    if connection is None:
                        connection = YouTubeConnection(id=str(uuid4()), owner_id=OWNER, channel_id=channel_id, channel_title=title, playlist_id=playlist, token_key=key, status='connected')
                        session.add(connection)
                    else:
                        for job in session.scalars(select(YouTubeSync).where(YouTubeSync.connection_id == connection.id, YouTubeSync.state.in_(ACTIVE))):
                            job.state, job.cancel_requested = 'cancelled', True
                        connection.channel_id, connection.channel_title, connection.playlist_id = channel_id, title, playlist
                        connection.token_key, connection.status = key, 'connected'
                    if old_key:
                        storage.delete(old_key)
                    session.commit()
                new_key = None
                outcome = 'connected'
        except Exception:
            # OAuth library errors can contain credentials. Never expose or log them.
            outcome = 'error'
        finally:
            try:
                with factory() as session:
                    pending = session.get(YouTubeOAuthState, digest(request.query_params.get('state', '')))
                    if pending and pending.browser_digest == 'consumed':
                        token_store().delete(pending.verifier_key)
                        session.delete(pending)
                        session.commit()
                if new_key:
                    token_store().delete(new_key)
            except Exception:
                pass
        response = RedirectResponse(frontend.rstrip('/') + '/?youtube=' + outcome, status_code=303, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
        response.delete_cookie(COOKIE, path='/api/v1/youtube/oauth')
        return response

    @router.post('/sync')
    def create_sync(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        try:
            return start_sync(factory)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @router.get('/sync')
    def read_sync(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with factory() as session:
            return sync_view(session, latest(session))

    @router.post('/sync/cancel')
    def cancel(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with factory() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            job = latest(session)
            if job and job.state in ACTIVE:
                job.cancel_requested = True
                if job.state == 'queued':
                    job.state = 'cancelled'
                job.updated_at = time.time()
            result = sync_view(session, job)
            session.commit()
            return result

    @router.post('/disconnect')
    def disconnect(response: Response):
        response.headers['Cache-Control'] = 'no-store'
        with factory() as session:
            session.connection().exec_driver_sql('BEGIN IMMEDIATE')
            connection = session.scalar(select(YouTubeConnection).where(YouTubeConnection.owner_id == OWNER))
            pending_keys = []
            for pending in session.scalars(select(YouTubeOAuthState)):
                pending_keys.append(pending.verifier_key)
                session.delete(pending)
            if not connection:
                session.commit()
                for pending_key in pending_keys:
                    token_store().delete(pending_key)
                return {'disconnected': True, 'revoke_pending': False}
            key = connection.token_key
            connection.status = 'disconnected'
            for job in session.scalars(select(YouTubeSync).where(YouTubeSync.connection_id == connection.id, YouTubeSync.state.in_(ACTIVE))):
                job.state, job.cancel_requested = 'cancelled', True
            session.commit()
        try:
            storage = token_store()
            for pending_key in pending_keys:
                storage.delete(pending_key)
            serialized = storage.get(key)
            revoked = revoke(serialized) if serialized else True
            storage.delete(key)
        except Exception:
            raise HTTPException(503, '帳號已停用，但 Windows 認證尚未清除，請檢查認證服務後再解除連結。') from None
        return {'disconnected': True, 'revoke_pending': not revoked}

    return router
