import { z } from "zod";

export const platformSchema = z.enum(["youtube", "instagram", "threads"]);
const videoModeSchema = z.enum(["text", "transcribe"]);
const videoSourceSchema = z.enum(["description", "chapter", "comment", "caption", "transcript"]);
const videoAnalysisSchema = z.object({
  state: z.enum(["queued", "running", "done", "failed"]),
  mode: videoModeSchema,
  error: z.string().nullable(),
  progress: z.object({
    stage: z.enum(["preparing", "downloading", "transcribing", "analyzing"]),
    percent: z.number().int().min(0).max(99).nullable(),
  }).nullable().default(null),
  result: z.object({
    mode: videoModeSchema,
    duration_seconds: z.number().nullable(),
    coverage: z.array(z.object({ source: videoSourceSchema, segments: z.number().int(), through_seconds: z.number().nullable() })),
    warnings: z.array(z.string()),
    findings: z.array(z.object({
      kind: z.enum(["song", "stock"]),
      name: z.string(),
      ticker: z.string().nullable(),
      evidence: z.array(z.object({ source: videoSourceSchema, quote: z.string(), start_seconds: z.number().nullable() })).nonempty(),
    })),
  }).nullable(),
});

export type VideoMode = z.infer<typeof videoModeSchema>;
export type VideoSource = z.infer<typeof videoSourceSchema>;

export const saveSchema = z.object({
  id: z.string(),
  owner_id: z.string(),
  platform: platformSchema,
  content_id: z.string(),
  url: z.url().refine((value) => value.startsWith("https://")),
  title: z.string(),
  author_text: z.string(),
  manual_comments: z.string().default(""),
  effective_topics: z.array(z.string()).default([]),
  effective_tags: z.array(z.string()).default([]),
  manual_topics: z.array(z.string()).nullable().default(null),
  manual_tags: z.array(z.string()).nullable().default(null),
  source: z.object({
    provider: z.literal("youtube_api").optional(),
    original_title: z.string(), author_text: z.string(), canonical_url: z.string().nullable(),
    comments: z.array(z.object({source_id: z.string(), text: z.string(), likes: z.number().int().nullable(), url: z.string().nullable()})),
    comments_ranking: z.enum(["likes", "visible", "unavailable", "not_applicable"]), fetched_count: z.number().int(),
    status: z.enum(["complete", "partial", "blocked", "failed"]), reason: z.string().nullable(), fetched_at: z.number(),
  }).nullable().default(null),
  analysis: z.object({suggested_title: z.string(), summary: z.string(), topics: z.array(z.string()), tags: z.array(z.string()), model: z.string(), generated_at: z.number(), input_truncated: z.boolean().default(false), summary_origin: z.enum(["ai", "source"]).default("ai")}).nullable().default(null),
  video_analysis: videoAnalysisSchema.nullable().default(null),
  extraction_status: z.enum(["idle", "queued", "processing", "complete", "partial", "blocked", "failed"]).default("idle"),
  ai_status: z.enum(["idle", "queued", "processing", "complete", "unavailable", "failed"]).default("idle"),
  extraction_error: z.string().nullable().default(null),
  ai_error: z.string().nullable().default(null),
  duplicate_of: z.string().nullable().default(null),
  version: z.number().int().positive(),
  status: z.enum(["queued", "processing", "needs_text", "ready", "failed"]),
  created_at: z.number(),
  updated_at: z.number(),
  job: z.object({ state: z.string(), attempts: z.number().int(), error: z.string().nullable() }).nullable(),
});

export type Save = z.infer<typeof saveSchema>;
export type Platform = z.infer<typeof platformSchema>;
export type SaveInput = Pick<Save, "url" | "title" | "author_text">;
export type SaveEdit = Pick<Save, "version"> & Partial<Pick<Save, "title" | "author_text" | "manual_comments">>;

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("無法連線，請確認本機服務已啟動，再試一次。", 0);
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const error = z.object({ detail: z.string() }).safeParse(payload);
    throw new ApiError(error.success ? error.data.detail : "服務暫時無法完成操作，請稍後再試。", response.status);
  }
  return response;
}

export async function listSaves(): Promise<Save[]> {
  const payload: unknown = await (await request("/saves")).json();
  const result = z.array(saveSchema).safeParse(payload);
  if (!result.success) throw new ApiError("收藏資料格式不符，請確認前後端版本一致。", 0);
  return result.data;
}

export async function getSave(id: string): Promise<Save> {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}`)).json();
  return saveSchema.parse(payload);
}

export async function createSave(input: SaveInput) {
  const payload: unknown = await (await request("/saves", { method: "POST", body: JSON.stringify(input) })).json();
  return z.object({ save: saveSchema, duplicate: z.boolean() }).parse(payload);
}

export async function editSave(id: string, input: SaveEdit) {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(input) })).json();
  return saveSchema.parse(payload);
}

export async function retrySave(id: string, version: number) {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}/retry`, { method: "POST", body: JSON.stringify({ version }) })).json();
  return saveSchema.parse(payload);
}

export async function processSave(id: string, version: number, action: "read" | "analyze") {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ version }) })).json();
  return saveSchema.parse(payload);
}

export async function requestVideoAnalysis(id: string, mode: VideoMode, audioAuthorized: boolean) {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}/video-analysis`, {
    method: "POST",
    body: JSON.stringify({ mode, audio_authorized: audioAuthorized }),
  })).json();
  return saveSchema.parse(payload);
}

export async function switchTitle(id: string, version: number, mode: "original" | "ai") {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}/title`, { method: "POST", body: JSON.stringify({ version, mode }) })).json();
  return saveSchema.parse(payload);
}

export async function deleteSave(id: string, version: number) {
  await request(`/saves/${encodeURIComponent(id)}?version=${version}`, { method: "DELETE" });
}

export function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "操作未完成，請再試一次。";
}

export const TOPICS = ["食譜", "餐廳", "旅遊", "音樂", "程式", "語言學習", "求職", "活動", "其他"];
export const searchModeSchema = z.enum(["keyword", "semantic", "hybrid"]);
export type SearchMode = z.infer<typeof searchModeSchema>;
const searchResponseSchema = z.object({
  results: z.array(z.object({save: saveSchema, score: z.number(), match_field: z.string(), match_text: z.string()})),
  requested_mode: searchModeSchema, used_mode: searchModeSchema, notice: z.string().nullable(),
});
export type SearchResponse = z.infer<typeof searchResponseSchema>;
const facetsSchema = z.object({topics: z.array(z.object({name: z.string(), count: z.number()})), tags: z.array(z.object({name: z.string(), count: z.number()})), index: z.object({pending: z.number(), failed: z.number().default(0), ready: z.number(), model_ready: z.boolean()})});
export type Facets = z.infer<typeof facetsSchema>;

export async function searchSaves(input: {q: string; mode: SearchMode; platform: Platform | "all"; topics: string[]; tags: string[]}) {
  const params = new URLSearchParams({q: input.q, mode: input.mode, limit: "50"});
  if (input.platform !== "all") params.set("platform", input.platform);
  input.topics.forEach((topic) => params.append("topic", topic));
  input.tags.forEach((tag) => params.append("tag", tag));
  const payload: unknown = await (await request(`/search?${params}`)).json();
  return searchResponseSchema.parse(payload);
}

export async function searchFacets() {
  const payload: unknown = await (await request("/search/facets")).json();
  return facetsSchema.parse(payload);
}

export async function reindexSearch() {
  const payload: unknown = await (await request("/search/reindex", {method: "POST", body: "{}"})).json();
  return z.object({queued: z.number().int()}).parse(payload);
}

export async function editClassification(id: string, input: {version: number; topics?: string[] | null; tags?: string[] | null}) {
  const payload: unknown = await (await request(`/saves/${encodeURIComponent(id)}/classification`, {method: "PATCH", body: JSON.stringify(input)})).json();
  return saveSchema.parse(payload);
}
