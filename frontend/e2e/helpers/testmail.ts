import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
export type MailboxContext = {
  mailbox: { namespace: string; tag: string };
  address: string;
  checkpoint: { timestamp_ms: number; seen_ids: string[] };
};
type Verification = { code: string; link: string; message_id: string };

function bridge<T>(command: string, payload: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.PYTHON_BIN || "python", ["-m", "tests.helpers.testmail_cli", command], {
      cwd: root, shell: false, stdio: ["pipe", "pipe", "pipe"],
    });
    let output = "";
    let diagnostic = "";
    let bridgeTimedOut = false;
    const configured = Number(process.env.TESTMAIL_TIMEOUT_SECONDS || "120");
    const timeout = Number.isFinite(configured) ? Math.min(150_000, configured * 1000 + 15_000) : 135_000;
    const timer = setTimeout(() => { bridgeTimedOut = true; child.kill(); }, timeout);
    child.stdout.on("data", (data: Buffer) => {
      output += data.toString("utf8");
      if (output.length > 16_384) child.kill();
    });
    // Convert private stderr to a fixed category; never forward its text.
    child.stderr.on("data", (data: Buffer) => {
      diagnostic = (diagnostic + data.toString("utf8")).slice(0, 4096);
    });
    child.once("error", () => { clearTimeout(timer); reject(new Error("Email helper could not start")); });
    child.once("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        const category = bridgeTimedOut || /Timed out/.test(diagnostic) ? "timeout"
          : /authentication|namespace access/.test(diagnostic) ? "authentication"
          : /GraphQL|malformed/.test(diagnostic) ? "contract"
          : /OTP/.test(diagnostic) ? "otp"
          : /URL/.test(diagnostic) ? "link"
          : /Verification/.test(diagnostic) ? "content"
          : /required|configuration/.test(diagnostic) ? "configuration" : "helper";
        return reject(new Error(`Email helper failed (${category})`));
      }
      try { resolve(JSON.parse(output) as T); }
      catch { reject(new Error("Email helper returned invalid JSON (payload withheld)")); }
    });
    child.stdin.on("error", () => { /* close handler reports failure without leaking payload */ });
    child.stdin.end(JSON.stringify(payload));
  });
}

export function createMailbox(context: string): Promise<MailboxContext> {
  return bridge("address", { context });
}

export function waitForVerification(context: MailboxContext, username: string): Promise<Verification> {
  return bridge("wait", { ...context, username, mode: "registration" });
}
