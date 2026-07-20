// ローカルバックエンドとの通信のみ。外部サービスへのリクエストは行わない。
// 通常はViteのdevプロキシ経由(相対パス)。必要なら VITE_API_BASE_URL で上書き可能。
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export interface HealthStatus {
  status: string;
  version: string;
  ffprobe_available: boolean;
  ffmpeg_available: boolean;
}

export interface Project {
  id: number;
  name: string;
  folder_path: string | null;
  note: string | null;
  created_at: string;
  video_count: number;
}

export interface Video {
  id: number;
  project_id: number;
  file_name: string;
  file_path: string;
  size_bytes: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  codec: string | null;
  has_thumbnail: boolean;
  scanned_at: string | null;
}

export interface ScanResult {
  added: number;
  updated: number;
  removed: number;
  thumbnails_generated: number;
  ffprobe_available: boolean;
  ffmpeg_available: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // 応答がJSONでない場合はステータスコードのまま
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const fetchHealth = () => request<HealthStatus>("/api/health");

export const fetchProjects = () => request<Project[]>("/api/projects");

export const createProject = (payload: {
  name: string;
  folder_path?: string;
  note?: string;
}) =>
  request<Project>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteProject = (id: number) =>
  request<void>(`/api/projects/${id}`, { method: "DELETE" });

export const fetchProject = (id: number) =>
  request<Project>(`/api/projects/${id}`);

export const scanProject = (id: number) =>
  request<ScanResult>(`/api/projects/${id}/scan`, { method: "POST" });

export const fetchProjectVideos = (id: number) =>
  request<Video[]>(`/api/projects/${id}/videos`);

export const fetchVideo = (id: number) => request<Video>(`/api/videos/${id}`);

export const thumbnailUrl = (videoId: number) =>
  `${API_BASE}/api/videos/${videoId}/thumbnail`;

export const streamUrl = (videoId: number) =>
  `${API_BASE}/api/videos/${videoId}/stream`;
