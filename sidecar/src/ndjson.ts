/**
 * NDJSON serialization utilities for the Aura sidecar.
 *
 * Matches the Python protocol module's ndjson.py — same U+2028/U+2029
 * escaping ensures both sides of the UDS bridge produce identical output.
 */

const JS_LINE_TERMINATORS = /\u2028|\u2029/g;

function escapeJsLineTerminators(json: string): string {
  return json.replace(JS_LINE_TERMINATORS, (c) =>
    c === "\u2028" ? "\\u2028" : "\\u2029"
  );
}

export function ndjsonSerialize(value: unknown): string {
  return escapeJsLineTerminators(JSON.stringify(value));
}

export function ndjsonParse(line: string): unknown | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}
