import { useCallback, useEffect, useState } from "react";
import {
  fetchProject,
  fetchProjectVideos,
  scanProject,
  thumbnailUrl,
  type Project,
  type ScanResult,
  type Video,
} from "../api";
import { formatBytes, formatDuration } from "../format";

interface Props {
  projectId: number;
  onBack: () => void;
  onOpenVideo: (videoId: number) => void;
}

function ProjectDetailView({ projectId, onBack, onOpenVideo }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<ScanResult | null>(null);

  const reload = useCallback(() => {
    fetchProject(projectId)
      .then(setProject)
      .catch(() => setError("案件を取得できませんでした"));
    fetchProjectVideos(projectId)
      .then(setVideos)
      .catch(() => setError("動画一覧を取得できませんでした"));
  }, [projectId]);

  useEffect(reload, [reload]);

  const onScan = async () => {
    setScanning(true);
    setError("");
    setScanResult(null);
    try {
      const result = await scanProject(projectId);
      setScanResult(result);
      reload();
    } catch (err) {
      setError(`スキャンに失敗しました: ${(err as Error).message}`);
    } finally {
      setScanning(false);
    }
  };

  return (
    <section>
      <button className="back" onClick={onBack}>
        ← 案件一覧へ戻る
      </button>
      {project && (
        <>
          <div className="section-head">
            <h2>{project.name}</h2>
            <button onClick={onScan} disabled={scanning || !project.folder_path}>
              {scanning ? "スキャン中..." : "フォルダをスキャン"}
            </button>
          </div>
          <p className="meta">
            {project.folder_path ?? "フォルダ未登録(案件一覧から登録し直してください)"}
          </p>
          {project.note && <p className="note">{project.note}</p>}
        </>
      )}

      {scanResult && (
        <p className="notice">
          スキャン完了: 追加 {scanResult.added} / 更新 {scanResult.updated} / 削除{" "}
          {scanResult.removed} / サムネイル生成 {scanResult.thumbnails_generated}
          {!scanResult.ffprobe_available &&
            " ※FFprobeが見つからないため、動画メタデータは取得できませんでした"}
          {!scanResult.ffmpeg_available &&
            " ※FFmpegが見つからないため、サムネイルは生成できませんでした"}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {videos.length === 0 ? (
        <p className="empty">
          動画がまだ登録されていません。「フォルダをスキャン」を実行してください。
        </p>
      ) : (
        <div className="video-grid">
          {videos.map((v) => (
            <button
              key={v.id}
              className="video-card"
              onClick={() => onOpenVideo(v.id)}
            >
              {v.has_thumbnail ? (
                <img src={thumbnailUrl(v.id)} alt="" loading="lazy" />
              ) : (
                <div className="thumb-placeholder">サムネイルなし</div>
              )}
              <span className="video-name">{v.file_name}</span>
              <span className="meta">
                {formatDuration(v.duration_seconds)}
                {v.width && v.height ? ` / ${v.width}×${v.height}` : ""}
                {` / ${formatBytes(v.size_bytes)}`}
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export default ProjectDetailView;
