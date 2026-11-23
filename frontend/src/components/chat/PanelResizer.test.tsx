import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MAX_PERCENT, MIN_PERCENT, PanelResizer, rightPercent } from "./PanelResizer";

describe("rightPercent", () => {
  const layout = { left: 100, width: 1000 };

  it("gives the share of the layout right of the handle", () => {
    expect(rightPercent(700, layout)).toBe(40);
  });

  it("keeps both panels usable", () => {
    expect(rightPercent(1090, layout)).toBe(MIN_PERCENT);
    expect(rightPercent(110, layout)).toBe(MAX_PERCENT);
  });
});

describe("PanelResizer", () => {
  it("resizes with the arrow keys within the limits", () => {
    const onChange = vi.fn<(percent: number) => void>();
    const { rerender } = render(<PanelResizer percent={50} onChange={onChange} label="Resize" />);
    const handle = screen.getByRole("separator", { name: "Resize" });

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    fireEvent.keyDown(handle, { key: "Enter" });
    fireEvent.keyDown(handle, { key: "Home" });
    fireEvent.keyDown(handle, { key: "End" });
    expect(onChange.mock.calls).toEqual([[55], [45], [MIN_PERCENT], [MAX_PERCENT]]);

    rerender(<PanelResizer percent={MAX_PERCENT} onChange={onChange} label="Resize" />);
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith(MAX_PERCENT);
  });

  it("tells assistive technology the width and its limits", () => {
    render(<PanelResizer percent={40} onChange={() => undefined} label="Resize" />);
    const handle = screen.getByRole("separator", { name: "Resize" });

    expect(handle.getAttribute("aria-valuenow")).toBe("40");
    expect(handle.getAttribute("aria-valuemin")).toBe(String(MIN_PERCENT));
    expect(handle.getAttribute("aria-valuemax")).toBe(String(MAX_PERCENT));
    expect(handle.getAttribute("aria-orientation")).toBe("vertical");
  });
});
