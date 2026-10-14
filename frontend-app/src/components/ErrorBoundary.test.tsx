import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

let explode = true;
function Bomb() { if (explode) throw new Error("kaboom"); return <p>fine now</p>; }

describe("ErrorBoundary", () => {
  it("shows the error instead of a blank page and recovers on Try again", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary label="Test page"><Bomb /></ErrorBoundary>);
    expect(screen.getByRole("alert").textContent).toMatch(/Test page hit a problem[\s\S]*kaboom/);
    explode = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("fine now")).toBeTruthy();
  });
});
