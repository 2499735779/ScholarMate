export type TextBox = {
  id: number;
  text: string;
  x: number;
  y: number;
  width: number;
  height: number;
};
// Merge only adjacent lines in the same column; never mix columns by text order.
export function groupText(items: TextBox[]): TextBox[] {
  const lines: TextBox[] = [];
  for (const item of [...items].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const row = [...lines]
      .reverse()
      .find(
        (l) =>
          Math.abs(l.y - item.y) < Math.min(l.height, item.height) * 0.35 &&
          item.x >= l.x &&
          item.x - l.x - l.width < item.height * 1.8,
      );
    if (row) {
      row.text += " " + item.text;
      row.width = Math.max(row.width, item.x + item.width - row.x);
      row.height = Math.max(row.height, item.height);
    } else lines.push({ ...item });
  }
  const blocks: TextBox[] = [];
  for (const line of lines) {
    const previous = [...blocks]
      .reverse()
      .find(
        (b) =>
          Math.abs(b.x - line.x) < Math.min(line.height, 12) &&
          line.y >= b.y + b.height * 0.7 &&
          line.y - b.y - b.height < line.height * 0.7 &&
          Math.abs(b.width - line.width) < Math.max(30, b.width * 0.3) &&
          b.text.length + line.text.length < 1800,
      );
    if (previous) {
      previous.text += " " + line.text;
      previous.height = line.y + line.height - previous.y;
      previous.width = Math.max(previous.width, line.width);
    } else blocks.push({ ...line });
  }
  return blocks
    .filter((b) => /[a-zA-Z]{3,}/.test(b.text))
    .map((b, id) => ({ ...b, id }));
}
// Batch block ids for one translation request: the backend rejects a page part
// above 16,000 characters, so a dense page has to be split into several calls.
export function chunkBlocks(blocks: TextBox[], maxChars = 9000, maxBlocks = 120) {
  const groups: TextBox[][] = [];
  let group: TextBox[] = [],
    size = 0;
  for (const block of blocks) {
    if (group.length && (size + block.text.length > maxChars || group.length >= maxBlocks)) {
      groups.push(group);
      group = [];
      size = 0;
    }
    group.push(block);
    size += block.text.length;
  }
  if (group.length) groups.push(group);
  return groups;
}

