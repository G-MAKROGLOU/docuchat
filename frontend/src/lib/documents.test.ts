import { describe, expect, it } from "vitest";
import {
  activeIngredients,
  documentTitle,
  documentsUrl,
  downloadUrl,
  thumbnailUrl,
} from "./documents";

describe("documentTitle", () => {
  it("uses the brand name", () => {
    expect(documentTitle({ brand_name: "Brand", generic_name: "generic" })).toBe("Brand");
  });

  it("falls back to the generic name when the brand name is empty", () => {
    expect(documentTitle({ brand_name: " ", generic_name: "generic" })).toBe("generic");
  });
});

describe("activeIngredients", () => {
  it("splits a combination product", () => {
    expect(activeIngredients("sacubitril and valsartan")).toEqual(["sacubitril", "valsartan"]);
    expect(activeIngredients("a, b AND c")).toEqual(["a", "b", "c"]);
  });

  it("keeps a salt name in one piece", () => {
    expect(activeIngredients("metoprolol succinate")).toEqual(["metoprolol succinate"]);
    expect(activeIngredients("candesartan")).toEqual(["candesartan"]);
  });
});

describe("documentsUrl", () => {
  it("sends the page and page size", () => {
    expect(documentsUrl({ q: "", page: 2, pageSize: 20 })).toBe(
      "/api/v1/documents?page=2&page_size=20",
    );
  });

  it("adds the trimmed, encoded search term", () => {
    expect(documentsUrl({ q: " a&b ", page: 1, pageSize: 10 })).toBe(
      "/api/v1/documents?page=1&page_size=10&q=a%26b",
    );
  });
});

describe("thumbnailUrl", () => {
  it("encodes the ID", () => {
    expect(thumbnailUrl("a/b")).toBe("/api/v1/documents/a%2Fb/thumbnail?v=2");
  });
});

describe("downloadUrl", () => {
  it("asks the file route for an attachment", () => {
    expect(downloadUrl("a/b")).toBe("/api/v1/documents/a%2Fb/file?download=1");
  });
});
