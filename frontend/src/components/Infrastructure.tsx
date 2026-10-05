import {
  useEffect,
  useRef,
  useState,
  type RefObject,
  type PointerEvent,
} from "react";
import { useReducedMotion } from "motion/react";
import { Box, Database, Fingerprint, Layers } from "lucide-react";

// Cards and SVG use the same percentage anchors, independent of the panel's aspect ratio.
const nodes = [
  { className: "node-one", label: "Приложения", Icon: Box, x: 20, y: 28 },
  { className: "node-two", label: "Сервисы", Icon: Layers, x: 85, y: 31 },
  { className: "node-three", label: "Сессии", Icon: Database, x: 20, y: 75 },
  {
    className: "node-four",
    label: "Идентификация",
    Icon: Fingerprint,
    x: 82,
    y: 70,
  },
];

function useDocumentVisibility() {
  const [visible, setVisible] = useState(
    document.visibilityState === "visible",
  );
  useEffect(() => {
    const changed = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);
  return visible;
}

function usePointerLighting(ref: RefObject<HTMLDivElement>, running: boolean) {
  const bounds = useRef<DOMRect | null>(null);
  const pointer = useRef({ x: 50, y: 40 });
  const frame = useRef(0);
  useEffect(
    () => () => {
      cancelAnimationFrame(frame.current);
      frame.current = 0;
    },
    [running],
  );
  // One measurement on entry and at most one style write per pointer frame.
  // No React render loop; hidden/reduced-motion scenes stay still.
  return {
    onPointerEnter: () => {
      bounds.current = ref.current?.getBoundingClientRect() || null;
    },
    onPointerMove: (event: PointerEvent<HTMLDivElement>) => {
      const rect = bounds.current;
      if (!running || !rect) return;
      pointer.current = {
        x: ((event.clientX - rect.left) / rect.width) * 100,
        y: ((event.clientY - rect.top) / rect.height) * 100,
      };
      if (frame.current) return;
      frame.current = requestAnimationFrame(() => {
        frame.current = 0;
        ref.current?.style.setProperty("--pointer-x", `${pointer.current.x}%`);
        ref.current?.style.setProperty("--pointer-y", `${pointer.current.y}%`);
      });
    },
  };
}

export default function Infrastructure() {
  const reduced = useReducedMotion();
  const visible = useDocumentVisibility();
  const ref = useRef<HTMLDivElement>(null);
  const running = !reduced && visible;
  const pointerEvents = usePointerLighting(ref, running);
  return (
    <div
      ref={ref}
      className="infrastructure"
      data-running={running}
      {...pointerEvents}
    >
      <div className="topology-light" />
      <div className="topology-label">
        <span className="status-dot" /> ИНФРАСТРУКТУРА ALXPRGS
      </div>
      <svg className="topology-links" fill="none">
        {nodes.map(({ className, x, y }) => (
          <g key={className}>
            <line x1="50%" y1="50%" x2={`${x}%`} y2={`${y}%`} />
            <line
              className="signal"
              x1="50%"
              y1="50%"
              x2={`${x}%`}
              y2={`${y}%`}
            />
          </g>
        ))}
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
      {nodes.map(({ className, label, Icon, x, y }) => (
        <div
          key={className}
          className={`topology-node ${className}`}
          style={{ left: `${x}%`, top: `${y}%` }}
        >
          <Icon size={20} />
          <span>{label}</span>
        </div>
      ))}
      <div className="topology-caption">
        Единая точка доступа<span>alxprgs.tech / identity infrastructure</span>
      </div>
    </div>
  );
}
