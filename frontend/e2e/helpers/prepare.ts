import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

/** Fresh synthetic fixtures at a case boundary; live limits remain enabled. */
export function prepareIndependentScenario(): void {
  const python = process.env.PYTHON_BIN;
  if (!python || !process.env.TEST_DATABASE_URL) {
    throw new Error("Installed Python and guarded test database are required");
  }
  const seed = fileURLToPath(new URL("../../../scripts/prepare_e2e_data.py", import.meta.url));
  execFileSync(python, [seed, "--reset-rate-limits"], { env: process.env, stdio: "inherit" });
}
