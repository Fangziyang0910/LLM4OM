/** Pure Markdown block partitioning, cursor-position mapping and undo history for the live editor. */

export type MarkdownBlock = {
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
export function splitMarkdownBlocks(text: string): MarkdownBlock[] {
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

export function blockIndexAtOffset(blocks: MarkdownBlock[], offset: number): number {
  const clamped = Math.max(0, offset);
  for (let i = 0; i < blocks.length; i++) {
    if (clamped >= blocks[i].start && clamped <= blocks[i].contentEnd) return i;
    if (clamped < blocks[i].end) return i;
  }
  return blocks.length - 1;
}

export function blocksWithEmpty(text: string, emptyOffset: number | null): MarkdownBlock[] {
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

export function resolveDocumentPosition(text: string, cursor: number): {
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

export function splitBeforeSlice(text: string, start: number): MarkdownBlock[] {
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

export function blockGapClass(blocks: MarkdownBlock[], index: number, activeIdx: number | null, source: string): string {
  let prevIndex = index - 1;
  while (prevIndex >= 0 && prevIndex !== activeIdx && !blocks[prevIndex].content.trim()) prevIndex--;
  if (prevIndex < 0) return "";
  const prev = blocks[prevIndex];
  const curr = blocks[index];
  const lineBreaks = source.slice(prev.contentEnd, curr.start).match(/\n/g)?.length ?? 0;
  return lineBreaks >= 2 || isStructuralBlock(prev.content) || isStructuralBlock(curr.content) ? "mt-2.5" : "mt-0.5";
}

export type HistoryState = {
  entries: { value: string; cursor: number }[];
  index: number;
  lastPush: number;
};

export function pushHistoryEntry(state: HistoryState, nextValue: string, cursor: number, timestamp: number, forceSplit = false) {
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
