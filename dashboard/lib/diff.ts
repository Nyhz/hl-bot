import type { Position } from "./types";
export function diffPositions(prev: Position[], next: Position[]): { opened: string[]; closed: string[] } {
  const a = new Set(prev.map((p) => p.coin));
  const b = new Set(next.map((p) => p.coin));
  return {
    opened: next.filter((p) => !a.has(p.coin)).map((p) => p.coin),
    closed: prev.filter((p) => !b.has(p.coin)).map((p) => p.coin),
  };
}
