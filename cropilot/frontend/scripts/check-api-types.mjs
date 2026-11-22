// npm run api:check: fails if src/api/schema.d.ts is not what openapi.yml generates.
// openapi.yml is checked from the Python side (core/test_api.py), so together they catch a stale schema.

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const committedPath = join(root, "src", "api", "schema.d.ts");

const pkgDir = join(root, "node_modules", "openapi-typescript");
const pkg = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
const bin = join(pkgDir, typeof pkg.bin === "string" ? pkg.bin : pkg.bin["openapi-typescript"]);

const tmp = mkdtempSync(join(tmpdir(), "api-types-"));
try {
  const freshPath = join(tmp, "schema.d.ts");
  execFileSync(process.execPath, [bin, join(root, "openapi.yml"), "-o", freshPath], { stdio: "pipe" });
  const normalise = (text) => text.replace(/\r\n/g, "\n");
  const fresh = normalise(readFileSync(freshPath, "utf8"));
  let committed = "";
  try {
    committed = normalise(readFileSync(committedPath, "utf8"));
  } catch {
    // missing: reported below
  }
  if (fresh !== committed) {
    console.error("src/api/schema.d.ts is stale or missing. Run: npm run api:types (and commit it).");
    process.exit(1);
  }
  console.log("src/api/schema.d.ts matches openapi.yml.");
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
