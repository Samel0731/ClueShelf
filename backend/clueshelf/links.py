import re
from urllib.parse import parse_qs, urlsplit


def parse_link(raw: str) -> tuple[str, str, str]:
    try:
        u = urlsplit(raw.strip())
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
            raise ValueError()
        host = (u.hostname or "").lower()
        path = u.path.rstrip("/")
        if host == "youtu.be":
            content_id = path.lstrip("/")
            platform = "youtube"
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            if len(parse_qs(u.query).get("v", [])) > 1:
                raise ValueError()
            match = re.fullmatch(r"/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})", path)
            content_id = match[1] if match else parse_qs(u.query).get("v", [""])[0] if path == "/watch" else ""
            platform = "youtube"
        elif host in {"instagram.com", "www.instagram.com"}:
            match = re.fullmatch(r"/(?:p|reel|reels)/([A-Za-z0-9_-]+)", path)
            if not match:
                raise ValueError()
            content_id, platform = match[1], "instagram"
        elif host in {"threads.net", "www.threads.net", "threads.com", "www.threads.com"}:
            share = re.fullmatch(r"/share/([A-Za-z0-9_-]+)", path)
            if share:
                return "threads", f"share:{share[1]}", f"https://www.threads.com/share/{share[1]}/"
            match = re.fullmatch(r"/@[A-Za-z0-9_.]+/post/([A-Za-z0-9_-]+)", path)
            if not match:
                raise ValueError()
            content_id, platform = match[1], "threads"
        else:
            raise ValueError()
        if platform == "youtube" and not re.fullmatch(r"[A-Za-z0-9_-]{11}", content_id):
            raise ValueError()
        canonical = f"https://www.youtube.com/watch?v={content_id}" if platform == "youtube" else f"https://www.instagram.com/p/{content_id}/" if platform == "instagram" else f"https://www.threads.com{path}"
        return platform, content_id, canonical
    except (ValueError, IndexError):
        raise ValueError("請提供有效的 YouTube 影片、Instagram 貼文／Reel 或 Threads 貼文 HTTPS 連結。") from None
