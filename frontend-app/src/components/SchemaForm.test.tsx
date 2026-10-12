import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import type { Field, Values } from "../types";
import { SchemaForm, defaultValues } from "./SchemaForm";

function Harness({ fields, initial = {}, onValues }: { fields: Field[]; initial?: Values; onValues?: (v: Values) => void }) {
  const [values, setValues] = useState<Values>({ ...defaultValues(fields), ...initial });
  return <SchemaForm fields={fields} values={values} objectClasses={["person", "car"]}
    onChange={(v) => { setValues(v); onValues?.(v); }} />;
}
const f = (over: Partial<Field> & Pick<Field, "name" | "type">): Field => ({ label: over.name, help: "", required: false, ...over });

describe("SchemaForm", () => {
  it("builds a form for a never-seen plugin from its schema alone", () => {
    const fields = [
      f({ name: "level", type: "number", label: "Spike level", min: 0, max: 10, unit: "units", widget: "slider", help: "How big." }),
      f({ name: "armed", type: "boolean", label: "Armed", default: true }),
      f({ name: "mode", type: "enum", label: "Mode", enum: [{ value: "a", label: "Alpha" }, { value: "b", label: "Beta" }], default: "a" }),
    ];
    render(<Harness fields={fields} />);
    expect(screen.getByLabelText("Spike level")).toHaveProperty("type", "range");
    expect(screen.getByText("How big.")).toBeTruthy();
    expect(screen.getByRole("switch")).toHaveProperty("checked", true);
    expect(screen.getByRole("option", { name: "Beta" })).toBeTruthy();
  });

  it("never shows raw JSON: lists are chips, objects are key/value rows", () => {
    const seen: Values[] = [];
    render(<Harness fields={[f({ name: "classes", type: "string_list", label: "Objects", widget: "class_picker", default: ["person"] })]}
      onValues={(v) => seen.push(v)} />);
    expect(screen.getByText("person")).toBeTruthy();
    const input = screen.getByLabelText("Objects");
    fireEvent.change(input, { target: { value: "car" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(seen.at(-1)).toEqual({ classes: ["person", "car"] });
    fireEvent.click(screen.getByLabelText("Remove person"));
    expect(seen.at(-1)).toEqual({ classes: ["car"] });
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("writes typed values (numbers, not strings) and shows server errors by field", () => {
    const seen: Values[] = [];
    const fields = [f({ name: "n", type: "integer", label: "Count", default: 1 })];
    const { rerender } = render(<Harness fields={fields} onValues={(v) => seen.push(v)} />);
    fireEvent.change(screen.getByLabelText("Count"), { target: { value: "7" } });
    expect(seen.at(-1)).toEqual({ n: 7 });
    rerender(<SchemaForm fields={fields} values={{ n: 7 }} onChange={() => undefined}
      errors={[{ field: "n", message: "Count must be at most 5" }]} />);
    expect(screen.getByRole("alert").textContent).toBe("Count must be at most 5");
  });

  it("places a line on the canvas instead of asking for coordinates", () => {
    const seen: Values[] = [];
    render(<Harness fields={[f({ name: "line", type: "points", label: "Line", widget: "line_draw" })]} onValues={(v) => seen.push(v)} />);
    const surface = screen.getByRole("img", { name: "Click to place points" });
    surface.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.click(surface, { clientX: 25, clientY: 50 });
    fireEvent.click(surface, { clientX: 75, clientY: 50 });
    expect(seen.at(-1)).toEqual({ line: [[0.25, 0.5], [0.75, 0.5]] });
  });
});
