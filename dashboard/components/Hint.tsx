// Iconito "?" con tooltip explicativo al hover/focus. CSS en globals.css (.hint / .hint-pop).
export function Hint({ text }: { text: string }) {
  return (
    <span className="hint" tabIndex={0} role="note" aria-label={text}>
      ?<span className="hint-pop">{text}</span>
    </span>
  );
}
