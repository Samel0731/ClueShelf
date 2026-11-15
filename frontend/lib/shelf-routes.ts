import { platformSchema, searchModeSchema } from "./api";
import type { BrowseFilters } from "./explore";

export function readFilters(params: URLSearchParams): BrowseFilters {
  return {
    q: (params.get("q") ?? "").slice(0, 500),
    mode: searchModeSchema.safeParse(params.get("mode")).data ?? "hybrid",
    platform: platformSchema.safeParse(params.get("platform")).data ?? "all",
    topics: [...new Set(params.getAll("topic").filter(id => id.length > 0 && id.length <= 100))].slice(0, 20),
    tags: [...new Set(params.getAll("tag").filter(id => id.length > 0 && id.length <= 100))].slice(0, 30),
  };
}

export function shelfHref(path: "/" | "/explore", filters: BrowseFilters, graph = false) {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.mode !== "hybrid") params.set("mode", filters.mode);
  if (filters.platform !== "all") params.set("platform", filters.platform);
  filters.topics.forEach(id => params.append("topic", id));
  filters.tags.forEach(id => params.append("tag", id));
  if (path === "/explore" && graph) params.set("view", "graph");
  return params.size ? `${path}?${params}` : path;
}

export function safeReturn(href: string | null) {
  if (!href || !/^\/(?:\?|$|explore(?:\?|$))/.test(href)) return "/";
  return href;
}

export function saveHref(id: string, from: string, notice?: "added" | "duplicate") {
  const params = new URLSearchParams({ from: safeReturn(from) });
  if (notice) params.set("notice", notice);
  return `/saves/${encodeURIComponent(id)}?${params}`;
}
