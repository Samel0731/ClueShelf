"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, editClassification, errorMessage, type Save } from "../lib/api";
import { type Catalog } from "../lib/taxonomy";

export default function ClassificationEditor({save, catalog, disabled, onChanged, onRefresh}: {save: Save; catalog: Catalog | null; disabled: boolean; onChanged: (save: Save) => void; onRefresh: () => Promise<void>}) {
  const [topics, setTopics] = useState(save.effective_topics);
  const [tags, setTags] = useState(save.effective_tags.join("、"));
  const [version, setVersion] = useState(save.version);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const dirtyRef = useRef(false);
  useEffect(() => {
    if (!dirtyRef.current) {setTopics(save.effective_topics); setTags(save.effective_tags.join("、")); setVersion(save.version);}
  }, [save]);
  const conflicted = version !== save.version;
  const availableTopics = Array.from(new Set([...(catalog?.items.filter(item => item.kind === "topic" && !item.merged_into && (!item.archived || topics.includes(item.name))).map(item => item.name) || []), ...topics]));
  function markDirty() { dirtyRef.current = true; setDirty(true); setMessage(""); }
  async function apply(input: {topics?: string[] | null; tags?: string[] | null}) {
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await editClassification(save.id, {version, ...input});
      dirtyRef.current = false; setDirty(false); setTopics(result.effective_topics); setTags(result.effective_tags.join("、")); setVersion(result.version); onChanged(result); setMessage("分類已保存。");
    } catch (e) {setError(errorMessage(e)); if (e instanceof ApiError && e.status === 409) await onRefresh();}
    finally {setBusy(false);}
  }
  return <section className="classification-editor" aria-labelledby="classification-heading">
    <div className="section-heading"><h3 id="classification-heading">主題與標籤</h3><span>{save.manual_topics !== null || save.manual_tags !== null ? "含人工修正" : "AI 分類"}</span></div>
    <fieldset disabled={disabled || busy}><legend>主題，可複選</legend><div className="topic-options">{availableTopics.map(topic => <label key={topic}><input type="checkbox" checked={topics.includes(topic)} onChange={() => {markDirty(); setTopics(current => current.includes(topic) ? current.filter(value => value !== topic) : [...current, topic]);}}/>{topic}</label>)}</div>
      <label htmlFor="classification-tags">標籤</label><textarea id="classification-tags" rows={2} maxLength={3000} value={tags} onChange={e => {markDirty(); setTags(e.target.value);}} placeholder="用頓號、逗號或換行分開，例如：日文、歌回、現場演唱"/>
      <p className="field-note">AI 重新整理後仍會採用人工分類。可到<Link href="/categories">分類管理</Link>建立新主題。</p>
      {conflicted && <div className="notice warning">內容已有更新，你的分類草稿仍保留。<button type="button" className="text-button" onClick={() => {dirtyRef.current = false; setDirty(false); setTopics(save.effective_topics); setTags(save.effective_tags.join("、")); setVersion(save.version); setError("");}}>載入最新分類（捨棄草稿）</button></div>}
      {error && <p className="notice error" role="alert">{error}</p>}{message && <p className="success-message" role="status">{message}</p>}
      <div className="edit-actions"><button type="button" className="primary" disabled={!dirty || conflicted} onClick={() => void apply({topics, tags: Array.from(new Set(tags.split(/[,，、\n]/).map(tag => tag.trim()).filter(Boolean)))})}>保存分類</button><button type="button" className="text-button" disabled={conflicted || dirty || save.manual_topics === null && save.manual_tags === null} onClick={() => void apply({topics: null, tags: null})}>恢復使用 AI 分類</button></div>
    </fieldset>
  </section>;
}
