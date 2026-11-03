// Pure parser for the "paste a day's appointments" box. No DOM access, so it is unit-tested with node.
//
// Each non-empty line:  Patient name, HH:MM [, type]
// Lines starting with # are ignored. Type defaults to "checkup".

export const TYPES = ["checkup", "follow_up", "specialist", "vaccination", "lab_test"];

export function normalizeType(raw) {
  return raw.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

export function normalizeTime(raw) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(raw.trim());
  if (!m) return null;
  const [h, min] = [Number(m[1]), Number(m[2])];
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, "0")}:${m[2]}`;
}

/**
 * @returns {{rows: object[], lines: number[], errors: {line: number, message: string}[]}}
 *   `lines[i]` is the 1-based source line of rows[i], so server errors can point at the right line.
 */
export function parseBulk(text, date) {
  const rows = [];
  const lines = [];
  const errors = [];
  text.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1;
    const trimmed = raw.trim();
    if (!trimmed || trimmed.startsWith("#")) return;

    const parts = trimmed.split(/[,\t]/).map((p) => p.trim());
    if (parts.length < 2 || !parts[0]) {
      errors.push({ line, message: "Expected: name, time (HH:MM), optional type" });
      return;
    }
    const time = normalizeTime(parts[1]);
    if (!time) {
      errors.push({ line, message: `"${parts[1]}" is not a valid time (use HH:MM, e.g. 09:30)` });
      return;
    }
    const type = parts[2] ? normalizeType(parts[2]) : "checkup";
    if (!TYPES.includes(type)) {
      errors.push({ line, message: `Unknown type "${parts[2]}". Use: ${TYPES.join(", ")}` });
      return;
    }
    rows.push({ patient_name: parts[0], appointment_date: date, appointment_time: time, appointment_type: type });
    lines.push(line);
  });
  return { rows, lines, errors };
}
