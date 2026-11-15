"use client";

import { useCallback, useEffect, useState } from "react";
import { errorMessage, reindexSearch, searchFacets, type Facets } from "../../lib/api";
import YouTubeAccount from "../youtube-account";

export default function SettingsPage() {
  const [index, setIndex] = useState<Facets["index"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const refresh = useCallback(async () => {
    try {
      setIndex((await searchFacets()).index);
      setError("");
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const pending = Boolean(index?.pending);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [pending, refresh]);

  async function rebuild() {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await reindexSearch();
      setMessage(`已排入 ${result.queued} 筆搜尋資料更新。`);
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return <>
    <header className="workspace-heading">
      <p className="workspace-kicker">管理你的空間</p>
      <h1>設定</h1>
      <p>連結 YouTube 帳號，查看同步與搜尋狀態。</p>
    </header>
    <section className="workspace-settings-section" aria-labelledby="account-heading">
      <h2 id="account-heading">帳號與同步</h2>
      <YouTubeAccount onCollectionChanged={refresh}/>
    </section>
    <section className="workspace-settings-section workspace-panel" aria-labelledby="index-heading">
      <h2 id="index-heading">搜尋維護</h2>
      {index ? <>
        <p>{index.model_ready ? "語意搜尋模型已就緒。" : "語意搜尋模型尚未就緒，可使用關鍵字搜尋。"}</p>
        <dl className="index-stats">
          <div><dt>已建立索引</dt><dd>{index.ready}</dd></div>
          <div><dt>等待處理</dt><dd>{index.pending}</dd></div>
          <div><dt>未完成</dt><dd>{index.failed}</dd></div>
        </dl>
      </> : !error && <p role="status">正在讀取索引狀態…</p>}
      {error && <div className="notice error" role="alert">{error} <button type="button" className="text-button" onClick={() => void refresh()}>重試</button></div>}
      {message && <p role="status" className="notice success">{message}</p>}
      <button className="secondary" type="button" disabled={busy} onClick={() => void rebuild()}>
        {busy ? "安排更新中…" : "重新建立搜尋資料"}
      </button>
    </section>
  </>;
}
