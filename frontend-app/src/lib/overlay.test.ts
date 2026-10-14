import { describe, expect, it } from "vitest";
import { boxLabel, boxStyle, boxTone, countsText } from "./overlay";

describe("overlay labels", () => {
  const person = { class: "person", conf: 0.614, bbox: [0.1, 0.2, 0.3, 0.6] as [number, number, number, number] };
  it("words the box like the old dashboard", () => {
    expect(boxLabel(person)).toBe("person 61%");
    expect(boxLabel({ ...person, name: "Asha" })).toBe("Asha 61%");
    expect(boxLabel({ ...person, class: "hand", gesture: "wave" })).toBe("wave 61%");
    expect(boxTone(person)).toBe("person");
    expect(countsText({ person: 2, car: 1 })).toBe("person: 2 · car: 1");
    expect(countsText(undefined)).toBe("");
  });
  it("positions in percent and clamps to the picture", () => {
    const s = boxStyle({ ...person, bbox: [-0.1, 0.2, 1.4, 0.6] });
    expect(s.left).toBe("0%"); expect(parseFloat(s.width)).toBeCloseTo(100); expect(parseFloat(s.top)).toBeCloseTo(20);
  });
});
