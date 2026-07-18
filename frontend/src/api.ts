// ローカルバックエンドとの通信のみ。外部サービスへのリクエストは行わない。
// 通常はViteのdevプロキシ経由(相対パス)。必要なら VITE_API_BASE_URL で上書き可能。
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

export interface HealthStatus {
  status: string;
  version: string;
}

export interface Project {
  id: string;
  name: string;
  recorded_at: string | null;
  status: string;
  note: string | null;
}

export async function fetchHealth(): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error(`health check failed: ${res.status}`);
  return res.json();
}

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${API_BASE}/api/projects`);
  if (!res.ok) throw new Error(`projects fetch failed: ${res.status}`);
  return res.json();
}
