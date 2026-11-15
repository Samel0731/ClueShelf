import json
from unittest.mock import patch

import pytest

from clueshelf.extraction import Comment, PublicResponse, extract, fetch_public, parse_public_html, rank_comments, validate_destination


def test_youtube_full_description_from_player_data():
    data = {"videoDetails": {"title": "京都のラーメン", "shortDescription": "作者完整說明\n含第二行"}}
    html = '<script>var ytInitialPlayerResponse = ' + json.dumps(data) + ';</script>'
    result = parse_public_html("youtube", html, "https://www.youtube.com/watch?v=hHBnlKxEAxo")
    assert result.original_title == "京都のラーメン"
    assert result.author_text == "作者完整說明\n含第二行"
    assert result.comments == [] and result.status == "complete"


def test_instagram_caption_does_not_collect_comments():
    data = {"post": {"code": "De6RyzOBGKB", "caption": {"text": "作者食譜"}}, "comments": [{"text": "其他人的留言"}]}
    result = parse_public_html("instagram", '<script type="application/json">' + json.dumps(data) + '</script>', "https://www.instagram.com/reel/De6RyzOBGKB/")
    assert result.author_text == "作者食譜"
    assert result.comments == []


def test_threads_only_rooted_replies_ranked():
    data = {"root": {"code": "ROOT", "pk": "123", "caption": {"text": "作者正文"}}, "posts": [
        {"code": "a", "pk": "a", "reply_to_id": "123", "caption": {"text": "熱門留言"}, "like_count": 15},
        {"code": "b", "pk": "b", "reply_to_id": "123", "caption": {"text": "另一留言"}, "like_count": 2},
        {"code": "c", "pk": "c", "reply_to_id": "a", "caption": {"text": "巢狀回覆"}, "like_count": 99},
        {"code": "d", "pk": "d", "caption": {"text": "推薦貼文"}, "like_count": 999},
    ]}
    result = parse_public_html("threads", '<script type="application/json">' + json.dumps(data) + '</script>', "https://www.threads.com/@test/post/ROOT")
    assert result.author_text == "作者正文"
    assert [c.text for c in result.comments] == ["熱門留言", "另一留言"]
    assert result.comments_ranking == "likes" and result.fetched_count == 2


def test_missing_likes_are_not_called_popular():
    selected, ranking, count = rank_comments([Comment(source_id=str(i), text=f"reply{i}") for i in range(15)])
    assert len(selected) == 10 and ranking == "visible" and count == 15


def test_top_ten_in_bounded_sample():
    selected, ranking, count = rank_comments([Comment(source_id=str(i), text=f"reply{i}", likes=i) for i in range(70)])
    assert count == 50 and selected[0].likes == 49 and len(selected) == 10 and ranking == "likes"


def test_login_shell_is_not_author_text():
    result = parse_public_html("instagram", '<meta property="og:description" content="Log in to Instagram">', "https://www.instagram.com/p/X/")
    assert not result.author_text and result.status == "blocked"


def test_preview_marked_partial():
    result = parse_public_html("instagram", '<meta property="og:description" content="作者公開預覽…">', "https://www.instagram.com/p/X/")
    assert result.status == "partial" and "預覽" in result.reason


@pytest.mark.parametrize("url", ["http://www.instagram.com/p/x", "https://www.instagram.com.evil.test/p/x", "https://127.0.0.1/x", "https://user:pass@instagram.com/p/x", "https://instagram.com:123/p/x"])
def test_network_allowlist(url):
    with pytest.raises(ValueError):
        validate_destination(url, "instagram", resolve=False)


def test_private_dns_rejected():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
        with pytest.raises(ValueError):
            validate_destination("https://www.instagram.com/p/x", "instagram")


def test_browser_failure_preserves_public_preview():
    html = b'<meta property="og:description" content="public preview">'
    response = PublicResponse("https://www.threads.com/@test/post/ROOT", 200, "text/html", html)
    with patch("clueshelf.extraction.validate_destination"), patch("clueshelf.extraction.fetch_public", return_value=response), patch("clueshelf.extraction.render_public", side_effect=RuntimeError("browser unavailable")):
        result = extract("threads", response.url)
    assert result.author_text == "public preview" and result.status == "partial"
    assert result.canonical_url == response.url and result.comments_ranking == "unavailable"


def test_ig_complete_html_does_not_need_browser():
    html = '<script type="application/json">' + json.dumps({"code": "ABC", "caption": {"text": "完整作者內文"}}) + '</script>'
    response = PublicResponse("https://www.instagram.com/p/ABC/", 200, "text/html", html.encode())
    with patch("clueshelf.extraction.validate_destination"), patch("clueshelf.extraction.fetch_public", return_value=response), patch("clueshelf.extraction.render_public") as browser:
        result = extract("instagram", response.url)
    assert result.status == "complete" and result.author_text == "完整作者內文"
    browser.assert_not_called()


def test_threads_direct_reply_tree_excludes_continuations_and_related_posts():
    first = {"pk": "first", "caption": {"text": "頂層留言"}, "like_count": 5, "text_post_app_info": {"reply_level": 1}}
    continuation = {"pk": "next", "caption": {"text": "巢狀對話"}, "like_count": 99}
    root = {"code": "ROOT", "pk": "root", "caption": {"text": "正文"}, "text_post_app_info": {"direct_replies": {"edges": [{"node": {"posts": {"edges": [{"node": first}, {"node": continuation}]}}}]}}}
    data = {"media": root, "relatedPosts": [{"code": "other", "caption": {"text": "推薦內容"}, "like_count": 999}]}
    result = parse_public_html("threads", '<script type="application/json">' + json.dumps(data) + '</script>', "https://www.threads.com/@test/post/ROOT")
    assert [c.text for c in result.comments] == ["頂層留言"]
    assert result.fetched_count == 1 and result.comments_ranking == "likes"


def test_threads_prefers_full_root_over_earlier_preview_duplicate():
    preview = {"code": "ROOT", "pk": "root", "caption": {"text": "正文"}}
    reply = {"pk": "reply", "caption": {"text": "真實回覆結構"}, "like_count": 7}
    full = {**preview, "text_post_app_info": {"direct_replies": {"edges": [{"node": {"posts": {"edges": [{"node": reply}]}}}]}}}
    html = '<script type="application/json">' + json.dumps({"preview": preview, "full": full}) + '</script>'
    result = parse_public_html("threads", html, "https://www.threads.com/@test/post/ROOT")
    assert [c.source_id for c in result.comments] == ["reply"]


def test_threads_downward_query_joins_composite_media_id_without_caption():
    root = {"code": "ROOT", "pk": "4016555875691010960", "caption": {"text": "正文"}}
    reply = {"pk": "reply", "caption": {"text": "熱門留言"}, "like_count": 203}
    downward = {"id": "4016555875691010960_72136562558", "text_post_app_info": {"direct_replies": {"edges": [{"node": {"posts": {"edges": [{"node": reply}]}}}]}}}
    html = '<script type="application/json">' + json.dumps({"root": root, "__bbox": {"result": {"data": {"media": downward}}}}) + '</script>'
    result = parse_public_html("threads", html, "https://www.threads.com/@test/post/ROOT")
    assert [c.likes for c in result.comments] == [203]


def test_forwarded_browser_headers_replace_defaults_without_duplicate_case():
    from urllib.parse import urlsplit
    from unittest.mock import MagicMock
    response = MagicMock()
    response.status = 200
    response.getheader.side_effect = lambda key, default=None: {"Content-Length": "0", "Content-Type": "text/html"}.get(key, default)
    response.getheaders.return_value = [("Set-Cookie", "guest=x; Secure")]
    response.read.return_value = b""
    connection = MagicMock()
    connection.getresponse.return_value = response
    with patch("clueshelf.extraction.validate_destination", return_value=(urlsplit("https://www.threads.com/post"), "1.1.1.1")), patch("clueshelf.extraction.PinnedHTTPS", return_value=connection):
        result = fetch_public("https://www.threads.com/post", "threads", headers={"User-Agent": "browser", "accept": "html"})
    headers = connection.request.call_args.kwargs["headers"]
    assert headers["user-agent"] == "browser" and "User-Agent" not in headers
    assert result.cookies == ["guest=x; Secure"]
