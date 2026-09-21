import { describe, it, expect } from "vitest";
import { chunkBlocks, groupText, type TextBox } from "./pdfLayout";
describe("PDF translation layout", () => {
  it("keeps columns separate and leaves numeric labels unchanged", () => {
    const boxes = groupText([
      { id: 0, text: "Left paragraph", x: 20, y: 20, width: 220, height: 10 },
      { id: 1, text: "Right paragraph", x: 330, y: 20, width: 220, height: 10 },
      { id: 2, text: "continued left", x: 20, y: 33, width: 220, height: 10 },
      { id: 3, text: "42", x: 20, y: 70, width: 20, height: 10 },
    ]);
    expect(boxes).toHaveLength(2);
    expect(boxes[0].text).toBe("Left paragraph continued left");
    expect(boxes[1].x).toBe(330);
  });
  it("splits a dense page into requests the backend accepts", () => {
    const box = (id: number, text: string): TextBox => ({
      id,
      text,
      x: 0,
      y: id * 10,
      width: 100,
      height: 10,
    });
    const groups = chunkBlocks([box(0, "a".repeat(6000)), box(1, "b".repeat(6000)), box(2, "c")]);
    expect(groups.map((g) => g.length)).toEqual([1, 2]);
    expect(groups.flat().every((b) => groups.some((g) => g.includes(b)))).toBe(true);
    const byCount = chunkBlocks(
      Array.from({ length: 5 }, (_, i) => box(i, "word")),
      9000,
      2,
    );
    expect(byCount.map((g) => g.length)).toEqual([2, 2, 1]);
    expect(chunkBlocks([])).toEqual([]);
  });
});

