import { z } from "zod";
import { ApiError } from "./api";

const count = z.number().int().nonnegative();
const syncSchema = z.object({
  id: z.string(),
  state: z.enum(["queued", "running", "completed", "cancelled", "paused", "failed"]),
  read_count: count,
  new_count: count,
  existing_count: count,
  skipped_count: count,
  failure_count: count,
  ai_waiting: count,
  skip_reasons: z.record(z.string(), count),
  error: z.string().nullable(),
  cancel_requested: z.boolean(),
  created_at: z.number(),
  updated_at: z.number(),
});

const statusSchema = z.object({
  configured: z.boolean(),
  configuration_error: z.string().nullable(),
  connection: z.object({
    id: z.string(),
    channel_id: z.string(),
    channel_title: z.string(),
    status: z.enum(["connected", "reauthorize", "disconnected"]),
    last_complete_scan_at: z.number().nullable(),
  }).nullable(),
  sync: syncSchema.nullable(),
});

export type YouTubeStatus = z.infer<typeof statusSchema>;
export type YouTubeSync = z.infer<typeof syncSchema>;

async function request(path: string, method: "GET" | "POST" = "GET"): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/youtube${path}`, {
      method,
      cache: "no-store",
      ...(method === "POST" ? {headers: {"Content-Type": "application/json"}, body: "{}"} : {}),
    });
  } catch {
    throw new ApiError("無法連線，請確認本機服務已啟動。", 0);
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = z.object({detail: z.string()}).safeParse(payload);
    throw new ApiError(error.success ? error.data.detail : "YouTube 操作未完成，請稍後再試。", response.status);
  }
  return payload;
}

export async function youtubeStatus(): Promise<YouTubeStatus> {
  const parsed = statusSchema.safeParse(await request("/status"));
  if (!parsed.success) throw new ApiError("YouTube 資料格式不符，請確認前後端版本一致。", 0);
  return parsed.data;
}

export async function connectYouTube() {
  return z.object({opened: z.literal(true)}).parse(await request("/oauth/start", "POST"));
}

export async function syncYouTube() {
  return syncSchema.parse(await request("/sync", "POST"));
}

export async function cancelYouTubeSync() {
  return syncSchema.nullable().parse(await request("/sync/cancel", "POST"));
}

export async function disconnectYouTube() {
  return z.object({disconnected: z.literal(true), revoke_pending: z.boolean()}).parse(await request("/disconnect", "POST"));
}
