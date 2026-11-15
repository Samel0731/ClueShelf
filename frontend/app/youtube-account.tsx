"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../lib/api";
import { cancelYouTubeSync, connectYouTube, disconnectYouTube, syncYouTube, youtubeStatus, type YouTubeStatus, type YouTubeSync } from "../lib/youtube";

const syncLabels = {
  queued: "等待同步",
  running: "正在讀取按讚影片",
  completed: "本次 API 可取得範圍已讀取完成",
  cancelled: "已中止同步，已匯入的收藏保留",
  paused: "同步已暫停",
  failed: "同步未完成",
} satisfies Record<YouTubeSync["state"], string>;

function SyncProgress({sync}: {sync: YouTubeSync}) {
  const counts = [
    {label: "已讀取", value: sync.read_count},
    {label: "新增", value: sync.new_count},
    {label: "已存在", value: sync.existing_count},
    {label: "略過", value: sync.skipped_count},
    {label: "AI 等待", value: sync.ai_waiting},
    {label: "失敗", value: sync.failure_count},
  ];
  return <div className="youtube-progress">
    <p className="youtube-sync-state" role="status">{sync.cancel_requested && (sync.state === "running" || sync.state === "queued") ? "正在中止，會先安全保存目前這批影片。" : syncLabels[sync.state]}</p>
    <dl className="youtube-counts">{counts.map(item => <div key={item.label}><dt>{item.label}</dt><dd>{item.value.toLocaleString("zh-TW")}</dd></div>)}</dl>
    {sync.skipped_count > 0 && <p className="youtube-note">私人、已刪除或 API 無法取得的影片會略過。{Object.entries(sync.skip_reasons).map(([reason, number]) => `${reason === "unavailable" ? "無法取得" : reason} ${number} 筆`).join("、")}。</p>}
    {sync.error && <p className="notice warning" role="status">{sync.error}</p>}
    {sync.state === "completed" && <p className="youtube-note">AI 整理與搜尋資料會接著在背景準備。API 結果不保證涵蓋帳號全部歷史。</p>}
  </div>;
}

export default function YouTubeAccount({onCollectionChanged}: {onCollectionChanged: () => Promise<void>}) {
  const [status, setStatus] = useState<YouTubeStatus | null>(null);
  const [error, setError] = useState("");
  const [callbackError, setCallbackError] = useState("");
  const [message, setMessage] = useState("");
  const [revokePending, setRevokePending] = useState(false);
  const [pending, setPending] = useState<"idle" | "connect" | "sync" | "cancel" | "disconnect">("idle");
  const [awaitingAuthorization, setAwaitingAuthorization] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const requestVersion = useRef(0);
  const lastImport = useRef("");
  const authorizationDeadline = useRef(0);

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const next = await youtubeStatus();
      if (version !== requestVersion.current) return;
      setStatus(next); setError("");
      if (next.connection?.status === "connected") setAwaitingAuthorization(false);
      const importVersion = next.sync ? `${next.sync.id}:${next.sync.updated_at}:${next.sync.ai_waiting}` : "";
      if (lastImport.current && importVersion !== lastImport.current) void onCollectionChanged();
      lastImport.current = importVersion;
    } catch (e) {
      if (version === requestVersion.current) setError(errorMessage(e));
    }
  }, [onCollectionChanged]);

  useEffect(() => {
    const url = new URL(window.location.href);
    const result = url.searchParams.get("youtube");
    if (result) {
      if (result === "connected") setMessage("YouTube 帳號已連結，可以開始同步按讚影片。");
      else if (result === "denied") setMessage("已取消 Google 授權，尚未變更收藏。");
      else if (result === "error") setCallbackError("Google 授權未完成，請重新連結帳號。");
      url.searchParams.delete("youtube");
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    }
    void refresh();
    return () => {requestVersion.current += 1;};
  }, [refresh]);

  const activeSync = status?.sync?.state === "queued" || status?.sync?.state === "running";
  const waitingAI = !!status?.sync?.ai_waiting;
  useEffect(() => {
    if (!activeSync && !waitingAI && !awaitingAuthorization) return;
    const timer = window.setInterval(() => {
      if (awaitingAuthorization && Date.now() >= authorizationDeadline.current) {
        setAwaitingAuthorization(false);
        setMessage("授權等待已結束；尚未完成時，可再按一次連結帳號。");
      }
      void refresh();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeSync, waitingAI, awaitingAuthorization, refresh]);

  async function connect() {
    setPending("connect"); setError(""); setCallbackError(""); setMessage(""); setRevokePending(false);
    try {
      await connectYouTube();
      authorizationDeadline.current = Date.now() + 10 * 60 * 1000;
      setAwaitingAuthorization(true);
      setMessage("已開啟系統瀏覽器，請在 Google 完成唯讀授權，再回來同步。");
    } catch (e) {setError(errorMessage(e));}
    finally {setPending("idle");}
  }

  async function sync() {
    setPending("sync"); setError(""); setMessage("");
    try {
      const next = await syncYouTube();
      setStatus(current => current ? {...current, sync: next} : current);
      await refresh();
    } catch (e) {setError(errorMessage(e));}
    finally {setPending("idle");}
  }

  async function cancel() {
    setPending("cancel"); setError("");
    try {
      const next = await cancelYouTubeSync();
      setStatus(current => current ? {...current, sync: next} : current);
      setMessage("已送出中止要求，正在處理的批次會先安全保存。");
    } catch (e) {setError(errorMessage(e));}
    finally {setPending("idle");}
  }

  async function disconnect() {
    setPending("disconnect"); setError(""); setMessage("");
    try {
      const result = await disconnectYouTube();
      setConfirmDisconnect(false); setAwaitingAuthorization(false);
      setRevokePending(result.revoke_pending);
      await refresh();
      setMessage(result.revoke_pending ? "本機連結已解除，收藏保留。Google 授權撤銷尚未完成，請至 Google 帳戶確認。" : "已解除 YouTube 連結，匯入的收藏會保留。");
    } catch (e) {setError(errorMessage(e));}
    finally {setPending("idle");}
  }

  const linked = status?.connection?.status === "connected";
  const needsAuthorization = status?.connection?.status === "reauthorize";
  const disabled = pending !== "idle";

  return <section className="youtube-account" aria-labelledby="youtube-account-title">
    <div className="youtube-account-heading"><div><h2 id="youtube-account-title"><span className="platform-icon youtube" aria-hidden="true">▶</span>YouTube 帳號連結</h2><p>匯入按讚影片的標題、說明與連結，交給本地 AI 整理。</p></div><button type="button" className="text-button" disabled={disabled} onClick={() => void refresh()} aria-label="更新 YouTube 連線狀態">更新狀態</button></div>
    {!status && !error && <p className="youtube-note" role="status">正在確認連線狀態…</p>}
    {status && <>
      {status.connection && status.connection.status !== "disconnected" && <div className="youtube-channel"><strong>{status.connection.channel_title}</strong><span className={`status ${linked ? "ready" : "needs"}`}>{linked ? "已連結 · 唯讀" : "需要重新授權"}</span></div>}
      {!status.configured && <details className="youtube-setup"><summary>尚未完成 Google 帳號連結設定</summary><p>{status.configuration_error || "需先完成 Google Cloud 設定，才能連結本人的 YouTube 帳號。"}</p><ol><li>在 <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer">Google Cloud</a> 啟用 YouTube Data API v3。</li><li>設定同意畫面與測試使用者，建立「網頁應用程式」OAuth 用戶端。</li><li>將重新導向網址設為 <code>http://127.0.0.1:8000/api/v1/youtube/oauth/callback</code>。</li><li>依專案的 YouTube 設定說明指定憑證檔，再重新啟動本機服務。</li></ol><p>尚未完成本人帳號的真實同步驗證。</p></details>}
      {needsAuthorization && <p className="youtube-note">授權已失效或遭撤銷。重新連結後，原本的收藏與人工修正都會保留。</p>}
      <div className="youtube-actions">
        {!linked && <button type="button" className="secondary" disabled={disabled || !status.configured || awaitingAuthorization} onClick={() => void connect()}>{pending === "connect" ? "正在開啟 Google…" : awaitingAuthorization ? "等待 Google 授權…" : needsAuthorization ? "重新授權 YouTube" : "連結 YouTube 帳號"}</button>}
        {linked && <button type="button" className="primary" disabled={disabled || activeSync || !status.configured} onClick={() => void sync()}>{pending === "sync" ? "正在安排同步…" : activeSync ? "同步進行中…" : "同步按讚影片"}</button>}
        {activeSync && <button type="button" className="secondary" disabled={disabled || !!status.sync?.cancel_requested} onClick={() => void cancel()}>{pending === "cancel" || status.sync?.cancel_requested ? "正在中止…" : "中止同步"}</button>}
        {linked && <button type="button" className="text-button" disabled={disabled || activeSync} onClick={() => void connect()}>重新授權</button>}
        {status.connection && <button type="button" className="danger-link" disabled={disabled} onClick={() => setConfirmDisconnect(true)}>{status.connection.status === "disconnected" ? "再次清除連結" : "解除連結"}</button>}
      </div>
      {confirmDisconnect && <div className="delete-confirm"><strong>解除 YouTube 帳號連結？</strong><p>會停止同步並撤銷授權，已匯入的收藏與人工修正會保留。</p><div><button type="button" className="danger" disabled={disabled} onClick={() => void disconnect()}>{pending === "disconnect" ? "正在解除…" : "確認解除連結"}</button><button type="button" className="secondary" disabled={disabled} onClick={() => setConfirmDisconnect(false)}>保留連結</button></div></div>}
      {status.connection?.status === "disconnected" && <p className="youtube-note">帳號已解除連結。若先前清除認證時遇到錯誤，可按「再次清除連結」重試。</p>}
      {status.sync && <SyncProgress sync={status.sync}/>}
      {status.connection?.last_complete_scan_at && <p className="youtube-note">上次完整讀取 API 可取得範圍：{new Date(status.connection.last_complete_scan_at * 1000).toLocaleString("zh-TW")}</p>}
    </>}
    {message && <p className="notice success" role="status">{message}</p>}
    {revokePending && <p className="youtube-note"><a href="https://myaccount.google.com/connections" target="_blank" rel="noreferrer">開啟 Google 帳戶連線管理，移除 ClueShelf 授權 ↗</a></p>}
    {(error || callbackError) && <p className="notice error" role="alert">{error || callbackError}</p>}
    <p className="youtube-note">只讀取官方可取得的收藏資料，不下載影音。取消按讚或解除連結，不會刪除已匯入的收藏。</p>
  </section>;
}
