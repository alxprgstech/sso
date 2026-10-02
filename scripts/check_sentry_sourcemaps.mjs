// Resolve an actual minified UI location through the exact private map.
import { createRequire } from "node:module";
import { readFileSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
const require = createRequire(resolve("frontend/package.json"));
const { TraceMap, originalPositionFor } = require("@jridgewell/trace-mapping");
const directory = resolve(process.argv[2]);
const script = readdirSync(join(directory, "assets")).find(name => /^index-.*\.js$/.test(name));
if (!script) throw new Error("Missing main bundle");
const code = readFileSync(join(directory, "assets", script), "utf8");
const target = "Не удалось отобразить страницу.";
const offset = code.indexOf(target);
if (offset < 0) throw new Error("Missing UI location");
const lines = code.slice(0, offset).split("\n");
const map = new TraceMap(JSON.parse(readFileSync(join(directory, "assets", script + ".map"), "utf8")));
const original = originalPositionFor(map, { line: lines.length, column: lines.at(-1).length });
if (!original.source?.endsWith("/src/main.tsx") || !original.line || original.line < 1) {
  throw new Error("Minified UI location does not resolve to original TSX");
}
console.log("Private Debug ID map resolves the minified UI location to src/main.tsx");
