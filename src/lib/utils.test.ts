import { describe, it, expect } from "vitest";
import { formatBytes } from "./utils";
describe("storage formatting", () => {
  it("reports sizes the way a file manager does", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(1024 * 1024 * 3.5)).toBe("3.5 MB");
    expect(formatBytes(1024 ** 3 * 2)).toBe("2 GB");
  });
});

