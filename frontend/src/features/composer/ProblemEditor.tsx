import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BookOpen, FileSpreadsheet, Paperclip, Trash2, Upload, X } from "lucide-react";
import { Markdown } from "@/components/Content";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";
import { parseCsv } from "@/lib/csv";
import { DATA_FILE_ACCEPT } from "./files";
import { DataEditor } from "./DataEditor";

type MarkdownBlock = {
  start: number;
  contentEnd: number;
  end: number;
  content: string;
};

type LineSpan = {
  start: number;
  lineEnd: number;
  end: number;
  raw: string;
};

const ATX_HEADING = /^ {0,3}#{1,6}(?:[ \t]+.*|[ \t]*)$/;
const THEMATIC_BREAK = /^ {0,3}(?:-\s*-\s*-[-\s]*|\*\s*\*\s*\*[*\s]*|_\s*_\s*_[_\s]*)$/;
const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})/;
const SINGLE_LINE_MATH = /^ {0,3}(?:\$\$(?!\s*\$).+\$\$|\\\[[\s\S]+\\\])[ \t]*$/;
const MATH_DOLLAR_OPEN = /^ {0,3}\$\$[ \t]*$/;
const MATH_BRACKET_OPEN = /^ {0,3}\\\[/;
const LIST_ITEM = /^ {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]+/;
const LIST_BARE = /^ {0,3}(?:[-*+]|\d{1,9}[.)])[ \t]*$/;
const BLOCKQUOTE = /^ {0,3}>/;
const TABLE_ROW = /^ {0,3}\|.*\|[ \t]*$/;
const TABLE_DELIMITER = /^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)+\|?[ \t]*$/;

function isTableStart(lines: LineSpan[], index: number): boolean {
  if (TABLE_ROW.test(lines[index].raw)) return true;
  return lines[index].raw.includes("|") && index + 1 < lines.length && TABLE_DELIMITER.test(lines[index + 1].raw);
}

function isNewBlockAfterParagraph(lines: LineSpan[], index: number): boolean {
  const raw = lines[index].raw;
  return raw.trim() === "" || ATX_HEADING.test(raw) || THEMATIC_BREAK.test(raw) || FENCE_OPEN.test(raw)
    || SINGLE_LINE_MATH.test(raw) || MATH_DOLLAR_OPEN.test(raw) || MATH_BRACKET_OPEN.test(raw)
    || LIST_ITEM.test(raw) || BLOCKQUOTE.test(raw) || isTableStart(lines, index);
}

/** Partition Markdown into contiguous top-level source slices so rendered blocks never alter the underlying text. */
function splitMarkdownBlocks(text: string): MarkdownBlock[] {
  if (!text || !text.trim()) return [{ start: 0, contentEnd: text.length, end: text.length, content: text }];

  const lines: LineSpan[] = [];
  let offset = 0;
  for (const match of text.matchAll(/\r?\n/g)) {
    const lineEnd = match.index!;
    const end = lineEnd + match[0].length;
    lines.push({ start: offset, lineEnd, end, raw: text.slice(offset, lineEnd) });
    offset = end;
  }
  if (offset < text.length) lines.push({ start: offset, lineEnd: text.length, end: text.length, raw: text.slice(offset) });

  const blocks: MarkdownBlock[] = [];
  let index = 0;
  let closedAtEnd = false;

  if (lines[0]?.raw.trim() === "") {
    let blankEnd = index;
    while (blankEnd < lines.length && lines[blankEnd].raw.trim() === "") blankEnd++;
    blocks.push({ start: 0, contentEnd: 0, end: lines[blankEnd - 1].end, content: "" });
    index = blankEnd;
  }

  while (index < lines.length) {
    const first = lines[index];
    const raw = first.raw;
    let last = index;
    let selfClosing = false;

    const fence = FENCE_OPEN.exec(raw);
    if (fence) {
      const marker = fence[1][0];
      const length = fence[1].length;
      const closePattern = new RegExp(`^ {0,3}${marker}{${length},}[ \\t]*$`);
      last = index + 1;
      while (last < lines.length && !closePattern.test(lines[last].raw)) last++;
      if (last < lines.length) selfClosing = true;
      else last = lines.length - 1;
    } else if (ATX_HEADING.test(raw) || THEMATIC_BREAK.test(raw) || SINGLE_LINE_MATH.test(raw)) {
      selfClosing = true;
    } else if (MATH_DOLLAR_OPEN.test(raw)) {
      last = index + 1;
      while (last < lines.length && !/\$\$[ \t]*$/.test(lines[last].raw)) last++;
      if (last < lines.length) selfClosing = true;
      else last = lines.length - 1;
    } else if (MATH_BRACKET_OPEN.test(raw)) {
      last = index;
      while (last < lines.length && !/\\\][ \t]*$/.test(lines[last].raw)) last++;
      if (last < lines.length) selfClosing = true;
      else last = lines.length - 1;
    } else if (isTableStart(lines, index)) {
      while (last + 1 < lines.length && lines[last + 1].raw.trim() !== "" && lines[last + 1].raw.includes("|")) last++;
    } else if (LIST_ITEM.test(raw) || LIST_BARE.test(raw)) {
      while (last + 1 < lines.length) {
        const next = lines[last + 1].raw;
        if (next.trim() === "" || ATX_HEADING.test(next) || THEMATIC_BREAK.test(next) || FENCE_OPEN.test(next)
          || SINGLE_LINE_MATH.test(next) || MATH_DOLLAR_OPEN.test(next) || MATH_BRACKET_OPEN.test(next)
          || LIST_ITEM.test(next) || LIST_BARE.test(next) || BLOCKQUOTE.test(next) || isTableStart(lines, last + 1)) break;
        if (/^[ \t]{2,}\S/.test(next)) last++;
        else break;
      }
      if (LIST_ITEM.test(raw)) selfClosing = true;
    } else if (BLOCKQUOTE.test(raw)) {
      while (last + 1 < lines.length && lines[last + 1].raw.trim() !== "" && BLOCKQUOTE.test(lines[last + 1].raw)) last++;
    } else {
      const unclosedInlineMath = (raw.match(/\$\$/g)?.length ?? 0) % 2 === 1 || (raw.includes("\\(") && !raw.includes("\\)"));
      if (unclosedInlineMath) {
        while (last + 1 < lines.length && !isNewBlockAfterParagraph(lines, last + 1)) last++;
      } else if (!raw.includes("|")) {
        selfClosing = true;
      }
    }

    const atFinalLine = last === lines.length - 1;
    const hasTrailingNewline = lines[last].end > lines[last].lineEnd;
    let nextIndex = last + 1;
    let blankLinesAfter = 0;
    while (nextIndex < lines.length && lines[nextIndex].raw.trim() === "") {
      blankLinesAfter++;
      nextIndex++;
    }

    const keepTrailingNewlineInContent = atFinalLine && blankLinesAfter === 0 && !selfClosing && hasTrailingNewline;
    const contentEnd = keepTrailingNewlineInContent ? lines[last].end : lines[last].lineEnd;
    const end = blankLinesAfter > 0 ? lines[nextIndex - 1].end : lines[last].end;
    blocks.push({ start: first.start, contentEnd, end, content: text.slice(first.start, contentEnd) });

    if (nextIndex >= lines.length) {
      closedAtEnd = blankLinesAfter > 0 || (selfClosing && hasTrailingNewline);
    }
    index = nextIndex;
  }

  if (closedAtEnd) {
    blocks.push({ start: text.length, contentEnd: text.length, end: text.length, content: "" });
  }
  return blocks;
}

function blockIndexAtOffset(blocks: MarkdownBlock[], offset: number): number {
  const clamped = Math.max(0, offset);
  for (let i = 0; i < blocks.length; i++) {
    if (clamped >= blocks[i].start && clamped <= blocks[i].contentEnd) return i;
    if (clamped < blocks[i].end) return i;
  }
  return blocks.length - 1;
}

function blocksWithEmpty(text: string, emptyOffset: number | null): MarkdownBlock[] {
  const base = splitMarkdownBlocks(text);
  if (emptyOffset === null) return base;
  let clamped = Math.max(0, Math.min(emptyOffset, text.length));
  if (clamped > 0 && text[clamped - 1] === "\r" && text[clamped] === "\n") clamped++;
  const idx = base.findIndex(block => clamped > block.contentEnd && clamped < block.end);
  if (idx === -1) return base;
  const block = base[idx];
  return [
    ...base.slice(0, idx),
    { start: block.start, contentEnd: block.contentEnd, end: clamped, content: block.content },
    { start: clamped, contentEnd: clamped, end: block.end, content: "" },
    ...base.slice(idx + 1),
  ];
}

function resolveDocumentPosition(text: string, cursor: number): {
  emptyOffset: number | null;
  index: number;
  localCursor: number;
} {
  let clamped = Math.max(0, Math.min(cursor, text.length));
  if (clamped > 0 && text[clamped - 1] === "\r" && text[clamped] === "\n") clamped++;
  const base = splitMarkdownBlocks(text);
  const gapIdx = base.findIndex(block => clamped > block.contentEnd && clamped < block.end);
  if (gapIdx !== -1) {
    return { emptyOffset: clamped, index: gapIdx + 1, localCursor: 0 };
  }
  const index = blockIndexAtOffset(base, clamped);
  const target = base[index];
  const localCursor = Math.max(0, Math.min(target.content.length, clamped - target.start));
  return { emptyOffset: null, index, localCursor };
}

function splitBeforeSlice(text: string, start: number): MarkdownBlock[] {
  if (start <= 0) return [];
  const before = splitMarkdownBlocks(text.slice(0, start));
  while (before.length && before[before.length - 1].start === start && before[before.length - 1].end === start && before[before.length - 1].content === "") {
    before.pop();
  }
  return before;
}

function isStructuralBlock(content: string): boolean {
  const firstLine = content.split(/\r?\n/, 1)[0] ?? "";
  return ATX_HEADING.test(firstLine) || THEMATIC_BREAK.test(firstLine) || FENCE_OPEN.test(firstLine)
    || SINGLE_LINE_MATH.test(firstLine) || MATH_DOLLAR_OPEN.test(firstLine) || MATH_BRACKET_OPEN.test(firstLine)
    || BLOCKQUOTE.test(firstLine) || (content.includes("|") && content.includes("\n"));
}

function blockGapClass(blocks: MarkdownBlock[], index: number, activeIdx: number | null, source: string): string {
  let prevIndex = index - 1;
  while (prevIndex >= 0 && prevIndex !== activeIdx && !blocks[prevIndex].content.trim()) prevIndex--;
  if (prevIndex < 0) return "";
  const prev = blocks[prevIndex];
  const curr = blocks[index];
  const lineBreaks = source.slice(prev.contentEnd, curr.start).match(/\n/g)?.length ?? 0;
  return lineBreaks >= 2 || isStructuralBlock(prev.content) || isStructuralBlock(curr.content) ? "mt-2.5" : "mt-0.5";
}

function dataRowCount(name: string, content: string): number {
  if (/\.(csv|tsv)$/i.test(name)) {
    try { return parseCsv(content, /\.tsv$/i.test(name) ? "\t" : ",").length; }
    catch { /* Keep the attachment usable while it is being repaired. */ }
  }
  return content.split("\n").filter(Boolean).length;
}

type HistoryState = {
  entries: { value: string; cursor: number }[];
  index: number;
  lastPush: number;
};

function pushHistoryEntry(state: HistoryState, nextValue: string, cursor: number, timestamp: number, forceSplit = false) {
  const head = state.entries[state.index];
  if (head?.value === nextValue) return;
  const nextEntries = state.entries.slice(0, state.index + 1);
  if (!forceSplit && timestamp - state.lastPush < 400 && nextEntries.length > 1) {
    nextEntries[nextEntries.length - 1] = { value: nextValue, cursor };
    state.entries = nextEntries;
  } else {
    nextEntries.push({ value: nextValue, cursor });
    if (nextEntries.length > 100) nextEntries.shift();
    state.entries = nextEntries;
    state.index = nextEntries.length - 1;
  }
  state.lastPush = timestamp;
}

/** Unified problem & data composer card: live Markdown block rendering, inline data attachments, and integrated action bar. */
export function ProblemEditor({ value, data, onChange, onFiles, onDataChange, onRemove, onClear, onExamples, disabled = false, reading = false,
  label = t("问题描述"), actions, toolbarExtra, primaryAction, placeholder, autoFocus = false }: {
  value: string; data: Record<string, string>; onChange: (value: string) => void;
  onFiles: (files: FileList | null) => void; onRemove: (name: string) => void; onClear: () => void; onExamples?: () => void;
  onDataChange: (name: string, content: string) => void | Promise<void>;
  disabled?: boolean; reading?: boolean;
  autoFocus?: boolean;
  label?: string; actions?: ReactNode; toolbarExtra?: ReactNode; primaryAction?: ReactNode; placeholder?: string;
}) {
  const [dragging, setDragging] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const [emptyCursor, setEmptyCursor] = useState<number | null>(null);
  const [fullMode, setFullMode] = useState(false);
  const [composingSlice, setComposingSlice] = useState<{ start: number; contentEnd: number } | null>(null);

  const files = Object.entries(data);
  const locked = disabled || reading;
  const surface = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const pendingSelection = useRef<{ start: number; end: number } | null>(null);
  const pointerActivating = useRef(false);
  const composingRef = useRef(false);
  const composingSliceRef = useRef<{ start: number; contentEnd: number } | null>(null);
  const valueRef = useRef(value);
  useEffect(() => { valueRef.current = value; });
  const history = useRef<HistoryState>({
    entries: [{ value, cursor: value.length }],
    index: 0,
    lastPush: 0,
  });

  const blocks = useMemo<MarkdownBlock[]>(() => {
    if (composingSlice) {
      const start = Math.min(composingSlice.start, value.length);
      const contentEnd = Math.min(Math.max(start, composingSlice.contentEnd), value.length);
      const before = splitBeforeSlice(value, start);
      const afterRaw = value.slice(contentEnd);
      const afterOffset = contentEnd + (/^(?:\r?\n)+/.exec(afterRaw)?.[0].length ?? 0);
      const after = afterOffset < value.length
        ? splitMarkdownBlocks(value.slice(afterOffset)).map(b => ({
          start: b.start + afterOffset,
          contentEnd: b.contentEnd + afterOffset,
          end: b.end + afterOffset,
          content: b.content,
        }))
        : [];
      return [
        ...before,
        { start, contentEnd, end: afterOffset, content: value.slice(start, contentEnd) },
        ...after,
      ];
    }
    return blocksWithEmpty(value, emptyCursor);
  }, [value, composingSlice, emptyCursor]);

  const effectiveActive = disabled ? null : activeIndex !== null ? Math.min(activeIndex, blocks.length - 1) : null;
  const isEmpty = value.length === 0;
  const showFullTextarea = isEmpty || (!disabled && fullMode);
  const activeBlock = !showFullTextarea && effectiveActive !== null ? blocks[effectiveActive] : null;
  const textareaValue = showFullTextarea || !activeBlock ? value : activeBlock.content;

  useEffect(() => {
    if (composingRef.current) return;
    const current = history.current.entries[history.current.index];
    if (current?.value !== value) {
      history.current = { entries: [{ value, cursor: value.length }], index: 0, lastPush: 0 };
      setEmptyCursor(null);
    }
  }, [value]);

  useEffect(() => {
    if (autoFocus && !value && matchMedia("(pointer: fine)").matches && document.activeElement === document.body) {
      input.current?.focus({ preventScroll: true });
    }
  }, [autoFocus]); // eslint-disable-line react-hooks/exhaustive-deps

  const inlineBlockEditing = !showFullTextarea && activeBlock !== null && blocks.length > 1;

  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    if (inlineBlockEditing) {
      element.style.height = "0px";
      element.style.height = `${Math.max(26, element.scrollHeight)}px`;
    } else {
      element.style.height = "";
    }
    if (!composingRef.current && pendingSelection.current && document.activeElement === element) {
      const { start, end } = pendingSelection.current;
      pendingSelection.current = null;
      const max = element.value.length;
      element.setSelectionRange(Math.min(start, max), Math.min(end, max));
    }
  }, [textareaValue, effectiveActive, showFullTextarea, inlineBlockEditing]);

  const applyDocumentChange = (nextValue: string, globalCursor: number, timestamp: number, forceHistorySplit = false, beforeCursor?: number) => {
    if (beforeCursor !== undefined && history.current.entries[history.current.index]) {
      history.current.entries[history.current.index].cursor = beforeCursor;
    }
    pushHistoryEntry(history.current, nextValue, globalCursor, timestamp, forceHistorySplit);
    const { emptyOffset, index, localCursor } = resolveDocumentPosition(nextValue, globalCursor);
    setFullMode(false);
    setEmptyCursor(emptyOffset);
    setActiveIndex(index);
    pendingSelection.current = { start: localCursor, end: localCursor };
    onChange(nextValue);
  };

  const activateBlock = (index: number, cursorOffset?: number) => {
    if (disabled) return;
    pointerActivating.current = true;
    const baseBlocks = emptyCursor !== null ? splitMarkdownBlocks(value) : blocks;
    const targetBlock = blocks[Math.max(0, Math.min(index, blocks.length - 1))];
    const clampedIndex = emptyCursor !== null
      ? Math.max(0, Math.min(blockIndexAtOffset(baseBlocks, targetBlock.start), baseBlocks.length - 1))
      : Math.max(0, Math.min(index, blocks.length - 1));
    const target = baseBlocks[clampedIndex];
    const local = Math.max(0, Math.min(cursorOffset ?? target.content.length, target.content.length));
    setEmptyCursor(null);
    setFullMode(false);
    setActiveIndex(clampedIndex);
    const alreadyActive = !showFullTextarea && emptyCursor === null && clampedIndex === effectiveActive;
    pendingSelection.current = alreadyActive ? null : { start: local, end: local };
    input.current?.focus({ preventScroll: true });
    if (alreadyActive && input.current) {
      const max = input.current.value.length;
      input.current.setSelectionRange(Math.min(local, max), Math.min(local, max));
    }
    pointerActivating.current = false;
  };

  const beforeBlocks = showFullTextarea
    ? []
    : effectiveActive === null
      ? blocks
      : blocks.slice(0, effectiveActive);
  const afterBlocks = showFullTextarea || effectiveActive === null
    ? []
    : blocks.slice(effectiveActive + 1);

  const renderBlock = (block: MarkdownBlock, index: number) => {
    if (!block.content.trim()) return null;
    return <div key={block.start} data-slot="markdown-block"
      onMouseDown={event => {
        if (disabled || event.button !== 0) return;
        if ((event.target as Element | null)?.closest?.("button, a")) return;
        const selection = window.getSelection();
        if (selection && !selection.isCollapsed && selection.rangeCount > 0 && selection.containsNode(event.currentTarget, true)) return;
        event.preventDefault();
        activateBlock(index);
      }}
      className={cn(
        blockGapClass(blocks, index, effectiveActive, value),
        !disabled && "cursor-text",
      )}>
      <Markdown text={block.content} singleDollarMath={false} />
    </div>;
  };

  return <Card className={cn(
    "relative min-h-48 min-w-0 flex-1 gap-0 overflow-hidden rounded-2xl border-border/90 bg-card py-0 shadow-sm transition-[border-color,box-shadow] duration-200 focus-within:border-primary/45 focus-within:ring-3 focus-within:ring-primary/10 max-lg:max-h-[calc(100dvh-12rem)] lg:min-h-56",
    dragging && "border-primary ring-3 ring-primary/20")}
    onDragOver={event => {
      if (!event.dataTransfer.types?.includes("Files") && !event.dataTransfer.files?.length) return;
      event.preventDefault(); if (!locked) setDragging(true);
    }} onDragLeave={event => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false);
    }}
    onDrop={event => {
      setDragging(false);
      if (!event.dataTransfer.types?.includes("Files") && !event.dataTransfer.files?.length) return;
      event.preventDefault(); if (!locked) onFiles(event.dataTransfer.files);
    }}>
    <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border/60 bg-muted/20 px-4">
      <div className="flex min-w-0 items-center gap-2">
        <Label htmlFor="problem-description" className="min-w-0 truncate text-[13px] font-semibold text-foreground/90">{label}</Label>
        {value.length ? <span className="hidden text-[11px] text-muted-foreground tabular sm:inline">{t("{count} 字", { count: value.length })}</span> : null}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {actions}
        {value || files.length ? <Button type="button" variant="ghost" size="xs" disabled={locked}
          className="h-7 gap-1 rounded-lg px-2 text-xs text-muted-foreground hover:text-destructive"
          onClick={() => { composingRef.current = false; composingSliceRef.current = null; setComposingSlice(null); setEmptyCursor(null); setFullMode(false); setActiveIndex(null); onClear(); }}>
          <Trash2 className="size-3.5" />{t("清空")}</Button> : null}
      </div>
    </div>

    <div ref={surface}
      onMouseDown={event => {
        if (disabled || event.button !== 0 || event.target !== event.currentTarget || isEmpty) return;
        event.preventDefault();
        activateBlock(blocks.length - 1);
      }}
      className={cn(
        "relative flex min-h-24 flex-1 flex-col overflow-y-auto px-4 py-3.5",
        !disabled && "cursor-text",
      )}>
      {beforeBlocks.map((block, idx) => renderBlock(block, idx))}

      <Textarea ref={input} id="problem-description" aria-label={t("问题描述")} value={textareaValue} disabled={disabled}
        rows={inlineBlockEditing ? Math.max(1, textareaValue.split("\n").length) : undefined}
        placeholder={isEmpty
          ? (placeholder ?? t("请用日常语言描述你要优化的目标和限制条件。\n例如：工厂生产 A、B 两种产品，单件利润分别为 3 元和 2 元，怎样安排产量能让总利润最高？（支持直接拖拽 Excel / CSV 表格到这里）"))
          : undefined}
        onFocus={() => {
          if (disabled || pointerActivating.current || activeIndex !== null || fullMode) return;
          if (blocks.length <= 1) setActiveIndex(0);
          else setFullMode(true);
        }}
        onBlur={event => {
          if (pointerActivating.current) return;
          if (event.relatedTarget instanceof Node && surface.current?.contains(event.relatedTarget)) return;
          composingRef.current = false;
          composingSliceRef.current = null;
          setComposingSlice(null);
          setEmptyCursor(null);
          setFullMode(false);
          setActiveIndex(null);
        }}
        onCompositionStart={() => {
          composingRef.current = true;
          pendingSelection.current = null;
          if (!showFullTextarea && activeBlock) {
            const slice = { start: activeBlock.start, contentEnd: activeBlock.contentEnd };
            composingSliceRef.current = slice;
            setComposingSlice(slice);
            setActiveIndex(splitBeforeSlice(value, slice.start).length);
          } else {
            composingSliceRef.current = null;
            setComposingSlice(null);
            setFullMode(true);
          }
        }}
        onCompositionEnd={event => {
          if (!composingRef.current && !composingSliceRef.current) return;
          composingRef.current = false;
          const slice = composingSliceRef.current;
          composingSliceRef.current = null;
          setComposingSlice(null);
          const nextBlockText = event.currentTarget.value;
          const localCursor = event.currentTarget.selectionStart ?? nextBlockText.length;
          if (slice) {
            const nextValue = value.slice(0, slice.start) + nextBlockText + value.slice(slice.contentEnd);
            applyDocumentChange(nextValue, slice.start + localCursor, event.timeStamp, true);
          } else {
            applyDocumentChange(nextBlockText, localCursor, event.timeStamp, true);
          }
        }}
        onChange={event => {
          const rawInput = event.target.value;
          const localCursor = event.target.selectionStart ?? rawInput.length;
          const isComposing = composingRef.current || Boolean((event.nativeEvent as InputEvent).isComposing);
          if (isComposing) {
            if (composingSliceRef.current) {
              const slice = composingSliceRef.current;
              const nextValue = value.slice(0, slice.start) + rawInput + value.slice(slice.contentEnd);
              const updated = { start: slice.start, contentEnd: slice.start + rawInput.length };
              composingSliceRef.current = updated;
              setComposingSlice(updated);
              onChange(nextValue);
              return;
            }
            setFullMode(true);
            onChange(rawInput);
            return;
          }
          if (showFullTextarea || !activeBlock) {
            applyDocumentChange(rawInput, localCursor, event.timeStamp, Math.abs(rawInput.length - value.length) > 1);
            return;
          }
          const nextValue = value.slice(0, activeBlock.start) + rawInput + value.slice(activeBlock.contentEnd);
          const globalCursor = activeBlock.start + localCursor;
          applyDocumentChange(nextValue, globalCursor, event.timeStamp, rawInput.includes("\n") !== activeBlock.content.includes("\n"));
        }}
        onKeyDown={event => {
          if (event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
          const element = event.currentTarget;
          const start = element.selectionStart ?? 0;
          const end = element.selectionEnd ?? 0;
          const mod = event.ctrlKey || event.metaKey;
          const key = event.key.toLowerCase();

          if (mod && key === "a" && !showFullTextarea && blocks.length > 1) {
            event.preventDefault();
            setEmptyCursor(null);
            setFullMode(true);
            pendingSelection.current = { start: 0, end: value.length };
            return;
          }

          if (mod && (key === "z" || (key === "y" && !event.shiftKey))) {
            event.preventDefault();
            const state = history.current;
            const redo = key === "y" || event.shiftKey;
            const targetIndex = redo ? state.index + 1 : state.index - 1;
            if (targetIndex >= 0 && targetIndex < state.entries.length) {
              state.index = targetIndex;
              state.lastPush = 0;
              const entry = state.entries[targetIndex];
              const { emptyOffset, index, localCursor } = resolveDocumentPosition(entry.value, entry.cursor);
              setFullMode(false);
              setEmptyCursor(emptyOffset);
              setActiveIndex(index);
              pendingSelection.current = { start: localCursor, end: localCursor };
              onChange(entry.value);
            }
            return;
          }

          if (event.key === "Escape" && (effectiveActive !== null || fullMode) && !document.querySelector("[role=dialog]")) {
            event.preventDefault();
            composingRef.current = false;
            composingSliceRef.current = null;
            setComposingSlice(null);
            setEmptyCursor(null);
            setFullMode(false);
            setActiveIndex(null);
            element.blur();
            return;
          }

          if (showFullTextarea && !event.shiftKey && !mod && ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {
            requestAnimationFrame(() => {
              const current = input.current;
              if (!current || document.activeElement !== current || current.selectionStart !== current.selectionEnd) return;
              const cursor = current.selectionStart ?? 0;
              const { emptyOffset, index, localCursor } = resolveDocumentPosition(valueRef.current, cursor);
              setFullMode(false);
              setEmptyCursor(emptyOffset);
              setActiveIndex(index);
              pendingSelection.current = { start: localCursor, end: localCursor };
            });
            return;
          }

          if (!activeBlock || effectiveActive === null) return;

          if (event.key === "Backspace" && start === 0 && end === 0 && effectiveActive > 0) {
            event.preventDefault();
            const prev = blocks[effectiveActive - 1];
            const gap = value.slice(prev.contentEnd, activeBlock.start);
            const trimmedGap = gap.replace(/\r?\n$/, "");
            const nextValue = value.slice(0, prev.contentEnd) + trimmedGap + value.slice(activeBlock.start);
            applyDocumentChange(nextValue, prev.contentEnd + trimmedGap.length, event.timeStamp, true, activeBlock.start);
            return;
          }

          if (event.key === "Delete" && start === activeBlock.content.length && end === activeBlock.content.length && effectiveActive < blocks.length - 1) {
            event.preventDefault();
            const next = blocks[effectiveActive + 1];
            const gap = value.slice(activeBlock.contentEnd, next.start);
            const trimmedGap = gap.replace(/^\r?\n/, "");
            const nextValue = value.slice(0, activeBlock.contentEnd) + trimmedGap + value.slice(next.start);
            applyDocumentChange(nextValue, activeBlock.contentEnd, event.timeStamp, true, activeBlock.contentEnd);
            return;
          }

          if (!event.shiftKey && !event.altKey && !mod && start === end) {
            const lineHeight = parseFloat(getComputedStyle(element).lineHeight) || 0;
            const logicalLines = activeBlock.content.split("\n").length;
            const visuallyWrapped = lineHeight > 0 && element.scrollHeight > lineHeight * (logicalLines + 0.5);
            if (event.key === "ArrowUp" && effectiveActive > 0 && !activeBlock.content.slice(0, start).includes("\n")) {
              const prev = blocks[effectiveActive - 1];
              const lastNewline = prev.content.lastIndexOf("\n");
              const lastLineStart = lastNewline + 1;
              const targetOffset = Math.min(prev.content.length, lastLineStart + start);
              if (visuallyWrapped && start > 0) {
                requestAnimationFrame(() => {
                  const current = input.current;
                  if (current && document.activeElement === current && current.selectionStart === start && current.selectionEnd === start) {
                    activateBlock(effectiveActive - 1, targetOffset);
                  }
                });
              } else {
                event.preventDefault();
                activateBlock(effectiveActive - 1, targetOffset);
              }
            } else if (event.key === "ArrowDown" && effectiveActive < blocks.length - 1 && !activeBlock.content.slice(start).includes("\n")) {
              const lineStart = activeBlock.content.lastIndexOf("\n", start - 1) + 1;
              const col = start - lineStart;
              const next = blocks[effectiveActive + 1];
              const firstLineEnd = next.content.indexOf("\n");
              const maxCol = firstLineEnd === -1 ? next.content.length : firstLineEnd;
              const targetOffset = Math.min(maxCol, col);
              if (visuallyWrapped && start < activeBlock.content.length) {
                requestAnimationFrame(() => {
                  const current = input.current;
                  if (current && document.activeElement === current && current.selectionStart === start && current.selectionEnd === start) {
                    activateBlock(effectiveActive + 1, targetOffset);
                  }
                });
              } else {
                event.preventDefault();
                activateBlock(effectiveActive + 1, targetOffset);
              }
            } else if (event.key === "ArrowLeft" && start === 0 && effectiveActive > 0) {
              event.preventDefault();
              activateBlock(effectiveActive - 1, blocks[effectiveActive - 1].content.length);
            } else if (event.key === "ArrowRight" && start === activeBlock.content.length && effectiveActive < blocks.length - 1) {
              event.preventDefault();
              activateBlock(effectiveActive + 1, 0);
            }
          }
        }}
        className={cn(
          !showFullTextarea && effectiveActive === null
            ? "pointer-events-none absolute inset-0 h-full w-full resize-none border-0 bg-transparent opacity-0 shadow-none focus-visible:border-0 focus-visible:ring-0"
            : inlineBlockEditing
              ? cn(
                effectiveActive !== null && blockGapClass(blocks, effectiveActive, effectiveActive, value),
                "min-h-[1.65rem] w-full field-sizing-content resize-none overflow-hidden rounded-none border-0 bg-transparent p-0 text-base leading-[1.8] shadow-none focus-visible:border-0 focus-visible:ring-0 sm:text-sm dark:bg-transparent",
              )
              : "h-full min-h-28 flex-1 field-sizing-fixed resize-none rounded-none border-0 bg-transparent p-0 text-base leading-[1.8] shadow-none focus-visible:border-0 focus-visible:ring-0 sm:text-sm dark:bg-transparent",
        )} />

      {afterBlocks.map((block, idx) => renderBlock(block, (effectiveActive ?? 0) + 1 + idx))}
    </div>

    {files.length ? <ul aria-label={t("数据文件")} className="flex max-h-28 shrink-0 flex-wrap gap-2 overflow-y-auto border-t border-border/60 bg-muted/15 px-4 py-2.5">
      {files.map(([name, content]) => <li key={name} title={t("点击可在线查看或编辑 {name}", { name })}
        className="group/file flex min-w-0 max-w-full items-center gap-1.5 rounded-xl border bg-background py-1 pr-1 pl-2.5 text-xs shadow-2xs transition-colors hover:border-primary/40">
        <button type="button" disabled={locked} aria-label={t("编辑 {name}", { name })} onClick={() => setEditing(name)}
          className="flex min-w-0 items-center gap-1.5 rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
          <FileSpreadsheet className="size-3.5 shrink-0 text-primary/80" /><span className="max-w-44 truncate font-medium">{name}</span>
        </button>
        <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground tabular">{t("{count} 行", { count: dataRowCount(name, content) })}</span>
        <Button variant="ghost" size="icon-xs" disabled={locked} aria-label={t("移除 {name}", { name })} className="rounded-lg text-muted-foreground hover:text-destructive" onClick={() => onRemove(name)}><X /></Button>
      </li>)}
    </ul> : null}

    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border/60 bg-muted/25 px-3 py-2.5 sm:px-4">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <Button variant="outline" size="sm" asChild className="h-8 rounded-xl bg-background/80 text-xs font-normal shadow-2xs">
          <label title={t("支持 Excel (.xlsx)、CSV、TSV、JSON 和文本文件；上传后可直接点击文件名在线编辑。")}
            className={cn("cursor-pointer", locked && "pointer-events-none opacity-50")}>
            {reading ? <Spinner /> : <Paperclip className="size-3.5 text-primary/80" />}{reading ? t("正在读取数据……") : t("上传数据表")}
            <input type="file" multiple disabled={locked} accept={DATA_FILE_ACCEPT} className="sr-only"
              onChange={event => { onFiles(event.target.files); event.target.value = ""; }} />
          </label>
        </Button>
        {onExamples && !primaryAction ? <Button variant="ghost" size="sm" className="h-8 rounded-xl text-xs font-normal text-muted-foreground" disabled={locked} onClick={onExamples}><BookOpen className="size-3.5" />{t("案例模板")}</Button> : null}
        {toolbarExtra}
      </div>
      {primaryAction ? <div className="flex w-full items-center justify-end sm:w-auto">{primaryAction}</div> : null}
    </div>

    {dragging ? <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-card/92 backdrop-blur-xs text-sm font-medium text-primary">
      <span className="grid size-11 place-items-center rounded-2xl bg-primary/10 text-primary"><Upload className="size-5" /></span>
      <span>{t("松开以添加数据文件")}</span>
      <span className="text-xs font-normal text-muted-foreground">{t("支持 Excel、CSV、TSV、JSON、TXT")}</span>
    </div> : null}
    {editing !== null && editing in data ? <DataEditor key={editing} name={editing} content={data[editing]}
      onSave={content => onDataChange(editing, content)} onClose={() => setEditing(null)} /> : null}
  </Card>;
}
