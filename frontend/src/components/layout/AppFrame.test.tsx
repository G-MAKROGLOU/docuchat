import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppFrame } from "./AppFrame";

const push = vi.fn<(path: string) => void>();

vi.mock("next/navigation", () => ({
  usePathname: () => "/documents",
  useRouter: () => ({ push }),
}));

describe("AppFrame", () => {
  beforeEach(() => {
    // jsdom has no matchMedia; AppShell uses it for the mobile breakpoint.
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.classList.remove("dark");
  });

  it("renders the page inside the shell with the app name", () => {
    render(
      <AppFrame>
        <p>page content</p>
      </AppFrame>,
    );
    expect(screen.getByText("page content")).toBeTruthy();
    expect(screen.getByText("Pfizer DocuChat")).toBeTruthy();
  });

  it("links the sidebar items to their pages and marks the current one", () => {
    render(<AppFrame>content</AppFrame>);
    for (const [label, path] of [
      ["Chat", "/"],
      ["Documents", "/documents"],
      ["Corpus", "/corpus"],
      ["Status", "/status"],
      ["Health", "/health"],
      ["Settings", "/settings"],
    ]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(push).toHaveBeenLastCalledWith(path);
    }
    // The sidebar marks the active item with the accent class only (@geomak/ui 7.21.0).
    expect(screen.getByRole("button", { name: "Documents" }).className).toContain("text-accent");
    expect(screen.getByRole("button", { name: "Status" }).className).not.toContain("text-accent");
  });

  it("sets the dark class on the root element when the theme switch is on", () => {
    render(<AppFrame>content</AppFrame>);
    fireEvent.click(screen.getByRole("switch"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
