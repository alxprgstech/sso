import type { Reporter, TestCase, TestResult, FullResult } from "@playwright/test/reporter";
import fs from "node:fs";
import path from "node:path";

export default class EmailReporter implements Reporter {
  private cases: { case: string; outcome: string; duration_ms: number; category: string }[] = [];
  onTestEnd(test: TestCase, result: TestResult) {
    // No error text, stdout/stderr, steps, URLs, bodies or attachments.
    const allowed = ["timeout", "authentication", "contract", "otp", "link", "content", "configuration", "helper"];
    const category = allowed.find(value => result.errors.some(error =>
      error.message?.includes(`Email helper failed (${value})`))) || (result.status === "passed" ? "none" : "browser");
    this.cases.push({ case: test.title, outcome: result.status, duration_ms: result.duration, category });
    console.log(`Email browser case: ${result.status}`);
  }
  onEnd(result: FullResult) {
    const directory = path.resolve("../artifacts/email");
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, "browser-summary.json"), JSON.stringify({ outcome: result.status, cases: this.cases }));
  }
}
