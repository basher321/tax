import { forwardRef, useCallback, useMemo, useRef } from "react";
import { FixedSizeList } from "react-window";

const ROW_HEIGHT = 30;
// Container fits content up to this many rows; beyond it, height is capped
// to roughly this many rows tall and the rest scrolls vertically.
const MAX_VISIBLE_ROWS = 20;

/* Row-virtualized table (react-window) for datasets too large to render as a
 * plain <table> — only the visible rows are ever in the DOM, so 50,000+ rows
 * scroll smoothly. Vertical scrolling comes from react-window itself;
 * horizontal scrolling comes from forcing the list's inner container to the
 * sum of the column widths (wider than the viewport) via innerElementType.
 * The header lives in its own div above the list and is kept in horizontal
 * sync by translating it with the list's own scrollLeft on every scroll. */
export default function VirtualizedTable({ columns, rows }) {
  const totalWidth = useMemo(
    () => columns.reduce((sum, c) => sum + c.width, 0),
    [columns],
  );
  // Content-driven height for <=20 rows (no leftover empty space below the
  // last row); capped to ~20 rows tall with a vertical scrollbar beyond that.
  const listHeight = Math.min(rows.length, MAX_VISIBLE_ROWS) * ROW_HEIGHT;
  const headerRef = useRef(null);

  const Outer = useMemo(() => forwardRef(function Outer(props, ref) {
    const { onScroll, style, ...rest } = props;
    return (
      <div
        ref={ref}
        // Force the horizontal scrollbar to always render (rather than only
        // on hover/overlay) so it's visible and discoverable whenever
        // columns overflow the container width.
        style={{ ...style, overflowX: "scroll", overflowY: "auto" }}
        {...rest}
        onScroll={(e) => {
          onScroll?.(e);
          if (headerRef.current) {
            headerRef.current.style.transform = `translateX(-${e.currentTarget.scrollLeft}px)`;
          }
        }}
      />
    );
  }), []);

  const Inner = useMemo(() => forwardRef(function Inner({ style, ...rest }, ref) {
    return <div ref={ref} style={{ ...style, width: totalWidth }} {...rest} />;
  }), [totalWidth]);

  const Row = useCallback(({ index, style }) => {
    const row = rows[index];
    return (
      <div
        style={{ ...style, width: totalWidth }}
        className={`flex border-b border-rule/60 ${index % 2 ? "bg-paper/40" : "bg-white"} hover:bg-ledger/[0.05]`}
      >
        {columns.map((col) => (
          <div
            key={col.key}
            style={{ width: col.width, flexShrink: 0 }}
            className={`px-2.5 py-1.5 text-xs truncate ${col.align === "right" ? "text-right font-mono" : ""}`}
            title={String(row?.[col.key] ?? "")}
          >
            {col.format ? col.format(row?.[col.key]) : row?.[col.key]}
          </div>
        ))}
      </div>
    );
  }, [rows, columns, totalWidth]);

  return (
    <div className="border border-rule rounded-md overflow-hidden bg-white">
      <div className="overflow-hidden">
        <div
          ref={headerRef}
          style={{ width: totalWidth }}
          className="flex bg-paper border-b border-rule"
        >
          {columns.map((col) => (
            <div
              key={col.key}
              style={{ width: col.width, flexShrink: 0 }}
              className={`px-2.5 py-2 text-xs font-semibold uppercase tracking-wide text-ink/60 truncate ${col.align === "right" ? "text-right" : ""}`}
            >
              {col.label}
            </div>
          ))}
        </div>
      </div>
      <FixedSizeList
        height={listHeight}
        width="100%"
        itemCount={rows.length}
        itemSize={ROW_HEIGHT}
        outerElementType={Outer}
        innerElementType={Inner}
      >
        {Row}
      </FixedSizeList>
    </div>
  );
}
