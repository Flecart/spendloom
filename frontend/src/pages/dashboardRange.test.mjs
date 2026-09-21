import assert from "node:assert/strict";
import test from "node:test";
import { rangeError, readSavedRange } from "./dashboardRange.ts";

test("an inverted date range can be corrected", () => {
  const range = { preset: "custom", date_from: "2026-09-22", date_to: "2026-09-21", scope: "" };
  assert.equal(rangeError(range), "From must be on or before To.");
  assert.equal(rangeError({ ...range, date_to: "2026-09-22" }), "");
  assert.equal(rangeError({ ...range, date_from: "" }), "Select both dates.");
});

test("an invalid saved range resets on reload", () => {
  const previousStorage = globalThis.localStorage;
  globalThis.localStorage = {
    getItem: () => JSON.stringify({ preset: "custom", date_from: "2026-09-22", date_to: "2026-09-21" }),
  };
  try {
    const restored = readSavedRange();
    assert.equal(restored.preset, "12m");
    assert.equal(rangeError(restored), "");
  } finally {
    globalThis.localStorage = previousStorage;
  }
});
