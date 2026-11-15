"""Google OAuth and Windows credential storage. Never log credential exceptions."""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
import httpx

SCOPE = 'https://www.googleapis.com/auth/youtube.readonly'
CALLBACK = 'http://127.0.0.1:8000/api/v1/youtube/oauth/callback'
ROOT = Path(__file__).resolve().parents[2]


class TokenStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class WindowsTokenStore:
    """Generic credentials belong to the current Windows login only."""
    class Credential(ctypes.Structure):
        _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)), ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]

    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('本機權杖保存需要 Windows Credential Manager。')
        self.api = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(self.Credential), wintypes.DWORD]
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(self.Credential))]
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def get(self, key):
        pointer = ctypes.POINTER(self.Credential)()
        if not self.api.CredReadW('ClueShelf/' + key, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise RuntimeError('無法讀取 Windows 認證。')
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode('utf-8')
        finally:
            self.api.CredFree(pointer)

    def set(self, key, value):
        data = value.encode('utf-8')
        if len(data) > 2560:
            raise RuntimeError('Google 認證超過 Windows Credential Manager 容量。')
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        credential = self.Credential(Type=1, TargetName='ClueShelf/' + key, CredentialBlobSize=len(data), CredentialBlob=buffer, Persist=2, UserName='ClueShelf')
        if not self.api.CredWriteW(ctypes.byref(credential), 0):
            raise RuntimeError('無法保存 Windows 認證。')

    def delete(self, key):
        if not self.api.CredDeleteW('ClueShelf/' + key, 1, 0) and ctypes.get_last_error() != 1168:
            raise RuntimeError('無法清除 Windows 認證。')


@dataclass(frozen=True)
class Settings:
    client_file: Path
    callback: str
    frontend: str

    @classmethod
    def load(cls):
        path = Path(os.environ.get('CLUESHELF_GOOGLE_CLIENT_FILE', str(ROOT / 'data/google-client.json')))
        callback = os.environ.get('CLUESHELF_YOUTUBE_CALLBACK', CALLBACK)
        frontend = os.environ.get('CLUESHELF_FRONTEND_URL', 'http://127.0.0.1:3000/')
        for value in (callback, frontend):
            url = urlsplit(value)
            if url.username or url.password or url.query or url.fragment or url.scheme not in {'http', 'https'}:
                raise ValueError('YouTube 網址設定無效。')
            if url.scheme != 'https' and url.hostname not in {'127.0.0.1', 'localhost'}:
                raise ValueError('非本機網址必須使用 HTTPS。')
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        web = config.get('web', {})
        if not web.get('client_id') or not web.get('client_secret') or callback not in web.get('redirect_uris', []):
            raise ValueError('請使用 Web OAuth client，並加入正確的 callback 網址。')
        # OAuth endpoints are fixed even when the downloaded client file is edited.
        if web.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth' or web.get('token_uri') != 'https://oauth2.googleapis.com/token':
            raise ValueError('Google OAuth client 的授權端點不符。')
        return cls(path, callback, frontend)

    def flow(self, *, state=None, verifier=None):
        from google_auth_oauthlib.flow import Flow
        return Flow.from_client_secrets_file(str(self.client_file), scopes=[SCOPE], redirect_uri=self.callback, state=state, code_verifier=verifier, autogenerate_code_verifier=verifier is None)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class YouTubeError(RuntimeError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


class GoogleClient:
    def __init__(self, serialized):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google.auth.exceptions import RefreshError
        from requests.exceptions import RequestException
        import requests
        self.credentials = Credentials.from_authorized_user_info(json.loads(serialized), scopes=[SCOPE])
        try:
            if not self.credentials.valid:
                session = requests.Session()
                session.trust_env = False
                request = Request(session=session)
                def bounded_request(*args, **kwargs):
                    kwargs['timeout'] = 25
                    return request(*args, **kwargs)
                self.credentials.refresh(bounded_request)
        except RefreshError as error:
            if error.retryable:
                raise YouTubeError('transient', 'Google 認證服務暫時失敗，稍後重試。') from None
            raise YouTubeError('auth', 'Google 授權已失效，請重新連結。') from None
        except RequestException:
            raise YouTubeError('transient', 'Google 連線暫時失敗，稍後重試。') from None

    def serialized(self):
        return self.credentials.to_json()

    def get(self, resource, **params):
        try:
            response = httpx.get('https://www.googleapis.com/youtube/v3/' + resource, params=params, headers={'Authorization': 'Bearer ' + self.credentials.token}, timeout=25, trust_env=False)
        except httpx.HTTPError:
            raise YouTubeError('transient', 'YouTube 連線暫時失敗，稍後重試。') from None
        if response.status_code >= 400:
            try:
                reasons = [item.get('reason') for item in response.json().get('error', {}).get('errors', [])]
            except (ValueError, AttributeError, TypeError):
                reasons = []
            if response.status_code == 401:
                raise YouTubeError('auth', 'Google 授權已失效，請重新連結。')
            if any(reason in {'quotaExceeded', 'dailyLimitExceeded'} for reason in reasons):
                raise YouTubeError('quota', 'YouTube API 配額已用完，請稍後手動再次同步。')
            if 'invalidPageToken' in reasons:
                raise YouTubeError('cursor', 'YouTube 分頁游標已失效。')
            if response.status_code == 429 or response.status_code >= 500:
                raise YouTubeError('transient', 'YouTube 暫時無法回應，稍後重試。')
            raise YouTubeError('permanent', 'YouTube API 無法取得資料，請檢查 API 與頻道設定。')
        try:
            return response.json()
        except ValueError:
            raise YouTubeError('transient', 'YouTube 回應格式無效。') from None

    def channel(self):
        items = self.get('channels', part='snippet,contentDetails', mine='true').get('items', [])
        if len(items) != 1:
            raise YouTubeError('permanent', '請授權一個可存取的 YouTube 頻道。')
        channel = items[0]
        likes = channel.get('contentDetails', {}).get('relatedPlaylists', {}).get('likes')
        if not likes:
            raise YouTubeError('permanent', '此頻道沒有可存取的按讚清單。')
        return channel['id'], channel['snippet']['title'], likes

    def page(self, playlist_id, cursor):
        params = dict(part='contentDetails', playlistId=playlist_id, maxResults=50)
        if cursor:
            params['pageToken'] = cursor
        page = self.get('playlistItems', **params)
        ids = [item.get('contentDetails', {}).get('videoId', '') for item in page.get('items', [])]
        valid = list(dict.fromkeys(identity for identity in ids if identity))
        videos = self.get('videos', part='snippet', id=','.join(valid)).get('items', []) if valid else []
        return ids, {video['id']: video['snippet'] for video in videos}, page.get('nextPageToken')


def revoke(serialized):
    try:
        token = json.loads(serialized).get('refresh_token') or json.loads(serialized).get('token')
        response = httpx.post('https://oauth2.googleapis.com/revoke', data={'token': token}, timeout=15, trust_env=False)
        return response.status_code in {200, 400}
    except (httpx.HTTPError, ValueError):
        return False
