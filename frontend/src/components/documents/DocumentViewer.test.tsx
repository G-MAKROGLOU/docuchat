import { describe, expect, it } from "vitest";
import { documentFileUrl, highlightPhrases, highlightTarget } from "./DocumentViewer";

describe("highlightPhrases", () => {
  it("tries the start of the passage first and the anchor after it", () => {
    const passage = Array.from({ length: 100 }, (_, i) => `w${i}`).join("  \n ");

    const [long, short] = highlightPhrases(passage, "w0 w1 w2");

    expect(long?.split(" ")).toHaveLength(60);
    expect(long?.startsWith("w0 w1 w2 w3")).toBe(true);
    expect(short).toBe("w0 w1 w2");
  });

  it("gives the anchor once when the passage is not longer, and nothing without text", () => {
    expect(highlightPhrases("one two", "one two")).toEqual(["one two"]);
    expect(highlightPhrases(undefined, " one two ")).toEqual(["one two"]);
    expect(highlightPhrases()).toEqual([]);
  });
});

describe("highlightTarget", () => {
  it("marks the anchor on the cited page", () => {
    expect(highlightTarget(4, " The recommended starting dosage ")).toEqual({
      page: 4,
      phrase: "The recommended starting dosage",
    });
  });

  it("marks nothing without a page or an anchor", () => {
    expect(highlightTarget(undefined, "text")).toBeNull();
    expect(highlightTarget(4, "  ")).toBeNull();
    expect(highlightTarget(4)).toBeNull();
  });
});

describe("documentFileUrl", () => {
  it("points at the backend file endpoint through the proxy", () => {
    expect(documentFileUrl("abc-123")).toBe("/api/v1/documents/abc-123/file");
  });

  it("encodes the ID", () => {
    expect(documentFileUrl("a/b")).toBe("/api/v1/documents/a%2Fb/file");
  });

  it("ends in the title as a file name, so the viewer download is named by it", () => {
    expect(documentFileUrl("abc", "Toprol XL")).toBe("/api/v1/documents/abc/file/Toprol XL.pdf");
    expect(documentFileUrl("abc", "a/b?c#d%e")).toBe("/api/v1/documents/abc/file/a-b-c-d-e.pdf");
    expect(documentFileUrl("abc", "  ")).toBe("/api/v1/documents/abc/file");
  });
});
