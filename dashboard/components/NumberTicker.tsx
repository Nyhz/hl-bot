"use client";
import { useEffect, useRef, useState } from "react";

export function NumberTicker({ value, format, ms = 400 }: { value: number; format: (n: number) => string; ms?: number }) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  useEffect(() => {
    const from = fromRef.current, to = value, start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms);
      setDisplay(from + (to - from) * p);
      if (p < 1) raf = requestAnimationFrame(tick); else fromRef.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return <span>{format(display)}</span>;
}
