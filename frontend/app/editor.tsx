"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, deleteSave, editSave, errorMessage, processSave, requestVideoAnalysis, switchTitle, type Save } from "../lib/api";
import ClassificationEditor from "./classification-editor";
import VideoPanel from "./video-panel";
import { type Catalog } from "../lib/taxonomy";
export type DetailView = "content" | "video" | "edit";

const bodyLabels = { youtube: "影片說明", instagram: "作者貼文說明", threads: "作者正文" };
const platformNames = { youtube: "YouTube", instagram: "Instagram", threads: "Threads" };
const extractionLabels = { idle: "尚未讀取", queued: "等候讀取", processing: "讀取中", complete: "原文已取得", partial: "僅取得部分內容", blocked: "平台限制讀取", failed: "讀取失敗" };
const aiLabels = { idle: "尚未整理", queued: "等候 AI", processing: "AI 整理中", complete: "AI 整理完成", unavailable: "本地模型未就緒", failed: "AI 整理失敗" };

function draftFor(save: Save) {
  return { title: save.title, author_text: save.author_text, manual_comments: save.manual_comments, version: save.version };
}

export function SaveStatus({ save }: { save: Pick<Save, "duplicate_of" | "ai_status" | "extraction_status" | "status"> }) {
  if (save.duplicate_of) return <span className="status needs">重複收藏</span>;
  const text = save.ai_status !== "idle" ? aiLabels[save.ai_status] : save.extraction_status !== "idle" ? extractionLabels[save.extraction_status] : save.status === "needs_text" ? "待補內文" : save.status === "queued" || save.status === "processing" ? "準備中" : "已保存";
  const pending = [save.extraction_status, save.ai_status].some((value) => value === "queued" || value === "processing");
  return <span className={`status ${pending ? "pending" : save.ai_status === "complete" ? "ready" : "needs"}`}><span/>{text}</span>;
}

export default function Editor({ save, catalog, view, onView, onChanged, onDeleted, onRefresh, onOpen }: {
  save: Save; catalog: Catalog | null; view: DetailView; onView: (view: DetailView) => void;
  onChanged: (save: Save) => void; onDeleted: () => void; onRefresh: () => Promise<void>; onOpen: (id: string) => void;
}) {
  const [draft, setDraft] = useState(() => draftFor(save));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const lastSave = useRef(save);
  const baseDraft = useRef(draftFor(save));
  const touched = useRef(new Set<"title" | "author_text" | "manual_comments">());
  const localEditing = useRef(false);
  const dirty = localEditing.current;
  const conflicted = draft.version !== save.version;
  const officialYouTube = save.source?.provider === "youtube_api";
  const processing = [save.extraction_status, save.ai_status].some((value) => value === "queued" || value === "processing");

  useEffect(() => {
    if (lastSave.current !== save) {
      if (!localEditing.current) { setDraft(draftFor(save)); baseDraft.current = draftFor(save); touched.current.clear(); }
      lastSave.current = save;
    }
  }, [save]);

  function change(field: "title" | "author_text" | "manual_comments", value: string) {
    if (value === baseDraft.current[field]) touched.current.delete(field);
    else touched.current.add(field);
    localEditing.current = touched.current.size > 0;
    setDraft({ ...draft, [field]: value }); setMessage("");
  }

  async function operate(action: () => Promise<Save>, success: string) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await action();
      localEditing.current = false;
      touched.current.clear(); baseDraft.current = draftFor(result);
      setDraft(draftFor(result)); onChanged(result); setMessage(success);
    } catch (e) {
      setError(errorMessage(e));
      if (e instanceof ApiError && e.status === 409) await onRefresh();
    } finally { setBusy(false); }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await operate(() => editSave(save.id, {
      version: draft.version,
      ...(touched.current.has("title") ? { title: draft.title } : {}),
      ...(touched.current.has("author_text") ? { author_text: draft.author_text } : {}),
      ...(touched.current.has("manual_comments") ? { manual_comments: draft.manual_comments } : {}),
    }), "修改已保存。人工內容會保留。");
  }

  async function remove() {
    setBusy(true); setError("");
    try { await deleteSave(save.id, save.version); onDeleted(); }
    catch (e) { setError(errorMessage(e)); setConfirmDelete(false); if (e instanceof ApiError && e.status === 409) await onRefresh(); }
    finally { setBusy(false); }
  }

  return <section className="detail" aria-labelledby="detail-title">
    <div className="detail-heading"><span className="eyebrow">收藏內容</span><SaveStatus save={save}/></div>
    <h1 id="detail-title">{save.title || "還沒有標題的收藏"}</h1>
    <a className="source-link" href={save.url} target="_blank" rel="noopener noreferrer">在 {platformNames[save.platform]} 開啟原內容 <span aria-hidden="true">↗</span></a>
    <div className="processing-summary" aria-live="polite"><span>{extractionLabels[save.extraction_status]}</span><span>{aiLabels[save.ai_status]}</span></div>
    <nav className="workspace-tabs" aria-label="收藏詳情檢視">
      <button type="button" aria-pressed={view === "content"} onClick={() => onView("content")}>內容</button>
      {save.platform === "youtube" && !save.duplicate_of && <button type="button" aria-pressed={view === "video"} onClick={() => onView("video")}>影片解析</button>}
      <button type="button" aria-pressed={view === "edit"} onClick={() => onView("edit")}>編輯{dirty ? " · 未儲存" : ""}</button>
    </nav>
    {error && <p className="notice error" role="alert">{error}</p>}
    {message && <p className="success-message" role="status">{message}</p>}
    {save.job?.error && <p className="job-error">{save.job.error}</p>}
    {view === "video" && save.platform === "youtube" && !save.duplicate_of && <VideoPanel save={save} disabled={busy || dirty}
      start={(mode, authorized) => void operate(() => requestVideoAnalysis(save.id, mode, authorized), "影片解析已排入佇列。")} />}
    {view === "content" && <div>
    <div className="process-actions">{!officialYouTube && <button type="button" className="secondary" disabled={busy || processing || localEditing.current || !!save.duplicate_of} onClick={() => void operate(() => processSave(save.id, save.version, "read"), "已排入重新讀取。")}>重新讀取原文</button>}<button type="button" className="secondary" disabled={busy || processing || localEditing.current || !(save.author_text || save.source?.author_text || save.manual_comments || save.source?.original_title || save.source?.comments.length) || !!save.duplicate_of} onClick={() => void operate(() => processSave(save.id, save.version, "analyze"), "已排入本地 AI 整理。")}>重新 AI 整理</button></div>
    {officialYouTube && <p className="field-note">原文來自 YouTube。可到<Link href="/settings">設定</Link>重新同步影片標題與說明。</p>}
    {save.duplicate_of && <div className="notice warning">這個分享連結指向已存在的收藏。你的補充保留在這份草稿，不會覆寫原收藏。<button type="button" className="text-button" onClick={() => { if (save.duplicate_of) onOpen(save.duplicate_of); }}>開啟原收藏</button></div>}
    {save.extraction_error && <p className="notice warning">{save.extraction_error}</p>}
    {save.ai_error && <p className="notice warning">{save.ai_error}</p>}

    <details className="content-panel" open={!save.analysis}>
      <summary>原始內容 <span>平台來源</span></summary>
      {save.source ? <><p className="source-meta">{officialYouTube ? "YouTube API · " : ""}讀取於 {new Date(save.source.fetched_at * 1000).toLocaleString("zh-TW")}</p>{save.source.original_title && <h3>{save.source.original_title}</h3>}<p className="content-label">{bodyLabels[save.platform]}</p><p className="original-text">{save.source.author_text || "沒有取得作者內文，可在下方補充。"}</p>{save.source.reason && <p className="field-note">{save.source.reason}</p>}</> : <p className="panel-empty">尚未取得平台原文。讀取失敗時，可在下方貼上內容。</p>}
    </details>

    {save.platform === "threads" && <details className="content-panel" open>
      <summary>Threads 留言 <span>與作者正文分開</span></summary>
      <p className="source-meta">{save.source?.comments_ranking === "likes" ? `在取得的 ${save.source.fetched_count} 則頂層留言中，按讚排序前 ${save.source.comments.length} 則。不是全篇熱門排名。` : save.source?.comments_ranking === "visible" ? `取得 ${save.source.fetched_count} 則頂層留言，保留前 ${save.source.comments.length} 則可見內容。缺少讚數，無法判定熱門程度。` : "未取得公開留言。你仍可保留正文，或在下方貼上留言補充。"}</p>
      {!!save.source?.comments.length && <ol className="reply-list">{save.source.comments.map((comment) => <li key={comment.source_id}><p className="original-text">{comment.text}</p><div className="reply-meta"><span>{comment.likes === null ? "讚數未知" : `${comment.likes} 個讚`}</span>{comment.url && <a href={comment.url} target="_blank" rel="noopener noreferrer">查看來源 ↗</a>}</div></li>)}</ol>}
    </details>}

    <details className="content-panel ai-panel" open>
      <summary>AI 整理 <span>本地模型</span></summary>
      {save.analysis && save.ai_status !== "complete" && <p className="notice warning">以下為上一次整理結果，尚未根據目前內容更新。</p>}
      {save.analysis?.input_truncated && <p className="field-note">這次 AI 使用內容節錄整理；完整原文與留言仍保留在上方。</p>}
      {save.analysis?.summary_origin === "source" && <p className="field-note">短文直接保留原句，避免 AI 擴寫；標題與分類仍由 AI 整理。</p>}
      {save.analysis ? <><h3>{save.analysis.suggested_title}</h3><p className="original-text">{save.analysis.summary}</p><div className="topic-tags">{save.analysis.topics.map((topic) => <span key={topic}>{topic}</span>)}{save.analysis.tags.map((tag) => <span className="fine-tag" key={`tag-${tag}`}>#{tag}</span>)}</div><p className="source-meta">{save.analysis.model} · {new Date(save.analysis.generated_at * 1000).toLocaleString("zh-TW")}</p>{save.platform === "threads" && <p className="field-note">留言為其他使用者觀點，不代表作者主張或已查證事實。</p>}</> : <p className="panel-empty">{aiLabels[save.ai_status]}。整理結果會顯示在這裡，原文始終保留。</p>}
    </details>

    </div>}
    <div hidden={view !== "edit"}>
    <ClassificationEditor catalog={catalog} save={save} disabled={busy || dirty} onChanged={onChanged} onRefresh={onRefresh}/>
    <form onSubmit={submit} className="manual-editor">
      <div className="section-heading"><h3>你的補充與修正</h3><span>人工內容優先保留</span></div>
      <label htmlFor="edit-title">顯示標題</label>
      <input id="edit-title" maxLength={500} value={draft.title} onChange={(e) => { change("title", e.target.value); }} placeholder="替收藏取個容易找的名字" disabled={busy}/>
      <div className="title-options">{save.source?.original_title && <button type="button" className="text-button" disabled={busy || processing || localEditing.current} onClick={() => void operate(() => switchTitle(save.id, save.version, "original"), "已使用原始標題。")}>使用原始標題</button>}{save.analysis?.suggested_title && <button type="button" className="text-button" disabled={busy || processing || localEditing.current || save.ai_status !== "complete"} onClick={() => void operate(() => switchTitle(save.id, save.version, "ai"), "已使用 AI 標題。")}>使用 AI 標題</button>}</div>
      <div className="label-row"><label htmlFor="edit-text">{bodyLabels[save.platform]}補充／修正</label><span>保留原語言</span></div>
      <textarea id="edit-text" maxLength={50000} rows={6} value={draft.author_text} onChange={(e) => { change("author_text", e.target.value); }} placeholder="自動讀取不到時，貼上作者的原始內容。" disabled={busy}/>
      <p className="field-note">這裡的內容用於整理，平台讀取到的原文另外保留。</p>
      {save.platform === "threads" && <><label htmlFor="edit-comments">手動補充留言（選填）</label><textarea id="edit-comments" maxLength={30000} rows={4} value={draft.manual_comments} onChange={(e) => { change("manual_comments", e.target.value); }} placeholder="貼上你想保留的留言。這些內容標示為手動補充，不列入平台熱門排名。" disabled={busy}/><p className="field-note">請與作者正文分開貼上，AI 會視為留言觀點。</p></>}
      {conflicted && <div className="notice warning">內容已有更新，你的輸入仍保留。請先確認最新版本。<button type="button" className="text-button" onClick={() => { localEditing.current = false; touched.current.clear(); baseDraft.current = draftFor(save); setDraft(draftFor(save)); setError(""); }}>載入最新內容（捨棄目前輸入）</button></div>}
      <div className="edit-actions"><button className="primary" disabled={busy || conflicted || !dirty}>{busy ? "處理中…" : "保存修改"}</button></div>
    </form>
    <div className="detail-footer"><span>收藏於 {new Date(save.created_at * 1000).toLocaleDateString("zh-TW")}</span><button type="button" className="danger-link" disabled={busy} onClick={() => setConfirmDelete(true)}>刪除收藏</button></div>
    {confirmDelete && <div className="delete-confirm" role="alert"><strong>確定刪除這筆收藏？</strong><p>此操作無法復原，原平台的內容不受影響。</p><div><button type="button" className="danger" onClick={remove} disabled={busy}>確定刪除</button><button type="button" className="secondary" onClick={() => setConfirmDelete(false)} disabled={busy}>保留收藏</button></div></div>}
    </div>
  </section>;
}
