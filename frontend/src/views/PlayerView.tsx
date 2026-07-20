import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { fetchVideo, streamUrl, type Video } from "../api";
import { formatDuration } from "../format";

interface Props {
  videoId: number;
  onBack: () => void;
}

/** 360°(equirectangular)動画をドラッグで見回せる最小ビューア。 */
function PlayerView({ videoId, onBack }: Props) {
  const [video, setVideo] = useState<Video | null>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    fetchVideo(videoId)
      .then(setVideo)
      .catch(() => setError("動画情報を取得できませんでした"));
  }, [videoId]);

  useEffect(() => {
    const container = containerRef.current;
    const videoEl = videoRef.current;
    if (!container || !videoEl) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError(
        "この環境ではWebGLを利用できないため、360°表示は行えません。"
      );
      return;
    }

    const width = container.clientWidth;
    const height = Math.max(320, Math.round(width * 0.5));
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1100);

    const texture = new THREE.VideoTexture(videoEl);
    texture.colorSpace = THREE.SRGBColorSpace;
    const geometry = new THREE.SphereGeometry(500, 60, 40);
    geometry.scale(-1, 1, 1); // 内側から見る
    const material = new THREE.MeshBasicMaterial({ map: texture });
    const sphere = new THREE.Mesh(geometry, material);
    scene.add(sphere);

    let lon = 0;
    let lat = 0;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    const dom = renderer.domElement;
    const onPointerDown = (e: PointerEvent) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      dom.setPointerCapture(e.pointerId);
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!dragging) return;
      lon -= (e.clientX - lastX) * 0.15;
      lat += (e.clientY - lastY) * 0.15;
      lat = Math.max(-85, Math.min(85, lat));
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onPointerUp = () => {
      dragging = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      camera.fov = Math.max(30, Math.min(100, camera.fov + e.deltaY * 0.05));
      camera.updateProjectionMatrix();
    };
    dom.addEventListener("pointerdown", onPointerDown);
    dom.addEventListener("pointermove", onPointerMove);
    dom.addEventListener("pointerup", onPointerUp);
    dom.addEventListener("wheel", onWheel, { passive: false });

    let frameId = 0;
    const animate = () => {
      frameId = requestAnimationFrame(animate);
      const phi = THREE.MathUtils.degToRad(90 - lat);
      const theta = THREE.MathUtils.degToRad(lon);
      camera.lookAt(
        Math.sin(phi) * Math.cos(theta),
        Math.cos(phi),
        Math.sin(phi) * Math.sin(theta),
      );
      renderer.render(scene, camera);
    };
    animate();

    const onResize = () => {
      const w = container.clientWidth;
      const h = Math.max(320, Math.round(w * 0.5));
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", onResize);
      dom.removeEventListener("pointerdown", onPointerDown);
      dom.removeEventListener("pointermove", onPointerMove);
      dom.removeEventListener("pointerup", onPointerUp);
      dom.removeEventListener("wheel", onWheel);
      texture.dispose();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      container.removeChild(dom);
    };
  }, [videoId]);

  const togglePlay = () => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) {
      el.play().catch(() => setError("再生を開始できませんでした"));
    } else {
      el.pause();
    }
  };

  const onSeek = (value: number) => {
    const el = videoRef.current;
    if (!el || !Number.isFinite(el.duration)) return;
    el.currentTime = value;
  };

  return (
    <section>
      <button className="back" onClick={onBack}>
        ← 動画一覧へ戻る
      </button>
      <h2>{video?.file_name ?? "360°プレイヤー"}</h2>
      <p className="meta">
        ドラッグで見回し / ホイールでズーム。equirectangular(全天球)動画を想定しています。
      </p>
      {error && <p className="error">{error}</p>}

      <div className="player-canvas" ref={containerRef} />

      <video
        ref={videoRef}
        src={streamUrl(videoId)}
        style={{ display: "none" }}
        playsInline
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onDurationChange={(e) => setDuration(e.currentTarget.duration)}
        onError={() => setError("動画を読み込めませんでした")}
      />

      <div className="player-controls">
        <button onClick={togglePlay}>{playing ? "一時停止" : "再生"}</button>
        <input
          type="range"
          min={0}
          max={Number.isFinite(duration) ? duration : 0}
          step={0.1}
          value={currentTime}
          onChange={(e) => onSeek(Number(e.target.value))}
        />
        <span className="meta">
          {formatDuration(currentTime)} / {formatDuration(duration)}
        </span>
      </div>
    </section>
  );
}

export default PlayerView;
