"use client";

import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../../lib/api";
import { getCatalog, type Catalog } from "../../lib/taxonomy";
import TaxonomyManager from "../taxonomy-manager";

export default function CategoriesPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    setCatalog(await getCatalog());
  }, []);

  function refresh() {
    void load().catch(err => setError(errorMessage(err)));
  }
  useEffect(() => { void load().catch(err => setError(errorMessage(err))); }, [load]);

  return <>
    <header className="workspace-heading">
      <p className="workspace-kicker">整理你的收藏</p>
      <h1>分類管理</h1>
      <p>管理主題與標籤，讓下次搜尋更容易。</p>
    </header>
    {error && <div className="notice error" role="alert">{error} <button type="button" className="text-button" onClick={refresh}>重試</button></div>}
    {catalog ? <TaxonomyManager catalog={catalog} onChanged={load}/>
      : !error && <p role="status">正在讀取分類…</p>}
  </>;
}
