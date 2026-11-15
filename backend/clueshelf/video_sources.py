"""Read public YouTube text and optionally transcribe authorized audio."""
import json
import math
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from .extraction import fetch_public
from .links import parse_link
from .video_models import SourceKind, VideoProgress

MAX_AUDIO_SECONDS = 4 * 60 * 60
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MODEL_DIR = DATA_DIR / "models" / "faster-whisper-small"
TIMESTAMP = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?![\d:])")


class VideoSourceError(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Segment:
    source: SourceKind
    text: str
    start: float | None = None
    end: float | None = None


@dataclass
class PublicText:
    duration: float | None = None
    live_status: str | None = None
    segments: list[Segment] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    title: str = ""


def run_media_command(command, timeout, active, *, tick=None):
    if not active():
        raise InterruptedError
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding="utf-8", errors="replace") as process:
        try:
            while active():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command[0], timeout)
                try:
                    stdout, stderr = process.communicate(timeout=min(1, remaining))
                    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    if tick is not None:
                        tick()
            raise InterruptedError
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def run_yt_dlp(url, options, *, timeout=65, active=lambda: True):
    platform, video_id, canonical = parse_link(url)
    if platform != "youtube":
        raise VideoSourceError("只有 YouTube 影片可解析。")
    command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-plugin-dirs",
        "--no-cache-dir", "--no-playlist", "--use-extractors", "youtube", "--encoding", "utf-8",
        "--js-runtimes", "node", "--socket-timeout", "12",
        "--retries", "1", "--extractor-retries", "1", *options, "--", canonical,
    ]
    try:
        result = run_media_command(command, timeout, active)
    except subprocess.TimeoutExpired as error:
        raise VideoSourceError("YouTube 資料讀取逾時。", retryable=True) from error
    if result.returncode != 0:
        output = result.stderr.lower()
        if "no module named yt_dlp" in output:
            raise VideoSourceError("尚未安裝 yt-dlp，請更新 ClueShelf 後端套件。")
        if any(term in output for term in ("429", "rate limit", "timed out", "temporary failure", "unable to download webpage")):
            raise VideoSourceError("YouTube 暫時限制讀取或連線失敗。", retryable=True)
        raise VideoSourceError("YouTube 未提供可讀取的內容，影片可能需要登入或受到限制。")
    return video_id, result.stdout


def metadata(url, *options):
    video_id, raw = run_yt_dlp(url, ["--skip-download", "--dump-single-json", *options])
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("id") != video_id:
            raise ValueError
    except ValueError as error:
        raise VideoSourceError("YouTube 回傳的影片資料格式無法讀取。") from error
    return data


def seconds(value):
    return float(value) if type(value) in {int, float} and math.isfinite(value) and value >= 0 else None


def text_lines(source, text, duration=None):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        matches = list(TIMESTAMP.finditer(line))
        pieces = [line] if len(matches) <= 1 else [
            line[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(line)].strip()
            for index, match in enumerate(matches)
        ]
        for piece in pieces:
            match = TIMESTAMP.search(piece)
            start = None
            if match:
                hour, minute, second = match.groups()
                timestamp = int(hour or 0) * 3600 + int(minute) * 60 + int(second)
                if duration is None or timestamp <= duration:
                    start = float(timestamp)
            yield Segment(source, piece, start)


def caption_tracks(info):
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    original_auto = [key for key in auto if key.endswith("-orig")]
    language = info.get("language")
    if not language and original_auto:
        language = original_auto[0].removesuffix("-orig")
    if not language and len(manual) == 1:
        language = next(iter(manual))
    if language:
        base = language.split("-")[0]
        for tracks in (manual, auto):
            for key in dict.fromkeys([language + "-orig", language, base, *tracks]):
                if key != language and not key.startswith(base + "-") and key != base:
                    continue
                if tracks is auto and key not in original_auto and original_auto:
                    continue
                for track in tracks.get(key, []):
                    if track.get("ext") == "json3" and isinstance(track.get("url"), str):
                        yield track["url"]
                        break


def read_captions(url):
    response = fetch_public(url, "youtube")
    if response.status != 200:
        raise ValueError("字幕來源暫時無法讀取")
    events = json.loads(response.body)["events"]
    segments = []
    for event in events:
        start = seconds(event.get("tStartMs"))
        length = seconds(event.get("dDurationMs"))
        text = " ".join("".join(word.get("utf8", "") for word in event.get("segs", [])).split())
        if start is not None and text:
            end = (start + length) / 1000 if length is not None else None
            segment = Segment("caption", text, start / 1000, end)
            if not segments or segment.text != segments[-1].text or segment.start != segments[-1].start:
                segments.append(segment)
    return segments


def collect_public_text(url, cached_description=""):
    public = PublicText()
    try:
        info = metadata(url, "--ignore-no-formats-error")
    except VideoSourceError as error:
        if not cached_description:
            raise
        public.segments.extend(text_lines("description", cached_description[:50000]))
        public.warnings.append(f"{error} 本次只使用已保存的影片說明。")
        return public
    public.duration = seconds(info.get("duration"))
    public.live_status = info.get("live_status")
    public.title = (info.get("title") or "")[:300]
    public.segments.extend(text_lines("description", (info.get("description") or cached_description)[:50000], public.duration))
    for chapter in (info.get("chapters") or [])[:1000]:
        if title := chapter.get("title"):
            public.segments.append(Segment("chapter", title[:1000], seconds(chapter.get("start_time")), seconds(chapter.get("end_time"))))

    try:
        comment_info = metadata(url, "--ignore-no-formats-error", "--write-comments",
                                "--extractor-args", "youtube:comment_sort=top;max_comments=20,20,0,0,1")
        comments = [entry for entry in (comment_info.get("comments") or []) if entry.get("parent") == "root"][:20]
        for comment in comments:
            public.segments.extend(text_lines("comment", (comment.get("text") or "")[:3000], public.duration))
        if not comments:
            public.warnings.append("未取得可用的頂層留言。")
    except VideoSourceError as error:
        public.warnings.append(f"留言未取得。{error}")

    for track in caption_tracks(info):
        try:
            captions = read_captions(track)
        except (ValueError, OSError, KeyError, TypeError, AttributeError):
            continue
        if captions:
            public.segments.extend(captions)
            break
    else:
        public.warnings.append("未取得可用的原語字幕。")
    return public


def transcribe_audio(url, public, *, active=lambda: True, scratch=None, token=None, report=lambda _: None):
    if public.live_status not in {"not_live", "was_live"} or not public.duration or public.duration > MAX_AUDIO_SECONDS:
        raise VideoSourceError("本機轉錄需要已結束且長度已知的影片，上限為四小時。")
    if not (MODEL_DIR / "model.bin").is_file():
        raise VideoSourceError("尚未安裝本機 Whisper 模型。請依 README 的影片轉錄步驟安裝。")
    if scratch is not None:
        scratch.mkdir(parents=True, exist_ok=True)
    prefix = f"{token}_" if token else "clueshelf-audio-"
    with TemporaryDirectory(prefix=prefix, dir=scratch) as directory:
        target = Path(directory) / "audio"
        progress_path = Path(directory) / "progress"
        report(VideoProgress(stage="downloading"))
        run_yt_dlp(url, [
            "--format", "bestaudio[protocol=https]", "--max-filesize", "512M",
            "--match-filter", "!is_live & !is_upcoming & duration <= 14400",
            "--no-continue", "--no-mtime", "--output", str(target),
        ], timeout=600, active=active)
        if not target.is_file():
            raise VideoSourceError("未取得可用的純音訊，或檔案超過 512 MB。")
        report(VideoProgress(stage="transcribing"))
        last_percent = -1

        def read_progress():
            try:
                contents = progress_path.read_text(encoding="ascii")
            except FileNotFoundError:
                return
            complete = contents[:contents.rfind("\n") + 1].splitlines()
            nonlocal last_percent
            if complete and (percent := int(complete[-1])) > last_percent:
                report(VideoProgress(stage="transcribing", percent=percent))
                last_percent = percent

        try:
            result = run_media_command(
                [sys.executable, "-m", "clueshelf.video_sources", str(target), str(progress_path)],
                90 * 60, active, tick=read_progress,
            )
            result.check_returncode()
            segments = [Segment("transcript", text, start, end) for start, end, text in json.loads(result.stdout)]
        except subprocess.TimeoutExpired as error:
            raise VideoSourceError("本機 Whisper 轉錄逾時。") from error
        except (subprocess.CalledProcessError, ValueError) as error:
            raise VideoSourceError("本機 Whisper 無法讀取音訊，請確認套件和模型已安裝。") from error
    if not segments:
        raise VideoSourceError("本機 Whisper 沒有辨識到可用語音。")
    return segments


def transcribe_file(path, progress_path=None):
    from faster_whisper import WhisperModel

    model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
    segments, info = model.transcribe(path, beam_size=3, vad_filter=True)
    output = []
    last_percent = -1
    for segment in segments:
        if progress_path is not None and info.duration > 0:
            percent = min(99, int(100 * segment.end / info.duration))
            if percent > last_percent:
                with Path(progress_path).open("a", encoding="ascii") as progress_file:
                    progress_file.write(f"{percent}\n")
                last_percent = percent
        if text := segment.text.strip():
            output.append((segment.start, segment.end, text))
    return output


if __name__ == "__main__":
    print(json.dumps(transcribe_file(*sys.argv[1:])))
