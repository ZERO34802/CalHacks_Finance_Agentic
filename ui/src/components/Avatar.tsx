// Agent avatar: the shape says the kind (Claude = diamond, code = square, Factory Droid = hexagon).
import { CODE, KIND_COLOR, type Kind } from "../story";

export default function Avatar({ id, kind, size = 28, on = false, title }: { id: string; kind: Kind; size?: number; on?: boolean; title?: string }) {
  return (
    <span className={`av ${kind} ${on ? "on" : ""}`} title={title} style={{ width: size, height: size, ["--c" as string]: KIND_COLOR[kind], fontSize: size * 0.34 }}>
      <b>{CODE[id] ?? id.slice(0, 2).toUpperCase()}</b>
    </span>
  );
}
