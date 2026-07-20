import { useEffect, useState, type FormEvent } from "react";
import {
  createProject,
  deleteProject,
  fetchProjects,
  type Project,
} from "../api";

interface Props {
  onOpenProject: (projectId: number) => void;
}

function ProjectListView({ onOpenProject }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [folderPath, setFolderPath] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reload = () => {
    fetchProjects()
      .then(setProjects)
      .catch(() => setError("案件一覧を取得できませんでした"));
  };

  useEffect(reload, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const created = await createProject({
        name,
        folder_path: folderPath.trim() || undefined,
        note: note.trim() || undefined,
      });
      setName("");
      setFolderPath("");
      setNote("");
      setShowForm(false);
      reload();
      onOpenProject(created.id);
    } catch (err) {
      setError(`案件を作成できませんでした: ${(err as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const onDelete = async (project: Project) => {
    if (!window.confirm(`案件「${project.name}」を削除しますか?`)) return;
    try {
      await deleteProject(project.id);
      reload();
    } catch (err) {
      setError(`削除できませんでした: ${(err as Error).message}`);
    }
  };

  return (
    <section>
      <div className="section-head">
        <h2>案件一覧</h2>
        <button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "閉じる" : "新規案件を登録"}
        </button>
      </div>

      {showForm && (
        <form className="project-form" onSubmit={onSubmit}>
          <label>
            案件名(必須)
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={200}
              placeholder="例: ○○ビル 3F 竣工前"
            />
          </label>
          <label>
            360°動画フォルダ(絶対パス・任意)
            <input
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              placeholder="例: C:\Users\you\LocalSiteWalkData\videos\siteA"
            />
          </label>
          <label>
            メモ(任意)
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="submit" disabled={submitting}>
            {submitting ? "作成中..." : "作成"}
          </button>
        </form>
      )}

      {error && <p className="error">{error}</p>}
      {projects.length === 0 && !error && (
        <p className="empty">登録済みの案件はまだありません。</p>
      )}

      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id}>
            <button className="project-link" onClick={() => onOpenProject(p.id)}>
              <strong>{p.name}</strong>
              <span className="meta">
                動画 {p.video_count} 件
                {p.folder_path ? ` / ${p.folder_path}` : " / フォルダ未登録"}
              </span>
              {p.note && <span className="note">{p.note}</span>}
            </button>
            <button className="danger" onClick={() => onDelete(p)}>
              削除
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default ProjectListView;
