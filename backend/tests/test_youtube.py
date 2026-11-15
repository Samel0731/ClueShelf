import json
import time
from urllib.parse import urlsplit, parse_qs
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from clueshelf.api import create_app
from clueshelf.database import Base, make_engine, session_factory
from clueshelf.models import Save, Job
from clueshelf.youtube_models import YouTubeConnection, YouTubeSync, YouTubeSource, YouTubeOAuthState
from clueshelf.youtube_api import create_router
from clueshelf.youtube_auth import YouTubeError, digest, Settings
from clueshelf.youtube_sync import start_sync, run_once, claim, fail


class Store:
    def __init__(self): self.values = {}
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value
    def delete(self, key): self.values.pop(key, None)


@pytest.fixture
def system(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'youtube.db'}")
    Base.metadata.create_all(engine)
    factory, store = session_factory(engine), Store()
    with factory() as session:
        session.add(YouTubeConnection(id='connection', owner_id='local-developer', channel_id='channel', channel_title='頻道', playlist_id='likes', token_key='token', status='connected'))
        session.commit()
    store.set('token','private-token')
    yield factory, store
    engine.dispose()


def page_client(pages):
    class Client:
        def __init__(self, serialized): assert serialized == 'private-token'
        def serialized(self): return 'private-token'
        def page(self, playlist, cursor):
            result = pages[cursor]
            if isinstance(result, Exception): raise result
            return result
    return Client


def test_pages_dedup_private_manual_preserved_and_unchanged_no_ai(system):
    factory, store = system
    pages = {None: (['abcdefghijk','deleted0000'], {'abcdefghijk': {'title':'日文','description':'說明'}}, 'next'), 'next': (['abcdefghijk','zyxwvutsrqp'], {'abcdefghijk': {'title':'日文','description':'說明'},'zyxwvutsrqp': {'title':'第二','description':'第二說明'}}, None)}
    job = start_sync(factory)
    assert start_sync(factory)['id'] == job['id']
    assert run_once(factory, store, page_client(pages))
    with factory() as session:
        assert session.get(YouTubeSync, job['id']).cursor == 'next'
        save = session.scalar(select(Save).where(Save.content_id == 'abcdefghijk'))
        save.title, save.author_text, save.title_manual, save.text_manual = '自訂','人工',True,True
        save.manual_topics, save.manual_tags = ['程式'],['自己的']
        session.commit()
    assert run_once(factory, store, page_client(pages))
    with factory() as session:
        current = session.get(YouTubeSync, job['id'])
        assert (current.state,current.read_count,current.new_count,current.existing_count,current.skipped_count) == ('completed',4,2,1,1)
        assert session.get(YouTubeConnection,'connection').last_complete_scan_at
        save = session.scalar(select(Save).where(Save.content_id == 'abcdefghijk'))
        assert (save.title,save.author_text,save.manual_topics,save.manual_tags) == ('自訂','人工',['程式'],['自己的'])
        imported_id = save.id
        jobs = session.scalars(select(Job)).all()
        assert len(jobs) == 2 and all(job.kind == 'analyze' for job in jobs)
    with TestClient(create_app(factory)) as client:
        path = f"/api/v1/saves/{imported_id}"
        assert client.get(path).json()["video_analysis"] is None
        assert client.post(path + "/video-analysis", json={"mode": "text"}).json()["video_analysis"]["state"] == "queued"
    start_sync(factory)
    run_once(factory,store,page_client(pages)); run_once(factory,store,page_client(pages))
    with factory() as session:
        assert len(session.scalars(select(Job)).all()) == 2


def test_restart_cursor_errors_and_quota(system):
    factory, store = system
    job = start_sync(factory)
    broken = page_client({None: ([],{},'expired'), 'expired': YouTubeError('cursor','游標失效')})
    run_once(factory,store,broken)
    run_once(factory,store,broken)
    with factory() as session:
        current = session.get(YouTubeSync,job['id'])
        assert current.cursor is None and current.cursor_restarts == 1
    run_once(factory,store,page_client({None: YouTubeError('quota','配額耗盡')}))
    with factory() as session:
        assert session.get(YouTubeSync,job['id']).state == 'paused'
    assert start_sync(factory)['id'] == job['id']
    run_once(factory,store,page_client({None: ([],{},None)}))
    with factory() as session:
        assert session.get(YouTubeSync,job['id']).state == 'completed'


def test_expired_lease_fences_old_writer_and_auth_requires_reconnect(system):
    factory, store = system
    job = start_sync(factory)
    old, _ = claim(factory)
    with factory() as session:
        session.get(YouTubeSync,job['id']).lease_until = time.time()-1
        session.commit()
    newer, _ = claim(factory)
    fail(factory, old, YouTubeError('auth','expired'))
    with factory() as session:
        assert session.get(YouTubeConnection,'connection').status == 'connected'
        assert session.get(YouTubeSync,job['id']).lease_token == newer.lease_token
    fail(factory,newer,YouTubeError('auth','expired'))
    with factory() as session:
        assert session.get(YouTubeConnection,'connection').status == 'reauthorize'


def test_transient_three_attempts_and_cancel_current_batch(system):
    factory, store = system
    job = start_sync(factory)
    client = page_client({None:YouTubeError('transient','offline')})
    for _ in range(3):
        run_once(factory,store,client)
        with factory() as session:
            session.get(YouTubeSync,job['id']).available_at = 0
            session.commit()
    with factory() as session:
        assert session.get(YouTubeSync,job['id']).state == 'failed'
        assert session.get(YouTubeSync,job['id']).attempts == 3
    start_sync(factory)
    class Cancelling:
        def __init__(self,_): pass
        def serialized(self): return 'private-token'
        def page(self,*args):
            with factory() as session:
                session.get(YouTubeSync,job['id']).cancel_requested = True
                session.commit()
            return ['abcdefghijk'], {'abcdefghijk':{'title':'保存此批','description':'原文'}},'more'
    run_once(factory,store,Cancelling)
    with factory() as session:
        assert session.get(YouTubeSync,job['id']).state == 'cancelled'
        assert session.scalar(select(Save)).title == '保存此批'


class FakeCredentials:
    refresh_token='refresh'
    def has_scopes(self, scopes): return True
    def to_json(self): return 'private-token'


class FakeFlow:
    code_verifier = 'verifier-secret'
    credentials = FakeCredentials()
    def authorization_url(self, **kwargs): return 'https://accounts.google.com/authorize', 'state'
    def fetch_token(self, **kwargs): assert kwargs['code_verifier'] == 'verifier-secret'


@pytest.fixture
def oauth(system, monkeypatch):
    factory, store = system
    class Config:
        callback='http://127.0.0.1:8000/api/v1/youtube/oauth/callback'
        frontend='http://127.0.0.1:3000/'
        def flow(self, **kwargs): return FakeFlow()
    monkeypatch.setattr('clueshelf.youtube_api.configuration', lambda: (Config(),None))
    opened=[]
    monkeypatch.setattr('clueshelf.youtube_api.webbrowser.open',lambda url,**kwargs: opened.append(url) or True)
    monkeypatch.setattr('clueshelf.youtube_api.revoke',lambda _: True)
    class Client:
        def __init__(self,_): pass
        def channel(self): return 'channel','我的頻道','likes'
        def serialized(self): return 'private-token'
    app=FastAPI(); app.include_router(create_router(factory,store,Client))
    return factory,store,app,opened


def begin(app,opened):
    # The UI and system browser intentionally have separate cookie jars.
    with TestClient(app,base_url='http://127.0.0.1:8000') as ui:
        assert ui.post('/api/v1/youtube/oauth/start').json() == {'opened':True}
        assert not ui.cookies.get('clueshelf_youtube_oauth')
    return parse_qs(urlsplit(opened[-1]).query)['state'][0]


def test_system_browser_launch_cookie_state_replay_and_clean_callback(oauth):
    factory,store,app,opened=oauth
    state=begin(app,opened)
    with TestClient(app,base_url='http://127.0.0.1:8000',follow_redirects=False) as browser:
        assert browser.get(opened[-1]).status_code == 303
        assert browser.get(opened[-1]).status_code == 400
        response=browser.get('/api/v1/youtube/oauth/callback',params={'state':state,'code':'AUTH_SECRET'})
        assert response.headers['location'] == 'http://127.0.0.1:3000/?youtube=connected'
        assert response.headers['cache-control'] == 'no-store'
        assert 'AUTH_SECRET' not in response.text
        assert browser.get('/api/v1/youtube/oauth/callback',params={'state':state,'code':'AUTH_SECRET'}).headers['location'].endswith('youtube=error')
    with factory() as session:
        assert session.get(YouTubeOAuthState,digest(state)) is None
        assert session.get(YouTubeConnection,'connection').channel_title == '我的頻道'


@pytest.mark.parametrize('failure',['denied','expired','wrong_browser'])
def test_oauth_denied_expired_wrong_browser(oauth,failure):
    factory,store,app,opened=oauth
    state=begin(app,opened)
    with TestClient(app,base_url='http://127.0.0.1:8000',follow_redirects=False) as browser:
        browser.get(opened[-1])
        if failure == 'expired':
            with factory() as session:
                session.get(YouTubeOAuthState,digest(state)).expires_at = time.time()-1
                session.commit()
        if failure == 'wrong_browser': browser.cookies.clear()
        result=browser.get('/api/v1/youtube/oauth/callback',params={'state':state,'error':'access_denied'})
        assert result.headers['location'].endswith('youtube=denied' if failure=='denied' else 'youtube=error')


def test_disconnect_invalidates_pending_and_keeps_saves(oauth):
    factory,store,app,opened=oauth
    state=begin(app,opened)
    with TestClient(app,base_url='http://127.0.0.1:8000',follow_redirects=False) as browser:
        browser.get(opened[-1])
        assert browser.post('/api/v1/youtube/disconnect').json() == {'disconnected':True,'revoke_pending':False}
        assert browser.get('/api/v1/youtube/oauth/callback',params={'state':state,'code':'SECRET'}).headers['location'].endswith('youtube=error')
    assert not store.values


def test_settings_reject_desktop_client_and_bad_callback(tmp_path,monkeypatch):
    path=tmp_path/'client.json'; path.write_text(json.dumps({'installed': {'client_id':'id'}}))
    monkeypatch.setenv('CLUESHELF_GOOGLE_CLIENT_FILE',str(path))
    with pytest.raises(ValueError): Settings.load()

def test_disconnect_during_oauth_exchange_cannot_reconnect(oauth,monkeypatch):
    factory,store,app,opened=oauth
    state=begin(app,opened)
    original=FakeFlow.fetch_token
    def fetch(self,**kwargs):
        original(self,**kwargs)
        with TestClient(app,base_url='http://127.0.0.1:8000') as client:
            assert client.post('/api/v1/youtube/disconnect').status_code == 200
    monkeypatch.setattr(FakeFlow,'fetch_token',fetch)
    with TestClient(app,base_url='http://127.0.0.1:8000',follow_redirects=False) as browser:
        browser.get(opened[-1])
        response=browser.get('/api/v1/youtube/oauth/callback',params={'state':state,'code':'SECRET'})
        assert response.headers['location'].endswith('youtube=error')
    with factory() as session:
        assert session.get(YouTubeConnection,'connection').status == 'disconnected'
    assert not store.values


def test_source_change_supersedes_old_job_preserving_manual(system):
    factory,store=system
    start_sync(factory)
    run_once(factory,store,page_client({None:(['abcdefghijk'],{'abcdefghijk':{'title':'初版','description':'原內文'}},None)}))
    with factory() as session:
        save=session.scalar(select(Save))
        save.title,save.author_text,save.title_manual,save.text_manual='手動標題','手動內文',True,True
        old_id=session.scalar(select(Job)).id
        session.commit()
    start_sync(factory)
    run_once(factory,store,page_client({None:(['abcdefghijk'],{'abcdefghijk':{'title':'新版','description':'來源更新'}},None)}))
    with factory() as session:
        save=session.scalar(select(Save))
        assert (save.title,save.author_text)==('手動標題','手動內文')
        assert save.source['author_text']=='來源更新'
        assert save.source['provider']=='youtube_api'
        assert save.version==2
        assert session.get(Job,old_id).state=='superseded'


def test_disconnect_during_page_does_not_resurrect_token(system):
    factory,store=system
    start_sync(factory)
    class Disconnect:
        def __init__(self,_): pass
        def serialized(self): return 'should-not-reappear'
        def page(self,*args):
            with factory() as session:
                session.get(YouTubeConnection,'connection').status='disconnected'
                session.scalar(select(YouTubeSync)).state='cancelled'
                session.commit()
            store.delete('token')
            return ['abcdefghijk'],{'abcdefghijk':{'title':'must not save'}},None
    run_once(factory,store,Disconnect)
    assert not store.values
    with factory() as session:
        assert session.scalar(select(Save)) is None

def test_official_client_page_batches_metadata_and_classifies_quota(monkeypatch):
    from clueshelf.youtube_auth import GoogleClient
    client=object.__new__(GoogleClient)
    seen=[]
    def get(resource,**params):
        seen.append((resource,params))
        if resource=='playlistItems': return {'items':[{'contentDetails':{'videoId':'abcdefghijk'}},{'contentDetails':{'videoId':'abcdefghijk'}},{'contentDetails':{'videoId':'missing0000'}}],'nextPageToken':'next'}
        return {'items':[{'id':'abcdefghijk','snippet':{'title':'完整','description':'全文'}}]}
    client.get=get
    ids,videos,cursor=client.page('LLchannel',None)
    assert ids==['abcdefghijk','abcdefghijk','missing0000']
    assert videos['abcdefghijk']['description']=='全文' and cursor=='next'
    assert seen[0]==('playlistItems',{'part':'contentDetails','playlistId':'LLchannel','maxResults':50})
    assert seen[1]==('videos',{'part':'snippet','id':'abcdefghijk,missing0000'})


def test_refresh_retryable_and_revoked_are_distinguished(monkeypatch):
    from clueshelf.youtube_auth import GoogleClient
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import RefreshError
    class Expired:
        valid=False
        def refresh(self,request): raise RefreshError('provider details must stay private',retryable=True)
    monkeypatch.setattr(Credentials,'from_authorized_user_info',lambda *args,**kwargs:Expired())
    with pytest.raises(YouTubeError) as raised: GoogleClient('{}')
    assert raised.value.kind=='transient' and 'provider details' not in str(raised.value)
    class Revoked:
        valid=False
        def refresh(self,request): raise RefreshError('private revoked detail')
    monkeypatch.setattr(Credentials,'from_authorized_user_info',lambda *args,**kwargs:Revoked())
    with pytest.raises(YouTubeError) as raised: GoogleClient('{}')
    assert raised.value.kind=='auth' and 'private revoked' not in str(raised.value)
