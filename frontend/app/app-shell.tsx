"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { createSave, errorMessage } from "../lib/api";
import { saveHref } from "../lib/shelf-routes";
import DetailDialog from "./detail-dialog";

const navigation = [
  { href: "/", label: "收藏庫", icon: "M4 5h16v14H4z M4 10h16 M9 10v9" },
  { href: "/explore", label: "探索", icon: "M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18 M16 8l-2 6-6 2 2-6z" },
  { href: "/categories", label: "分類管理", icon: "M4 4h7v7H4z M14 4h6v7h-6z M4 14h7v6H4z M14 14h6v6h-6z" },
  { href: "/settings", label: "設定", icon: "M4 6h16 M4 12h16 M4 18h16 M8 4v4 M16 10v4 M10 16v4" },
];

export function ShelfMark() {
  return <svg viewBox="0 0 40 40" fill="none" aria-hidden="true">
    <rect x="6" y="7" width="8" height="24" rx="2" fill="currentColor"/>
    <rect x="17" y="12" width="7" height="19" rx="2" fill="currentColor" opacity=".65"/>
    <path d="m28 9 7 20" stroke="currentColor" strokeWidth="6" strokeLinecap="round"/>
    <path d="M4 35h32" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
  </svg>;
}

function CaptureDialog({ close }: { close: () => void }) {
  const router = useRouter();
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const result = await createSave({
        url: String(data.get("url") ?? ""),
        title: String(data.get("title") ?? ""),
        author_text: String(data.get("author_text") ?? ""),
      });
      if (!result.duplicate) window.dispatchEvent(new Event("clueshelf:added"));
      const from = window.location.pathname + window.location.search;
      router.push(saveHref(result.save.id, from, result.duplicate ? "duplicate" : "added"));
      close();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return <DetailDialog title="新增收藏" onClose={() => { if (!busy) close(); }} autoFocusClose={false}>
    <form className="capture-form" onSubmit={submit}>
      <label htmlFor="capture-url">影片或貼文連結</label>
      <input data-dialog-initial-focus id="capture-url" name="url" type="url" placeholder="貼上 YouTube、Instagram 或 Threads 連結" required maxLength={2048} disabled={busy}/>
      <button type="button" className="text-button" aria-expanded={expanded} aria-controls="capture-extra" onClick={() => setExpanded(!expanded)}>
        {expanded ? "收起補充內容" : "＋ 補充標題或內文"}
      </button>
      <div id="capture-extra" hidden={!expanded}>
        <label htmlFor="capture-name">標題（選填）</label>
        <input id="capture-name" name="title" maxLength={500} disabled={busy}/>
        <label htmlFor="capture-text">作者內文（選填）</label>
        <textarea id="capture-text" name="author_text" maxLength={50000} rows={4} disabled={busy}/>
      </div>
      {error && <p role="alert" className="notice error">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? "儲存中…" : "加入收藏"}</button>
    </form>
  </DetailDialog>;
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [capturing, setCapturing] = useState(false);
  return <div className="workspace">
    <a className="skip-link" href="#main-content">跳至主要內容</a>
    <aside className="workspace-sidebar">
      <Link className="workspace-brand" href="/" aria-label="ClueShelf 首頁">
        <ShelfMark/><span>ClueShelf<small>集緒 · 個人收藏庫</small></span>
      </Link>
      <nav className="workspace-nav" aria-label="主要導覽">
        {navigation.map(item => {
          const active = pathname === item.href || item.href === "/" && pathname.startsWith("/saves/");
          return <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={item.icon}/></svg>
            {item.label}
          </Link>;
        })}
      </nav>
      <p className="workspace-private"><span className="local-dot"/>本地私人收藏庫</p>
    </aside>
    <div className="workspace-main">
      <header className="workspace-top">
        <span>集緒 <span aria-hidden="true">/</span> 個人收藏</span>
        <button className="primary" type="button" onClick={() => setCapturing(true)}>＋ 新增收藏</button>
      </header>
      <main id="main-content" className="workspace-content" tabIndex={-1}>{children}</main>
    </div>
    {capturing && <CaptureDialog close={() => setCapturing(false)}/>}
  </div>;
}
