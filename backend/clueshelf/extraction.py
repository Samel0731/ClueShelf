"""Anonymous public extraction. Every upstream request uses a validated, pinned IP."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urljoin, urlsplit

from pydantic import BaseModel, Field


class Comment(BaseModel):
    source_id: str
    text: str
    likes: int | None = None
    url: str | None = None


class ExtractionResult(BaseModel):
    original_title: str = ""
    author_text: str = ""
    canonical_url: str | None = None
    comments: list[Comment] = Field(default_factory=list)
    comments_ranking: Literal["likes", "visible", "unavailable", "not_applicable"] = "not_applicable"
    fetched_count: int = 0
    status: Literal["complete", "partial", "blocked", "failed"] = "partial"
    reason: str | None = None
    fetched_at: float = Field(default_factory=time.time)


HOSTS = {
    "youtube": ("youtube.com", "youtu.be", "ytimg.com", "googlevideo.com"),
    "instagram": ("instagram.com", "cdninstagram.com", "fbcdn.net"),
    "threads": ("threads.com", "threads.net", "cdninstagram.com", "fbcdn.net", "instagram.com"),
}
MAX_BYTES = 5 * 1024 * 1024


def validate_destination(url: str, platform: str, *, resolve=True):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("不允許的來源網址")
    if not any(host == root or host.endswith("." + root) for root in HOSTS[platform]):
        raise ValueError("來源網域不在允許範圍")
    if resolve:
        addresses = list(dict.fromkeys(info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError("來源指向非公開網路")
        return parsed, addresses[0]
    return parsed, None


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        raw = socket.create_connection((self.ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


@dataclass
class PublicResponse:
    url: str
    status: int
    content_type: str
    body: bytes
    cookies: list[str] = field(default_factory=list)


def fetch_public(url: str, platform: str, *, deadline=None, headers=None):
    deadline = deadline or time.monotonic() + 25
    headers = {key.lower(): value for key, value in (headers or {}).items()}
    for _ in range(5):
        if time.monotonic() >= deadline:
            raise TimeoutError("來源讀取逾時")
        parsed, address = validate_destination(url, platform)
        connection = PinnedHTTPS(parsed.hostname, address, max(1, min(8, deadline - time.monotonic())))
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={"user-agent": "ClueShelf/0.2 public-content-reader", "accept": "text/html,application/json,*/*;q=0.5", "accept-encoding": "identity", **headers})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                target = urljoin(url, response.getheader("Location", ""))
                if urlsplit(target).hostname != parsed.hostname:
                    headers = {key: value for key, value in headers.items() if key.lower() not in {"cookie", "referer"}}
                url = target
                continue
            if int(response.getheader("Content-Length", "0")) > MAX_BYTES:
                raise ValueError("來源內容超過大小限制")
            content = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("來源讀取逾時")
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError("來源內容超過大小限制")
            return PublicResponse(url, response.status, response.getheader("Content-Type", ""), bytes(content), [value for key, value in response.getheaders() if key.lower() == "set-cookie"])
        finally:
            connection.close()
    raise ValueError("來源跳轉次數過多")


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.scripts = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property", attrs.get("name", ""))
            if key:
                self.meta[key] = attrs.get("content", "")
        if tag == "link" and attrs.get("rel") == "canonical":
            self.meta["canonical"] = attrs.get("href", "")
        if tag == "script":
            self.active = []

    def handle_data(self, data):
        if self.active is not None:
            self.active.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active is not None:
            self.scripts.append("".join(self.active))
            self.active = None


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def script_objects(scripts):
    decoder = json.JSONDecoder()
    for script in scripts:
        try:
            yield json.loads(script)
            continue
        except (ValueError, RecursionError):
            pass
        for marker in ("ytInitialPlayerResponse =", "ytInitialPlayerResponse="):
            if marker in script:
                try:
                    yield decoder.raw_decode(script.split(marker, 1)[1].lstrip())[0]
                except (ValueError, RecursionError):
                    pass


def caption(post):
    value = post.get("caption")
    return value.get("text", "") if isinstance(value, dict) and isinstance(value.get("text"), str) else ""


def rank_comments(comments: list[Comment]):
    unique = list({c.source_id: c for c in comments if c.source_id.strip() and c.text.strip()}.values())[:50]
    known = [c for c in unique if c.likes is not None]
    return (sorted(known, key=lambda c: -c.likes)[:10], "likes", len(unique)) if known else (unique[:10], "visible" if unique else "unavailable", len(unique))


def parse_public_html(platform: str, html: str, canonical_url: str):
    parser = MetadataParser()
    parser.feed(html)
    objects = list(script_objects(parser.scripts))
    nodes = [node for obj in objects for node in walk(obj)]
    result = ExtractionResult(canonical_url=canonical_url, comments_ranking="unavailable" if platform == "threads" else "not_applicable")
    if platform == "youtube":
        details = next((n["videoDetails"] for n in nodes if isinstance(n.get("videoDetails"), dict)), None)
        if details:
            result.original_title = str(details.get("title", ""))[:500]
            result.author_text = str(details.get("shortDescription", ""))[:50000]
            result.status = "complete" if result.original_title and result.author_text else "partial"
            return result
    code_match = re.search(r"/(?:post|p|reel|reels)/([A-Za-z0-9_-]+)", urlsplit(canonical_url).path)
    code = code_match[1] if code_match else None
    roots = [n for n in nodes if code and n.get("code") == code and caption(n)]
    def reply_count(node):
        info = node.get("text_post_app_info") or {}
        direct = info.get("direct_replies") or {} if isinstance(info, dict) else {}
        return len(direct.get("edges") or []) if isinstance(direct, dict) else 0
    root = max(roots, key=reply_count, default=None)
    if root:
        result.author_text = caption(root)[:50000]
        if platform == "threads":
            root_id = str(root.get("pk", root.get("id", "")))
            replies = []
            identity = root_id.split("_", 1)[0]
            # Downward-query media omits caption/code and uses a composite media_user ID.
            same_post = [n for n in nodes if identity and str(n.get("pk", n.get("id", ""))).split("_", 1)[0] == identity]
            reply_root = max(same_post, key=reply_count, default=root)
            app_info = reply_root.get("text_post_app_info", {})
            direct = app_info.get("direct_replies", {}) if isinstance(app_info, dict) else {}
            edges = direct.get("edges", []) if isinstance(direct, dict) else []
            for edge in edges[:50]:
                thread = edge.get("node", {}) if isinstance(edge, dict) else {}
                posts = thread.get("posts", {}) if isinstance(thread, dict) else {}
                post_edges = posts.get("edges", []) if isinstance(posts, dict) else []
                # A direct-reply thread can include a conversation continuation. Only its first post is top-level.
                first = post_edges[0].get("node", {}) if post_edges and isinstance(post_edges[0], dict) else {}
                if not isinstance(first, dict) or not caption(first):
                    continue
                info = first.get("text_post_app_info", {})
                if isinstance(info, dict) and info.get("reply_level", 1) != 1:
                    continue
                likes = first.get("like_count")
                reply_url = first.get("canonical_url")
                replies.append(Comment(source_id=str(first.get("pk", first.get("id", ""))), text=caption(first)[:10000], likes=likes if isinstance(likes, int) and not isinstance(likes, bool) and likes >= 0 else None, url=reply_url if isinstance(reply_url, str) and reply_url.startswith("https://www.threads.com/") else None))
            for n in nodes:
                relation = n.get("reply_to_id", n.get("parent_id"))
                if root_id and relation is not None and str(relation) == root_id and caption(n):
                    likes = n.get("like_count")
                    replies.append(Comment(source_id=str(n.get("pk", n.get("id", n.get("code", "")))), text=caption(n)[:10000], likes=likes if isinstance(likes, int) and not isinstance(likes, bool) and likes >= 0 else None))
            result.comments, result.comments_ranking, result.fetched_count = rank_comments(replies)
            if result.comments_ranking == "likes" and any(c.likes is None for c in replies[:50]):
                result.reason = "僅依取得的留言中具有讚數者排序，並非全貼文熱門排名。"
    if not result.author_text:
        # JSON-LD articleBody is author content. OG descriptions may be truncated/social wrappers.
        article = next((n for n in nodes if n.get("@type") in ("SocialMediaPosting", "Article", "VideoObject") and isinstance(n.get("articleBody"), str)), None)
        if article:
            result.author_text = article["articleBody"][:50000]
        else:
            description = unescape(parser.meta.get("og:description", "")).strip()
            if description and not any(text in description.lower() for text in ("log in", "login", "sign up", "登入以", "登錄以")):
                result.author_text = description[:50000]
                result.reason = "僅取得公開預覽說明，可能截斷；可補充完整作者內文。"
    if platform == "youtube":
        result.original_title = parser.meta.get("og:title", "")[:500]
    if result.author_text:
        result.status = "partial" if result.reason or platform == "threads" and result.comments_ranking == "unavailable" else "complete"
        if platform == "threads" and result.comments_ranking == "unavailable":
            result.reason = "已取得正文，但未取得可驗證為本貼文頂層回覆的留言。"
    else:
        result.status = "blocked" if any(s in html.lower() for s in ("login", "log in", "checkpoint", "captcha", "登入")) else "partial"
        result.reason = "公開頁面未提供可讀取的作者內容，請手動補充。"
    return result


def render_public(platform, url):
    from playwright.sync_api import sync_playwright

    deadline = time.monotonic() + 45
    budget = {"requests": 0, "bytes": 0}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block", accept_downloads=False, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36", locale="zh-TW")
            context.route_web_socket("**/*", lambda websocket: websocket.close())

            def route_request(route):
                request = route.request
                if request.method != "GET" or request.resource_type in {"media", "image", "font", "websocket"}:
                    route.abort()
                    return
                budget["requests"] += 1
                if budget["requests"] > 80 or budget["bytes"] > 20 * 1024 * 1024 or time.monotonic() >= deadline:
                    route.abort()
                    return
                try:
                    forwarded = {key: value for key, value in request.all_headers().items() if key in {"user-agent", "accept", "accept-language", "referer", "cookie"}}
                    data = fetch_public(request.url, platform, deadline=deadline, headers=forwarded)
                    budget["bytes"] += len(data.body)
                    if data.url != request.url:
                        route.fulfill(status=302, headers={"location": data.url}, body="")
                    else:
                        response_headers = {"content-type": data.content_type}
                        if data.cookies:
                            response_headers["set-cookie"] = "\n".join(data.cookies)
                        route.fulfill(status=data.status, headers=response_headers, body=data.body)
                except Exception:
                    route.abort()

            context.route("**/*", route_request)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(1500)
            canonical = page.locator('link[rel="canonical"]').first.get_attribute("href") if page.locator('link[rel="canonical"]').count() else page.url
            validate_destination(canonical or page.url, platform, resolve=False)
            main_hosts = ("instagram.com",) if platform == "instagram" else ("threads.com", "threads.net")
            host = (urlsplit(canonical or page.url).hostname or "").lower()
            if not any(host == root or host.endswith("." + root) for root in main_hosts):
                raise ValueError("主要頁面離開原平台")
            html = page.content()
            if len(html.encode()) > MAX_BYTES:
                raise ValueError("來源頁面過大")
            return html, canonical or page.url
        finally:
            browser.close()


def extract(platform: str, url: str) -> ExtractionResult:
    try:
        validate_destination(url, platform)
        response = fetch_public(url, platform)
        if response.status >= 400:
            return ExtractionResult(status="blocked" if response.status in (401, 403, 429) else "failed", reason=f"來源回應 HTTP {response.status}", comments_ranking="unavailable" if platform == "threads" else "not_applicable")
        html = response.body.decode("utf-8", "replace")
        parser = MetadataParser()
        parser.feed(html)
        canonical = parser.meta.get("canonical", parser.meta.get("og:url", response.url))
        validate_destination(canonical, platform, resolve=False)
        initial = parse_public_html(platform, html, canonical)
        if platform == "threads" and canonical.rstrip("/") != response.url.rstrip("/"):
            resolved = fetch_public(canonical, platform)
            if resolved.status == 200:
                full_page = parse_public_html(platform, resolved.body.decode("utf-8", "replace"), canonical)
                if full_page.author_text or full_page.comments:
                    initial = full_page
        if platform == "youtube" or initial.status == "complete":
            return initial
        try:
            html, canonical = render_public(platform, canonical)
        except Exception as error:
            initial.status = "partial" if initial.author_text else "failed"
            initial.reason = "尚未安裝讀取用 Chromium，請先執行 playwright install chromium。" if "Executable doesn't exist" in str(error) else "公開頁面進一步讀取未完成；保留已取得的內容，可手動補充。"
            return initial
        rendered = parse_public_html(platform, html, canonical)
        # A rendered hydration snapshot can omit reply data present in the initial HTML.
        if initial.comments and len(initial.comments) >= len(rendered.comments):
            return initial
        return initial if initial.author_text and not rendered.author_text else rendered
    except Exception as error:
        missing_browser = "Executable doesn't exist" in str(error)
        reason = "尚未安裝讀取用 Chromium，請先執行 playwright install chromium。" if missing_browser else f"公開內容讀取未完成（{type(error).__name__}）；可補充作者內文。"
        return ExtractionResult(status="failed", reason=reason, comments_ranking="unavailable" if platform == "threads" else "not_applicable")
