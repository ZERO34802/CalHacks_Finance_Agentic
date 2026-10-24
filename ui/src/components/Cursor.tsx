// A teammate's cursor: glides on a spring, wears a name tag in its kind's color, says what it found,
// and ripples when it acts. Positioned in the parent's coordinate space.
import { AnimatePresence, motion } from "framer-motion";
import type { ReactNode } from "react";

export default function Cursor({ x, y, color, name, kind, say, pulse = 0, dim = false, stub = false }: {
  x: number; y: number; color: string; name: string; kind?: string; say?: ReactNode; pulse?: number; dim?: boolean; stub?: boolean;
}) {
  return (
    <motion.div className="cursor" initial={false} animate={{ x, y, opacity: dim ? 0.35 : 1 }}
      transition={{ type: "spring", stiffness: 110, damping: 17, mass: 0.9 }} style={{ ["--c" as string]: color }}>
      <AnimatePresence>
        {pulse > 0 && (
          <motion.span key={pulse} className="ripple" initial={{ scale: 0.2, opacity: 0.7 }} animate={{ scale: 2.4, opacity: 0 }}
            exit={{ opacity: 0 }} transition={{ duration: 0.6 }} />
        )}
      </AnimatePresence>
      <svg className="arrow" width="22" height="24" viewBox="0 0 22 24" aria-hidden>
        <path d="M2 2 L2 19 L7 14.5 L10.5 22 L13.5 20.6 L10 13.4 L17 13 Z" fill="var(--c)" stroke="#fff" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
      <span className="tag">{name}{kind && <em>{kind}</em>}{stub && <i>stub</i>}</span>
      <AnimatePresence mode="wait">
        {say && (
          <motion.span key={String(say)} className="say" initial={{ opacity: 0, y: -4, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4 }} transition={{ duration: 0.25 }}>{say}</motion.span>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
