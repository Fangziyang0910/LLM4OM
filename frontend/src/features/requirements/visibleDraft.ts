import { fromMarkdown } from "mdast-util-from-markdown";
import type { Nodes } from "mdast";

const optionalSection = /^(?:待确认(?:的?问题|事项|项)?|待澄清(?:问题)?|未解决的问题|备注|补充说明|假设|附件|open questions?|open issues?|assumptions?|notes?|attachments?)$/i;
const emptyStatement = /^(?:(?:目前|当前)?(?:暂无|没有|无)(?:待确认项|待确认事项|待确认的问题|补充说明|备注)|no (?:remaining |outstanding )?(?:open |pending )?questions?)$/i;
const emptyValue = /^(?:无|暂无|没有|不适用|none|n\/a|not applicable)(?:\s*[（(][^（）()\n]*已确认[）)])?$/i;

function label(text: string) {
  return text.trim().replace(/\*\*/g, "").replace(/[。.:：]+$/, "").trim();
}

/** Hide empty assistant sections in saved Markdown without rewriting the checkpoint or the user's current edits. */
export function visibleDraft(source: string): string {
  const lines = source.split("\n");
  const hidden = new Set<number>();
  const omit = (node: Nodes) => {
    for (let line = node.position!.start.line - 1; line < node.position!.end.line; line++) hidden.add(line);
  };
  const raw = (node: Nodes) => source.slice(node.position!.start.offset, node.position!.end.offset);
  let section: Nodes | undefined;
  let hasContent = false;
  const finishSection = () => { if (section && !hasContent) omit(section); };

  function placeholder(value: string) {
    const field = /^([^：:\n]+)[：:]\s*(.+)$/.exec(value);
    return emptyStatement.test(value) || (!!section && emptyValue.test(value))
      || (!!field && optionalSection.test(field[1].trim()) && emptyValue.test(field[2].trim()));
  }

  for (const block of fromMarkdown(source).children) {
    const name = label(raw(block).replace(/^#{1,6}\s+/, ""));
    if (block.type === "heading" || (block.type === "paragraph" && optionalSection.test(name))) {
      if (section?.type === "heading" && block.type === "heading" && block.depth > section.depth) hasContent = true;
      finishSection();
      section = optionalSection.test(name) ? block : undefined;
      if (!section && placeholder(name)) omit(block);
      hasContent = false;
    } else if (block.type === "list") {
      for (const item of block.children) {
        if (item.children.length === 1 && item.children[0].type === "paragraph" && placeholder(label(raw(item.children[0])))) omit(item);
        else hasContent = true;
      }
    } else if (block.type === "paragraph" && block.children.every(child => child.type === "text")) {
      for (let line = block.position!.start.line - 1; line < block.position!.end.line; line++) {
        if (placeholder(label(lines[line]))) hidden.add(line);
        else hasContent = true;
      }
    } else if (block.type === "paragraph" && placeholder(label(raw(block)))) omit(block);
    else hasContent = true;
  }
  finishSection();
  if (!hidden.size) return source;
  // Remove the spacing attached to an omitted line, preserving spacing in the rest of the draft.
  for (const line of hidden) if (line + 1 < lines.length && !lines[line + 1].trim()) hidden.add(line + 1);
  return lines.filter((_, line) => !hidden.has(line)).join("\n").trimEnd();
}
