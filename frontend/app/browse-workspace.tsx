"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, errorMessage, platformSchema, searchModeSchema, type Platform } from "../lib/api";
import { browseFacets, browseSaves, browseUpdates, type BriefSave, type BrowseFilters, type BrowseResponse } from "../lib/explore";
import { readFilters, saveHref, shelfHref } from "../lib/shelf-routes";
import { getCatalog, type Catalog, type Template } from "../lib/taxonomy";
import { ShelfMark } from "./app-shell";
import { SaveStatus } from "./editor";
import TagCloud from "./tag-cloud";

const GraphExplorer = dynamic(() => import("./graph-explorer"), {
  loading: () => <p role="status">正在載入關係圖…</p>,
});

const platforms = {
  youtube: { name: "YouTube", glyph: "▶" },
  instagram: { name: "Instagram", glyph: "◎" },
  threads: { name: "Threads", glyph: "@" },
} satisfies Record<Platform, { name: string; glyph: string }>;
const displayOptions = ["auto", "cards", "list"] as const;
type Display = typeof displayOptions[number];
const matchLabels: Record<string, string> = {
  display_title: "收藏標題", original_title: "原始標題", author_text: "作者內文",
  original_author_text: "平台原文", summary: "AI 摘要", topics: "主題", tags: "標籤",
  manual_comments: "手動補充留言", video_song: "影片解析 · 歌曲", video_stock: "影片解析 · 股票",
};

type Results = { key: string; scope: BrowseResponse; items: BriefSave[] };
const browseCache = new Map<string, { results: Results; time: number }>();
const returnPositions = new Map<string, number>();

function remember(key: string, results: Results) {
  browseCache.delete(key);
  browseCache.set(key, { results, time: Date.now() });
  const oldest = browseCache.keys().next().value;
  if (browseCache.size > 20 && oldest !== undefined) {
    browseCache.delete(oldest);
    returnPositions.delete(oldest);
  }
}

function SaveCard({ save, href, template, list, onOpen, onTag }: {
  save: BriefSave; href: string; template: Template; list: boolean; onOpen: () => void; onTag: (id: string) => void;
}) {
  const platform = platforms[save.platform];
  const excerpt = save.match_text || save.summary || save.excerpt;
  const label = save.match_field.startsWith("threads_comment") ? "Threads 留言" : matchLabels[save.match_field] ?? "收藏內容";
  return <article className={`save-card template-${template}${list ? " save-row" : ""}`}>
    <Link className="card-open" href={href} prefetch={false} onClick={onOpen}>
      <div className="card-top">
        <span className={`platform-icon ${save.platform}`} aria-hidden="true">{platform.glyph}</span>
        <span className="platform-name">{platform.name}</span><SaveStatus save={save}/>
      </div>
      <h3>{save.title || "尚未命名的收藏"}</h3>
      {excerpt && <div className={save.match_text ? "match-excerpt" : undefined}>
        {save.match_text && <span>{label}</span>}<p className="card-excerpt">{excerpt}</p>
      </div>}
      <div className="card-bottom"><time>{new Date(save.created_at * 1000).toLocaleDateString("zh-TW")}</time><span aria-hidden="true">查看內容 →</span></div>
    </Link>
    {!!(save.effective_topics.length || save.effective_tags.length) && <div className="card-classification">
      {save.effective_topics.map(topic => <span className="topic-pill" key={topic}>{topic}</span>)}
      {save.effective_tags.slice(0, 4).map((tag, index) => <button type="button" className="tag-pill" key={tag}
        onClick={() => { const id = save.tag_ids[index]; if (id) onTag(id); }}>#{tag}</button>)}
    </div>}
  </article>;
}

export default function BrowseWorkspace({ page }: { page: "library" | "explore" }) {
  const params = useSearchParams();
  const router = useRouter();
  const exploring = page === "explore";
  const path = exploring ? "/explore" : "/";
  const graph = exploring && params.get("view") === "graph";
  const queryString = params.toString();
  const filters = useMemo(() => readFilters(new URLSearchParams(queryString)), [queryString]);
  const key = shelfHref(path, filters);
  const currentHref = shelfHref(path, filters, graph);
  const [results, setResults] = useState<Results | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const [changed, setChanged] = useState(false);
  const [display, setDisplay] = useState<Display>("auto");
  const [filterOpen, setFilterOpen] = useState(false);
  const version = useRef(0);
  const polling = useRef(false);
  const search = useRef<HTMLInputElement>(null);
  const scope = results?.scope;
  const items = results?.items ?? [];
  const pending = results?.key !== key || loading;

  const loadCatalog = useCallback(async () => {
    try { setCatalog(await getCatalog()); setCatalogError(""); }
    catch (err) { setCatalogError(errorMessage(err)); }
  }, []);
  useEffect(() => { if (!exploring) void loadCatalog(); }, [exploring, loadCatalog]);
  useEffect(() => {
    try {
      const saved = localStorage.getItem("clueshelf.display");
      if (saved === "auto" || saved === "cards" || saved === "list") setDisplay(saved);
    } catch { /* Storage can be disabled. */ }
    function onShortcut(event: KeyboardEvent) {
      const target = event.target;
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey || document.querySelector("dialog[open]")) return;
      if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (!search.current) return;
      event.preventDefault();
      search.current?.focus();
    }
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, []);

  const refresh = useCallback(async () => {
    const request = ++version.current;
    setLoading(true);
    setLoadingMore(false);
    setError("");
    try {
      const scope = await browseSaves({ ...filters, q: filters.q.trim() });
      if (version.current !== request) return;
      const next = { key, scope, items: scope.items };
      remember(key, next);
      setResults(next);
      setChanged(false);
    } catch (err) {
      if (version.current === request) setError(errorMessage(err));
    } finally {
      if (version.current === request) setLoading(false);
    }
  }, [filters, key]);

  useEffect(() => {
    setError("");
    setChanged(false);
    setLoadingMore(false);
    const cached = browseCache.get(key);
    if (cached && (returnPositions.has(key) || Date.now() - cached.time < 60000)) {
      setResults(cached.results);
      setLoading(false);
    } else {
      setLoading(true);
      const timer = window.setTimeout(() => void refresh(), filters.q.trim() ? 350 : 0);
      return () => { window.clearTimeout(timer); version.current += 1; };
    }
    return () => { version.current += 1; };
  }, [filters.q, key, refresh]);

  const restorePosition = useCallback(() => {
    const top = returnPositions.get(key);
    if (top === undefined) return;
    returnPositions.delete(key);
    window.scrollTo(0, top);
  }, [key]);
  useEffect(() => {
    if (!pending && !graph) restorePosition();
  }, [pending, graph, restorePosition]);

  useEffect(() => {
    function added() {
      browseCache.clear();
      returnPositions.clear();
    }
    window.addEventListener("clueshelf:added", added);
    return () => window.removeEventListener("clueshelf:added", added);
  }, []);

  useEffect(() => {
    if (!results || pending || loadingMore) return;
    let stale = false;
    async function poll(snapshot: Results) {
      if (polling.current || document.visibilityState !== "visible") return;
      polling.current = true;
      try {
        const groups: string[][] = [];
        for (let offset = 0; offset < snapshot.items.length; offset += 100) {
          groups.push(snapshot.items.slice(offset, offset + 100).map(item => item.id));
        }
        if (!groups.length) groups.push([]);
        const [first, ...rest] = await Promise.all(groups.map(browseUpdates));
        if (stale || !first || first.data_revision === snapshot.scope.data_revision) return;
        const updates = [first, ...rest];
        const replacement = new Map(updates.flatMap(update => update.items).map(item => [item.id, item]));
        const deleted = new Set(updates.flatMap(update => update.deleted_ids));
        const facets = await browseFacets(snapshot.scope.snapshot_id);
        if (stale) return;
        const next = {
          ...snapshot,
          scope: { ...snapshot.scope, ...facets },
          items: snapshot.items.filter(item => !deleted.has(item.id)).map(item => {
            const newer = replacement.get(item.id);
            return newer ? { ...newer, match_field: item.match_field, match_text: item.match_text } : item;
          }),
        };
        remember(key, next);
        setResults(next);
        setChanged(true);
        if (!exploring && facets.catalog_revision !== snapshot.scope.catalog_revision) void loadCatalog();
      } catch (err) {
        if (!stale && err instanceof ApiError && err.status === 410) setChanged(true);
      } finally {
        polling.current = false;
      }
    }
    const timer = window.setInterval(() => void poll(results), 5000);
    return () => { stale = true; window.clearInterval(timer); };
  }, [results, pending, loadingMore, key, exploring, loadCatalog]);

  async function loadMore() {
    if (!results || !scope?.next_cursor || pending || loadingMore) return;
    const request = version.current;
    setLoadingMore(true);
    setError("");
    try {
      const next = await browseSaves({ ...filters, q: filters.q.trim() }, {
        cursor: scope.next_cursor, snapshot_id: scope.snapshot_id,
      });
      if (version.current !== request) return;
      const merged = new Map([...results.items, ...next.items].map(item => [item.id, item]));
      const value = { key, scope: next, items: [...merged.values()] };
      remember(key, value);
      setResults(value);
    } catch (err) {
      if (version.current === request) setError(errorMessage(err));
    } finally {
      if (version.current === request) setLoadingMore(false);
    }
  }

  function setFilters(change: Partial<BrowseFilters>, replace = false) {
    const href = shelfHref(path, { ...filters, ...change }, graph);
    if (replace) window.history.replaceState(null, "", href);
    else window.history.pushState(null, "", href);
  }

  function rememberPosition() {
    if (!results || pending) return;
    remember(key, results);
    returnPositions.set(key, window.scrollY);
  }

  function filterInLibrary(kind: "topic" | "tag", id: string) {
    const field = kind === "topic" ? "topics" : "tags";
    const selected = [...new Set([...filters[field], id])].slice(-(kind === "topic" ? 20 : 30));
    router.push(shelfHref("/", { ...filters, [field]: selected }));
  }

  function chooseDisplay(next: Display) {
    setDisplay(next);
    try { localStorage.setItem("clueshelf.display", next); } catch { /* Storage can be disabled. */ }
  }

  const activeFilters = Boolean(filters.q || filters.platform !== "all" || filters.topics.length || filters.tags.length);
  const chosenTopic = filters.topics.length === 1 ? catalog?.items.find(item => item.id === filters.topics[0]) : undefined;
  const template = display === "auto" ? chosenTopic?.template ?? "generic" : "generic";
  const list = display === "list" || display === "auto" && (template === "music" || template === "resources");

  return <>
    <header className="workspace-heading">
      <p className="workspace-kicker">{exploring ? "從分類發現收藏" : "我的收藏空間"}</p>
      <h1>{exploring ? "探索" : "收藏庫"}</h1>
      <p>{exploring ? "從標籤或關係圖找出收藏之間的連結。" : "搜尋收藏的標題、摘要、歌名與股票，找回想看的內容。"}</p>
    </header>
    {exploring ? <nav className="workspace-tabs" aria-label="探索檢視">
      <Link href={shelfHref("/explore", filters)} aria-current={!graph ? "page" : undefined}>標籤</Link>
      <Link href={shelfHref("/explore", filters, true)} aria-current={graph ? "page" : undefined}>關係圖</Link>
    </nav> : <div className="shelf-tools">
      <label className="sr-only" htmlFor="shelf-search">搜尋收藏</label>
      <div className="workspace-search">
        <input ref={search} id="shelf-search" type="search" placeholder="搜尋收藏…" maxLength={500}
          value={filters.q} onChange={event => setFilters({ q: event.target.value }, true)}/>
        <kbd aria-hidden="true">/</kbd>
      </div>
      <div className="shelf-control-row">
        <div className="filters" aria-label="依平台篩選">
          <button type="button" aria-pressed={filters.platform === "all"} className={filters.platform === "all" ? "selected" : undefined}
            onClick={() => setFilters({ platform: "all" })}>全部</button>
          {platformSchema.options.map(platform => <button type="button" key={platform}
            aria-pressed={filters.platform === platform} className={filters.platform === platform ? "selected" : undefined}
            onClick={() => setFilters({ platform })}>{platforms[platform].name}</button>)}
        </div>
        <div className="shelf-options">
          <label htmlFor="search-mode">搜尋方式</label>
          <select id="search-mode" value={filters.mode} onChange={event => {
            const parsed = searchModeSchema.safeParse(event.target.value);
            if (parsed.success) setFilters({ mode: parsed.data });
          }}><option value="hybrid">智慧搜尋</option><option value="keyword">關鍵字</option><option value="semantic">語意搜尋</option></select>
          <button type="button" className="secondary" aria-expanded={filterOpen} aria-controls="shelf-filters" onClick={() => setFilterOpen(!filterOpen)}>篩選</button>
        </div>
      </div>
      {filterOpen && <div id="shelf-filters" className="shelf-filter-panel">
        <p className="field-note">收藏須同時符合已選條件。</p>
        <label htmlFor="shelf-topic">主題</label>
        <select id="shelf-topic" value="" disabled={filters.topics.length >= 20} onChange={event => {
          if (event.target.value) setFilters({ topics: [...filters.topics, event.target.value] });
        }}><option value="">選擇主題</option>{catalog?.items.filter(item =>
          item.kind === "topic" && !item.archived && !item.merged_into && !filters.topics.includes(item.id)
        ).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <label htmlFor="shelf-tag">標籤</label>
        <select id="shelf-tag" value="" disabled={filters.tags.length >= 30} onChange={event => {
          if (event.target.value) setFilters({ tags: [...filters.tags, event.target.value] });
        }}><option value="">選擇標籤</option>{catalog?.items.filter(item =>
          item.kind === "tag" && !item.archived && !item.merged_into && !filters.tags.includes(item.id)
        ).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        {catalogError && <p role="alert">{catalogError} <button type="button" className="text-button" onClick={() => void loadCatalog()}>重試</button></p>}
      </div>}
      {activeFilters && <div className="selected-filters">
        {filters.topics.map(id => <button className="topic-pill" key={id} type="button"
          onClick={() => setFilters({ topics: filters.topics.filter(topic => topic !== id) })}>
          {catalog?.items.find(item => item.id === id)?.name ?? scope?.topics.find(item => item.id === id)?.name ?? "主題"} ×
        </button>)}
        {filters.tags.map(id => <button className="tag-pill selected" key={id} type="button"
          onClick={() => setFilters({ tags: filters.tags.filter(tag => tag !== id) })}>
          #{catalog?.items.find(item => item.id === id)?.name ?? scope?.tags.find(item => item.id === id)?.name ?? "標籤"} ×
        </button>)}
        <button className="text-button" type="button" onClick={() => setFilters({ q: "", platform: "all", topics: [], tags: [] })}>清除搜尋與篩選</button>
      </div>}
    </div>}
    {!exploring && <div className="shelf-results-heading">
      <div><h2>{filters.q.trim() ? "搜尋結果" : "所有收藏"}</h2>{scope && !pending && <span>{scope.total} 筆</span>}</div>
      <label htmlFor="shelf-display" className="sr-only">收藏展示方式</label>
      <select id="shelf-display" value={display} onChange={event => {
        const next = displayOptions.find(option => option === event.target.value);
        if (next) chooseDisplay(next);
      }}><option value="auto">依主題調整版型</option><option value="cards">卡片</option><option value="list">精簡列表</option></select>
    </div>}
    {changed && <div className="update-hint" role="status">
      <span>收藏已更新。</span><button type="button" className="text-button" onClick={() => void refresh()}>更新結果</button>
    </div>}
    {error && <div className="notice error" role="alert">{error} <button type="button" className="text-button" onClick={() => void refresh()}>重試</button></div>}
    {scope?.notice && <p className="notice warning" role="status">{scope.notice}</p>}
    {loading && <p className="browse-progress" role="status">{scope ? "正在更新結果…" : "正在載入收藏…"}</p>}
    {results && scope && <div className={pending ? "results-pending" : undefined} inert={pending} aria-busy={loading}>
      {exploring ? graph ? <GraphExplorer
        scope={scope} filters={readFilters(new URLSearchParams(results.key.split("?")[1]))} revision={scope.data_revision} active={!pending}
        onReady={restorePosition}
        onOpen={id => { rememberPosition(); router.push(saveHref(id, currentHref)); }}
        onFilter={filterInLibrary} onScopeChanged={next => {
          const value = { key, scope: next, items: next.items };
          setResults(value);
          remember(key, value);
          setChanged(false);
        }}
      /> : <TagCloud tags={scope.tags} selected={filters.tags} onSelect={id => filterInLibrary("tag", id)}
        preparing={scope.index.pending > 0}/> : <>
        {items.length ? <div className={`save-list ${list ? "list-layout" : ""} theme-${template}`}>
          {items.map(save => <SaveCard key={save.id} save={save} href={saveHref(save.id, currentHref)}
            template={template} list={list} onOpen={rememberPosition}
            onTag={id => {
              if (filters.tags.includes(id)) setFilters({ tags: filters.tags.filter(tag => tag !== id) });
              else if (filters.tags.length < 30) setFilters({ tags: [...filters.tags, id] });
            }}/>)}
        </div> : <div className="empty-state">
          <div className="empty-mark"><ShelfMark/></div>
          <h3>{activeFilters ? "找不到符合條件的收藏" : "收藏庫準備好了"}</h3>
          <p>{activeFilters ? "試試縮短關鍵字，或移除一項篩選。" : "用頁首的「新增收藏」貼上第一個連結，或到設定同步 YouTube 按讚影片。"}</p>
        </div>}
        {scope.next_cursor && <div className="load-more">
          <button className="secondary" type="button" disabled={pending || loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? "正在載入…" : "載入更多"}
          </button><span>已載入 {items.length}／{scope.total} 筆</span>
        </div>}
      </>}
    </div>}
  </>;
}
