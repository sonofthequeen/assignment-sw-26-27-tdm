import { describe, expect, it } from "vitest";
import { formatDistance, formatLapTime, formatPenalty, humanize, withUnit } from "../utils/format";

describe("formatting keeps stored units and exact values", () => {
  it("formats milliseconds as m:ss.mmm without rounding", () => {
    expect(formatLapTime(62450)).toBe("1:02.450");
    expect(formatLapTime(5390)).toBe("0:05.390");
    expect(formatLapTime(3_600_001)).toBe("60:00.001");
    expect(formatLapTime(null)).toBe("—");
  });

  it("formats penalties and decimal-string distances exactly", () => {
    expect(formatPenalty(2000)).toBe("+2.000 s");
    expect(formatPenalty(0)).toBe("—");
    expect(formatDistance("8050.000")).toBe("8\u202f050.000 m");
    expect(formatDistance("28100.696")).toBe("28\u202f100.696 m");
    expect(formatDistance("56.549")).toBe("56.549 m");
  });

  it("labels values and units without inventing missing ones", () => {
    expect(withUnit("34.5", "°C")).toBe("34.5 °C");
    expect(withUnit(null, "°C")).toBe("—");
    expect(humanize("IN_LAP")).toBe("In lap");
  });
});
