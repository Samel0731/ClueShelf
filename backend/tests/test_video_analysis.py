import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import update

from test_foundation import add, system
from test_search_api import app as searchable_app
from clueshelf.models import VideoAnalysis
from clueshelf.video_analysis import InvalidModelResponse
from clueshelf.video_models import Candidate, VideoProgress
from clueshelf.video_sources import PublicText, Segment, VideoSourceError, collect_public_text, transcribe_audio
from clueshelf.video_worker import claim, finish, run_once


def test_new_youtube_save_queues_public_text_once(system):
    client, _ = system
    item = add(client)
    assert item["video_analysis"]["state"] == "queued"
    assert item["video_analysis"]["mode"] == "text"
    duplicate = client.post("/api/v1/saves", json={"url": item["url"]})
    assert duplicate.status_code == 200
    assert duplicate.json()["save"]["id"] == item["id"]
    response = client.post(f"/api/v1/saves/{item['id']}/video-analysis", json={"mode": "text"})
    assert response.status_code == 202
    assert response.json()["video_analysis"]["state"] == "queued"


def test_video_results_use_evidence_and_are_searchable(searchable_app, monkeypatch):
    client, factory = searchable_app
    item = add(client)
    path = f"/api/v1/saves/{item['id']}"
    public = PublicText(duration=13_056, segments=[
        Segment("chapter", "演唱：夜に駆ける", 80),
        Segment("chapter", "演唱：夜に駆ける", 12_800),
        Segment("description", "本日歌單：群青"),
        Segment("description", "オリジナル曲『きにぴ』がデジタルリリースしております"),
        Segment("comment", "觀眾歌單 6:10 ロキ", 370),
        Segment("comment", "我想聊聯發科 2454"),
        Segment("caption", "台積電 2330 的先進製程需求增長", 595, 600),
        Segment("caption", "台積電今年的資本支出增加", 1190, 1197),
    ])
    monkeypatch.setattr("clueshelf.video_worker.collect_public_text", lambda *_: public)

    def candidates(batch, title):
        names = {"chapter": ["夜に駆ける"], "description": ["群青", "きにぴ"], "comment": ["ロキ", "聯發科"], "caption": ["台積電"]}
        for index, segment in enumerate(batch):
            for name in names[segment.source]:
                if name in segment.text:
                    yield Candidate(kind="stock" if name in {"台積電", "聯發科"} else "song", name=name,
                                    ticker="2454" if name == "聯發科" else "2330" if name == "台積電" else None,
                                    segment=index, quote=segment.text)
        yield Candidate(kind="stock", name="輝達", ticker="NVDA", segment=0, quote="不存在的證據")

    monkeypatch.setattr("clueshelf.video_analysis.extract_candidates", candidates)
    monkeypatch.setattr("clueshelf.video_worker.transcribe_audio", lambda *_: (_ for _ in ()).throw(AssertionError("text job downloaded audio")))
    assert run_once(factory)
    result = client.get(path).json()["video_analysis"]["result"]
    findings = result["findings"]
    assert {entry["name"] for entry in findings} == {"夜に駆ける", "群青", "ロキ", "台積電", "聯發科"}
    assert [entry["evidence"][0]["start_seconds"] for entry in findings if entry["name"] == "夜に駆ける"] == [80, 12_800]
    assert next(entry for entry in findings if entry["name"] == "群青")["evidence"][0]["start_seconds"] is None
    stock = next(entry for entry in findings if entry["name"] == "台積電")
    assert stock["ticker"] == "2330"
    assert [evidence["start_seconds"] for evidence in stock["evidence"]] == [595, 1190]
    assert next(entry for entry in findings if entry["name"] == "聯發科")["evidence"][0]["source"] == "comment"
    assert next(row for row in result["coverage"] if row["source"] == "caption")["through_seconds"] == 1197
    for query, field in [("夜に駆ける", "video_song"), ("2330", "video_stock")]:
        hits = client.get("/api/v1/search", params={"q": query}).json()["results"]
        assert [(hit["save"]["id"], hit["match_field"]) for hit in hits] == [(item["id"], field)]

    assert client.post(path + "/video-analysis", json={"mode": "transcribe"}).status_code == 422
    assert client.post(path + "/video-analysis", json={"mode": "transcribe", "audio_authorized": True}).status_code == 202

    def missing_model(*_, report, **__):
        before = client.get(path).json()["video_analysis"]
        assert before["progress"] == {"stage": "preparing", "percent": None}
        report(VideoProgress(stage="transcribing", percent=34))
        during = client.get(path).json()["video_analysis"]
        assert during["state"] == "running"
        assert during["progress"] == {"stage": "transcribing", "percent": 34}
        raise VideoSourceError("尚未安裝本機 Whisper 模型")

    monkeypatch.setattr("clueshelf.video_worker.transcribe_audio", missing_model)
    assert run_once(factory)
    failed = client.get(path).json()["video_analysis"]
    assert failed["state"] == "failed"
    assert failed["progress"] is None
    assert "Whisper" in failed["error"]
    assert failed["result"] == result


def test_video_worker_recovers_expired_job_and_discards_stale_writes(system, monkeypatch, tmp_path):
    client, factory = system
    item = add(client)
    path = f"/api/v1/saves/{item['id']}"
    stale = claim(factory)
    scratch = tmp_path / "scratch"
    old_audio = scratch / f"{stale.token}_old"
    old_audio.mkdir(parents=True)
    (old_audio / "audio").write_bytes(b"interrupted download")
    with factory.begin() as session:
        session.execute(update(VideoAnalysis).values(lease_until=time.time() - 1))

    def rate_limited(*_):
        raise VideoSourceError("YouTube 暫時限制讀取", retryable=True)

    monkeypatch.setattr("clueshelf.video_worker.collect_public_text", rate_limited)
    assert run_once(factory, scratch=scratch)
    assert not old_audio.exists()
    finish(factory, stale, error="stale write")
    queued = client.get(path).json()["video_analysis"]
    assert queued["state"] == "queued" and "限制" in queued["error"]
    assert not run_once(factory)
    assert client.delete(path, params={"version": item["version"]}).status_code == 204
    assert not run_once(factory)
    assert client.get(path).status_code == 404


def test_transcription_cleans_up_download_on_model_failure(monkeypatch, tmp_path):
    model = tmp_path / "model.bin"
    model.touch()
    monkeypatch.setattr("clueshelf.video_sources.MODEL_DIR", tmp_path)
    saved_paths = []

    def download(_, options, **kwargs):
        path = Path(options[options.index("--output") + 1])
        path.write_bytes(b"fixture audio")
        saved_paths.append(path)

    def model_failure(command, timeout, active, *, tick):
        assert Path(command[-2]).read_bytes() == b"fixture audio"
        Path(command[-1]).write_text("34\n", encoding="ascii")
        tick()
        tick()
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr("clueshelf.video_sources.run_yt_dlp", download)
    monkeypatch.setattr("clueshelf.video_sources.run_media_command", model_failure)
    updates = []
    with pytest.raises(VideoSourceError, match="Whisper"):
        transcribe_audio("https://www.youtube.com/watch?v=abcdefghijk", PublicText(100, "not_live"), report=updates.append)
    assert [(update.stage, update.percent) for update in updates] == [
        ("downloading", None), ("transcribing", None), ("transcribing", 34),
    ]
    assert saved_paths and not saved_paths[0].parent.exists()


def test_unavailable_comments_keep_manual_original_language_captions(monkeypatch):
    def metadata(_, *options):
        if "--write-comments" in options:
            raise VideoSourceError("留言受限")
        return {
            "title": "歌枠", "language": "ja", "description": "2:40 歌單",
            "duration": 400, "live_status": "was_live",
            "subtitles": {"en": [{"ext": "json3", "url": "translated"}], "ja": [{"ext": "json3", "url": "manual"}]},
            "automatic_captions": {"ja-orig": [{"ext": "json3", "url": "auto"}]},
        }

    def captions(url):
        assert url == "manual"
        return [Segment("caption", "群青を歌います", 160, 163)]

    monkeypatch.setattr("clueshelf.video_sources.metadata", metadata)
    monkeypatch.setattr("clueshelf.video_sources.read_captions", captions)
    result = collect_public_text("https://www.youtube.com/watch?v=abcdefghijk")
    assert result.warnings == ["留言未取得。留言受限"]
    assert [(entry.source, entry.start) for entry in result.segments] == [("description", 160), ("caption", 160)]


def test_bad_model_batch_does_not_discard_later_captions(system, monkeypatch):
    client, factory = system
    item = add(client)
    public = PublicText(duration=3000, segments=[
        Segment("caption", "無法解析的段落", 1, 3),
        Segment("caption", "今天討論微軟 MSFT 的雲端業務", 2980, 2985),
        Segment("caption", "忘れられないあの夜", 2987, 2990),
        Segment("caption", "群青を歌います", 2992, 2994),
    ])
    monkeypatch.setattr("clueshelf.video_worker.collect_public_text", lambda *_: public)

    def candidates(batch, title):
        if batch[0].start == 1:
            raise InvalidModelResponse("fixture")
        names = {"今天討論微軟 MSFT 的雲端業務": "微軟", "忘れられないあの夜": "あの夜", "群青を歌います": "群青"}
        return [
            Candidate(kind="stock" if "MSFT" in segment.text else "song", name=names[segment.text],
                      ticker="MSFT" if "MSFT" in segment.text else None, segment=index, quote=segment.text)
            for index, segment in enumerate(batch)
        ]

    monkeypatch.setattr("clueshelf.video_analysis.extract_candidates", candidates)
    assert run_once(factory)
    result = client.get(f"/api/v1/saves/{item['id']}").json()["video_analysis"]["result"]
    assert [(finding["name"], finding["ticker"]) for finding in result["findings"]] == [("微軟", "MSFT"), ("群青", None)]
    assert result["coverage"] == [{"source": "caption", "segments": 3, "through_seconds": 2994}]
    assert "1 段文字未完成解析" in result["warnings"][0]
