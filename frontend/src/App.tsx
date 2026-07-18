import { useEffect, useState } from "react";
import { fetchHealth } from "./api";
import ProjectDetailView from "./views/ProjectDetailView";
import ProjectListView from "./views/ProjectListView";
import PlayerView from "./views/PlayerView";
import "./App.css";

type BackendState = "checking" | "ok" | "error";

type Route =
  | { view: "projects" }
  | { view: "project"; projectId: number }
  | { view: "player"; projectId: number; videoId: number };

function App() {
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [backendVersion, setBackendVersion] = useState("");
  const [ffmpegOk, setFfmpegOk] = useState(true);
  const [route, setRoute] = useState<Route>({ view: "projects" });

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setBackendState(h.status === "ok" ? "ok" : "error");
        setBackendVersion(h.version);
        setFfmpegOk(h.ffmpeg_available && h.ffprobe_available);
      })
      .catch(() => setBackendState("error"));
  }, []);

  return (
    <main className="container">
      <header>
        <h1>Local Site Walk</h1>
        <p className="tagline">
          360°動画をローカルで管理・閲覧する現場ウォークスルーツール
        </p>
        <div className={`health health-${backendState}`}>
          {backendState === "checking" && "バックエンド確認中…"}
          {backendState === "ok" && `バックエンド接続OK (v${backendVersion})`}
          {backendState === "error" && "バックエンドに接続できません"}
        </div>
        {backendState === "ok" && !ffmpegOk && (
          <p className="notice">
            FFmpeg / FFprobe が見つかりません。動画の登録はできますが、
            メタデータ取得とサムネイル生成は行われません。
          </p>
        )}
      </header>

      {route.view === "projects" && (
        <ProjectListView
          onOpenProject={(projectId) => setRoute({ view: "project", projectId })}
        />
      )}
      {route.view === "project" && (
        <ProjectDetailView
          projectId={route.projectId}
          onBack={() => setRoute({ view: "projects" })}
          onOpenVideo={(videoId) =>
            setRoute({ view: "player", projectId: route.projectId, videoId })
          }
        />
      )}
      {route.view === "player" && (
        <PlayerView
          videoId={route.videoId}
          onBack={() =>
            setRoute({ view: "project", projectId: route.projectId })
          }
        />
      )}

      <footer>
        <p>
          データはローカル(社内)にのみ保存されます。外部クラウドへは送信しません。
        </p>
      </footer>
    </main>
  );
}

export default App;
