"use client";

import { useState } from "react";
import type { Save, VideoMode, VideoSource } from "../lib/api";

const sources: Record<VideoSource, string> = {
  description: "影片說明",
  chapter: "影片章節",
  comment: "觀眾提供",
  caption: "影片字幕",
  transcript: "本機轉錄",
};

const transcriptionStages = {
  preparing: "正在讀取影片資料",
  downloading: "正在下載音訊",
  transcribing: "正在本機轉錄音訊",
  analyzing: "正在整理轉錄結果",
};

function timeLabel(seconds: number) {
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = String(total % 60).padStart(2, "0");
  return minutes >= 60 ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${remainder}` : `${minutes}:${remainder}`;
}

export default function VideoPanel({ save, disabled, start }: {
  save: Save;
  disabled: boolean;
  start: (mode: VideoMode, audioAuthorized: boolean) => void;
}) {
  const [audioAuthorized, setAudioAuthorized] = useState(false);
  const analysis = save.video_analysis;
  const pending = analysis?.state === "queued" || analysis?.state === "running";
  const transcriptionPending = analysis?.mode === "transcribe" && pending;
  const transcriptionDone = analysis?.mode === "transcribe" && analysis.state === "done";
  const progress = analysis?.progress;
  const percent = transcriptionDone ? 100 : progress?.percent ?? undefined;
  const stageLabel = transcriptionDone ? "本機轉錄完成" : analysis?.state === "queued"
    ? "等待本機轉錄" : progress ? transcriptionStages[progress.stage] : "正在準備本機轉錄";
  const result = analysis?.result;
  const findings = result?.findings ?? [];
  const groups = [
    { title: "影片中的歌曲", items: findings.filter(item => item.kind === "song" && item.evidence.some(evidence => evidence.source !== "comment")) },
    { title: "影片提到的股票", items: findings.filter(item => item.kind === "stock" && item.evidence.some(evidence => evidence.source !== "comment")) },
    { title: "觀眾提供的歌單與股票", items: findings.filter(item => item.evidence.every(evidence => evidence.source === "comment")) },
  ];

  return <details className="content-panel video-panel" open>
    <summary>影片解析 <span>本機 AI</span></summary>
    <p aria-live="polite" className="source-meta">
      {transcriptionPending ? null : analysis?.state === "queued" ? "影片解析已排入佇列。" :
        analysis?.state === "running" ? "正在讀取公開文字並整理。" :
        analysis?.state === "failed" ? "這次解析未完成。" :
        result ? (result.mode === "transcribe" ? "公開文字與本機轉錄結果" : "公開文字解析結果") : "尚未解析這支影片。"}
      {result && (pending || analysis?.state === "failed") && " 下方保留上次解析結果。"}
    </p>
    {(transcriptionPending || transcriptionDone) && <div className="video-progress">
      <div className="video-progress-label">
        <span aria-live="polite">{stageLabel}</span>
        {percent !== undefined && <span>{percent}%</span>}
      </div>
      <progress aria-label={stageLabel} max={100} value={percent} />
    </div>}
    {analysis?.error && <p className="notice warning">{analysis.error}</p>}
    {result?.warnings.map(warning => <p className="field-note" key={warning}>{warning}</p>)}
    {!!result?.coverage.length && <p className="field-note">已處理 {result.coverage.map(item =>
      `${sources[item.source]} ${item.segments} 段${item.through_seconds === null ? "" : `，最晚 ${timeLabel(item.through_seconds)}`}`).join("；")}。</p>}
    {result && !findings.length && <p className="panel-empty">已取得的資料中沒有可核對的歌名或股票。</p>}
    {groups.filter(group => group.items.length).map(group => <section key={group.title}>
      <h3>{group.title}</h3>
      <ul className="reply-list">{group.items.map((item, index) => <li key={`${item.name}-${index}`}>
        <strong>{item.name}{item.ticker && item.ticker !== item.name ? `（${item.ticker}）` : ""}</strong>
        {item.evidence.map((evidence, evidenceIndex) => <div key={evidenceIndex}>
          <p className="original-text">{evidence.quote}</p>
          <div className="reply-meta">
            <span>{sources[evidence.source]}</span>
            {evidence.start_seconds !== null && <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(save.content_id)}&t=${Math.floor(evidence.start_seconds)}s`}
              target="_blank" rel="noopener noreferrer">{timeLabel(evidence.start_seconds)} ↗</a>}
          </div>
        </div>)}
      </li>)}</ul>
    </section>)}
    <div className="process-actions">
      <button type="button" className="secondary" disabled={disabled || pending} onClick={() => start("text", false)}>
        {result ? "重新解析公開文字" : "解析影片"}
      </button>
    </div>
    <details>
      <summary>本機轉錄音訊</summary>
      <p className="field-note">支援四小時內的已結束影片。首次使用需安裝 Whisper 模型。暫存音訊用於本機轉錄，工作結束後清除。</p>
      <label><input type="checkbox" checked={audioAuthorized} disabled={disabled || pending}
        onChange={event => setAudioAuthorized(event.target.checked)} /> 我已獲准下載這支影片的音訊</label>
      <div className="process-actions"><button type="button" className="secondary" disabled={disabled || pending || !audioAuthorized}
        onClick={() => start("transcribe", audioAuthorized)}>本機轉錄音訊</button></div>
    </details>
  </details>;
}
