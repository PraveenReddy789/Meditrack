// Run with: node --test tests/js/*.test.mjs
import assert from "node:assert/strict";
import test from "node:test";

import { normalizeTime, normalizeType, parseBulk } from "../../app/static/js/bulk.js";

test("normalizes single-digit hours and rejects impossible times", () => {
  assert.equal(normalizeTime("9:30"), "09:30");
  assert.equal(normalizeTime(" 14:05 "), "14:05");
  assert.equal(normalizeTime("24:00"), null);
  assert.equal(normalizeTime("12:60"), null);
  assert.equal(normalizeTime("noon"), null);
});

test("type aliases are forgiving", () => {
  assert.equal(normalizeType("Follow up"), "follow_up");
  assert.equal(normalizeType("lab-test"), "lab_test");
});

test("parses rows, defaults the type and keeps source line numbers", () => {
  const text = "# morning list\nAsha Rao, 9:30\n\nBen Cole, 10:00, Follow-up\n";
  const { rows, lines, errors } = parseBulk(text, "2026-11-03");
  assert.deepEqual(errors, []);
  assert.deepEqual(lines, [2, 4]);
  assert.deepEqual(rows[0], {
    patient_name: "Asha Rao", appointment_date: "2026-11-03", appointment_time: "09:30", appointment_type: "checkup",
  });
  assert.equal(rows[1].appointment_type, "follow_up");
});

test("reports each bad line with its number and keeps the good ones", () => {
  const { rows, errors } = parseBulk("Only a name\nAsha Rao, 25:00\nBen Cole, 10:00, surgery\nCara Dey, 11:00", "2026-11-03");
  assert.equal(rows.length, 1);
  assert.deepEqual(errors.map((e) => e.line), [1, 2, 3]);
  assert.match(errors[1].message, /not a valid time/);
  assert.match(errors[2].message, /Unknown type/);
});

test("accepts tab-separated input pasted from a spreadsheet", () => {
  const { rows, errors } = parseBulk("Asha Rao\t09:30\tspecialist", "2026-11-03");
  assert.equal(errors.length, 0);
  assert.equal(rows[0].appointment_type, "specialist");
});
