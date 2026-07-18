import { useEffect, useState } from "react";
import { fetchHealth, fetchProjects, type Project } from "./api";
import "./App.css";

type BackendState = "checking" | "ok" | "error";

function App() {
  const [backendState, setBackendState] = useState<BackendState>("checking");
  const [backendVersion, setBackendVersion] = useState<string>("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string>("");
  const [showRegisterNote, setShowRegisterNote] = useState(false);

  useEffect(() => {
    fetchHealth()
      .then((h) => {
        setBackendState(h.status === "ok" ? "ok" : "error");
        setBackendVersion(h.version);
      })
      .catch(() => setBackendState("error"));

    fetchProjects()
      .then(setProjects)
      .catch(() => setProjectsError("案件一覧を取得できませんでした"));
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
      </header>

      <section>
        <div className="section-head">
          <h2>案件一覧</h2>
          <button onClick={() => setShowRegisterNote(true)}>
            新規案件を登録
          </button>
        </div>
        {showRegisterNote && (
          <p className="notice">
            案件登録(360°動画のアップロード)は未実装です。今後のバージョンで対応予定です。
          </p>
        )}
        {projectsError && <p className="error">{projectsError}</p>}
        {!projectsError && projects.length === 0 && (
          <p className="empty">登録済みの案件はまだありません。</p>
        )}
        {projects.length > 0 && (
          <ul className="project-list">
            {projects.map((p) => (
              <li key={p.id}>
                <strong>{p.name}</strong>
                <span className="meta">
                  {p.status}
                  {p.recorded_at ? ` / 撮影日: ${p.recorded_at}` : ""}
                </span>
                {p.note && <span className="note">{p.note}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer>
        <p>
          データはローカル(社内)にのみ保存されます。外部クラウドへは送信しません。
        </p>
      </footer>
    </main>
  );
}

export default App;
