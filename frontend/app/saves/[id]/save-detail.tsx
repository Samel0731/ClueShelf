"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, errorMessage, getSave, type Save } from "../../../lib/api";
import { safeReturn, saveHref } from "../../../lib/shelf-routes";
import { getCatalog, type Catalog } from "../../../lib/taxonomy";
import Editor, { type DetailView } from "../../editor";

function isWorking(save: Save | null) {
  return save && ([save.ai_status, save.extraction_status].some(state => state === "queued" || state === "processing")
    || save.video_analysis?.state === "queued" || save.video_analysis?.state === "running");
}

export default function SaveDetail({ id }: { id: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const back = safeReturn(params.get("from"));
  const requested = params.get("view");
  const notice = params.get("notice");
  const [save, setSave] = useState<Save | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const [missing, setMissing] = useState(false);
  const version = useRef(0);
  const polling = useRef(false);
  const video = save?.platform === "youtube" && !save.duplicate_of;
  const view: DetailView = requested === "edit" ? "edit" : requested === "video" && video ? "video" : "content";

  const refresh = useCallback(async () => {
    const request = ++version.current;
    try {
      const next = await getSave(id);
      if (version.current !== request) return;
      setSave(current => {
        if (!current) return next;
        const previous = current.video_analysis;
        const updated = next.video_analysis;
        if (next.version === current.version && next.updated_at === current.updated_at
          && next.ai_status === current.ai_status && next.extraction_status === current.extraction_status
          && previous?.state === updated?.state && previous?.progress?.stage === updated?.progress?.stage
          && previous?.progress?.percent === updated?.progress?.percent) return current;
        return next;
      });
      setError("");
      setMissing(false);
    } catch (err) {
      if (version.current !== request) return;
      setError(errorMessage(err));
      if (err instanceof ApiError && err.status === 404) {
        setSave(null);
        setMissing(true);
      }
    }
  }, [id]);

  useEffect(() => {
    void refresh();
    return () => { version.current += 1; };
  }, [refresh]);
  useEffect(() => {
    if (view !== "edit" || catalog) return;
    let stale = false;
    void getCatalog().then(value => { if (!stale) setCatalog(value); }).catch(err => {
      if (!stale) setError(errorMessage(err));
    });
    return () => { stale = true; };
  }, [catalog, view]);
  const working = isWorking(save);
  useEffect(() => {
    if (!working && view !== "video") return;
    const timer = window.setInterval(() => {
      if (polling.current || document.visibilityState !== "visible") return;
      polling.current = true;
      void refresh().finally(() => { polling.current = false; });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [refresh, view, working]);

  function changeView(next: DetailView) {
    const url = new URL(window.location.href);
    if (next === "content") url.searchParams.delete("view");
    else url.searchParams.set("view", next);
    url.searchParams.delete("notice");
    window.history.pushState(null, "", url.pathname + url.search);
  }

  return <div className="workspace-detail">
    <Link className="workspace-back" href={back} scroll={false}>← {back.startsWith("/explore") ? "返回探索" : "返回收藏庫"}</Link>
    {notice === "added" && <p className="notice success" role="status">已加入收藏，背景工作已排入佇列。</p>}
    {notice === "duplicate" && <p className="notice success" role="status">已經收藏過這個連結，已開啟原收藏。</p>}
    {error && <div className="notice error" role="alert">
      {missing ? "找不到這筆收藏，可能已刪除。" : error}
      {!missing && <button type="button" className="text-button" onClick={() => void refresh()}>重試</button>}
    </div>}
    {!save && !error && <p role="status">正在讀取收藏…</p>}
    {save && <Editor
      save={save} catalog={catalog} view={view} onView={changeView}
      onChanged={next => { version.current += 1; setSave(next); }}
      onRefresh={refresh} onOpen={target => router.push(saveHref(target, back))}
      onDeleted={() => router.replace(back)}
    />}
  </div>;
}
