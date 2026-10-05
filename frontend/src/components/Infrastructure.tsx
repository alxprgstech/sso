import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "motion/react";
import { Box, Database, Fingerprint, Layers } from "lucide-react";
export default function Infrastructure() {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const bounds = useRef<DOMRect | null>(null);
  const pointer = useRef({ x: 50, y: 40 });
  const frame = useRef(0);
  const [visible, setVisible] = useState(
    document.visibilityState === "visible",
  );
  useEffect(() => {
    const changed = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);
  useEffect(
    () => () => {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
    },
    [reduced, visible],
  );
  // One measurement on entry and at most one style write per pointer frame.
  // No React render loop; hidden/reduced-motion scenes stay still.
  return (
    <div
      ref={ref}
      className="infrastructure"
      data-running={!reduced && visible}
      onPointerEnter={() => {
        bounds.current = ref.current?.getBoundingClientRect() || null;
      }}
      onPointerMove={(event) => {
        const rect = bounds.current;
        if (reduced || !visible || !rect) return;
        pointer.current = {
          x: ((event.clientX - rect.left) / rect.width) * 100,
          y: ((event.clientY - rect.top) / rect.height) * 100,
        };
        if (frame.current) return;
        frame.current = requestAnimationFrame(() => {
          frame.current = 0;
          ref.current?.style.setProperty(
            "--pointer-x",
            `${pointer.current.x}%`,
          );
          ref.current?.style.setProperty(
            "--pointer-y",
            `${pointer.current.y}%`,
          );
        });
      }}
    >
      <div className="topology-light" />
      <div className="topology-label">
        <span className="status-dot" /> ИНФРАСТРУКТУРА ALXPRGS
      </div>
      <svg className="topology-links" viewBox="0 0 600 600" fill="none">
        <path d="M300 300L130 160M300 300L480 180M300 300L140 460M300 300L470 430" />
        <path
          className="signal"
          d="M300 300L130 160M300 300L480 180M300 300L140 460M300 300L470 430"
        />
      </svg>
      <div className="topology-core">
        <img
          className="brand-art topology-brand"
          src="/brand/logo-mark.svg"
          alt=""
          width={44}
          height={44}
        />
        <strong>ALXPRGS SSO</strong>
        <span>IDENTITY / ACCESS</span>
      </div>
      <div className="topology-node node-one">
        <Box size={20} />
        <span>Приложения</span>
      </div>
      <div className="topology-node node-two">
        <Layers size={20} />
        <span>Сервисы</span>
      </div>
      <div className="topology-node node-three">
        <Database size={20} />
        <span>Сессии</span>
      </div>
      <div className="topology-node node-four">
        <Fingerprint size={20} />
        <span>Идентификация</span>
      </div>
      <div className="topology-caption">
        Единая точка доступа<span>alxprgs.tech / identity infrastructure</span>
      </div>
    </div>
  );
}
