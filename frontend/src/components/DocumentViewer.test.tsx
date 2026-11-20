import { describe, expect, it } from "vitest";
import { documentFileUrl } from "./DocumentViewer";

describe("documentFileUrl", () => {
  it("points at the backend file endpoint through the proxy", () => {
    expect(documentFileUrl("abc-123")).toBe("/api/v1/documents/abc-123/file");
  });

  it("encodes the ID", () => {
    expect(documentFileUrl("a/b")).toBe("/api/v1/documents/a%2Fb/file");
  });
});
