import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { type Citations, renderMarkdown } from "./Markdown";

function html(text: string, citations?: Citations): string {
  // The wrapper class comes from a CSS module, so only its content is compared.
  return (
    render(<>{renderMarkdown(text, citations)}</>).container.firstElementChild?.innerHTML ?? ""
  );
}

describe("renderMarkdown", () => {
  it("renders paragraphs with line breaks and inline styles", () => {
    expect(html("**Bold** and *italic* with `code`\nnext line\n\nSecond")).toBe(
      "<p><span><strong>Bold</strong> and <em>italic</em> with <code>code</code></span>" +
        "<span><br>next line</span></p><p><span>Second</span></p>",
    );
  });

  it("renders headings as bold paragraphs", () => {
    expect(html("## Adults")).toBe("<p><strong>Adults</strong></p>");
  });

  it("renders nested and ordered lists", () => {
    expect(html("- One\n  - One a\n- Two\n\n1. First\n2. Second")).toBe(
      "<ul><li>One<ul><li>One a</li></ul></li><li>Two</li></ul>" +
        "<ol><li>First</li><li>Second</li></ol>",
    );
  });

  it("keeps the items of a list that starts indented", () => {
    expect(html("  - a\n- b")).toBe("<ul><li>a</li><li>b</li></ul>");
  });

  it("keeps HTML in the text as text", () => {
    expect(html("<img src=x onerror=alert(1)>")).toBe(
      "<p><span>&lt;img src=x onerror=alert(1)&gt;</span></p>",
    );
  });

  it("keeps citations and unmatched markers as text", () => {
    expect(html("10 mg [S1]. 2 * 3 = 6")).toBe("<p><span>10 mg [S1]. 2 * 3 = 6</span></p>");
  });

  it("makes the citations that have an action into buttons", () => {
    const open = vi.fn<() => void>();
    const text = "Dose [S1] and [S2].\n- **Max** [S1]";
    const { getAllByRole } = render(<>{renderMarkdown(text, { S1: open })}</>);

    const buttons = getAllByRole("button", { name: "Open source S1" });
    expect(buttons).toHaveLength(2);
    expect(html("Dose [S2].", { S1: open })).toBe("<p><span>Dose [S2].</span></p>");
    buttons[1]?.click();
    expect(open).toHaveBeenCalledOnce();
  });
});
