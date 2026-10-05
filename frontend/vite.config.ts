import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { sentryVitePlugin } from "@sentry/bundler-plugins/vite";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const version = readFileSync(new URL("../VERSION", import.meta.url), "utf8").trim();
const sha = process.env.ALX_BUILD_SHA || execFileSync("git", ["rev-parse", "HEAD"], { cwd: root, encoding: "utf8" }).trim();
if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error("Invalid build revision");
const identity = { version, commit_sha: sha, release: `alxprgs-sso@${version}+${sha}` };
const releaseBuild = process.env.ALX_RELEASE_BUILD === "1";
const require = createRequire(import.meta.url);

const backendTarget = process.env.VITE_BACKEND_TARGET || "http://localhost:8000";

// https://vitejs.dev/config/
export default defineConfig({
  define: { __BUILD_IDENTITY__: JSON.stringify(identity) },
  plugins: [react(), tailwindcss(), ...(releaseBuild ? [sentryVitePlugin({
    org: "offline", project: "alxprgs-sso-frontend", telemetry: false, debug: false,
    sourcemaps: { disable: "disable-upload" },
    release: { name: identity.release, create: false, finalize: false },
  })] : []), {
    name: "local-replay-worker",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url !== "/sentry-replay-worker.js") return next();
        response.setHeader("Content-Type", "text/javascript");
        response.end(readFileSync(new URL("./src/telemetry/replay-worker-prefix.js", import.meta.url), "utf8") + "\n" + readFileSync(require.resolve("@sentry/replay/worker-bundler"), "utf8"));
      });
    },
    closeBundle() {
      const prefix = readFileSync(new URL("./src/telemetry/replay-worker-prefix.js", import.meta.url), "utf8");
      const worker = readFileSync(require.resolve("@sentry/replay/worker-bundler"), "utf8");
      writeFileSync(new URL("./dist/sentry-replay-worker.js", import.meta.url), prefix + "\n" + worker);
      writeFileSync(new URL("./dist/build-info.json", import.meta.url), JSON.stringify(identity));
      if (releaseBuild) {
        // Vite 8's final entry map serialization drops plugin-added metadata.
        // Restore only the ID injected into this exact JS; mappings/code are unchanged.
        const assets = new URL("./dist/assets/", import.meta.url);
        for (const file of readdirSync(assets).filter(name => name.endsWith(".js"))) {
          const id = readFileSync(new URL(file, assets), "utf8").match(/\/\/# debugId=([a-f0-9-]{36})/)?.[1];
          if (!id) throw new Error("Missing injected Debug ID");
          const mapPath = new URL(file + ".map", assets);
          const map = JSON.parse(readFileSync(mapPath, "utf8"));
          if (map.debug_id && map.debug_id !== id) throw new Error("Debug ID mismatch");
          map.debug_id = id; map.debugId = id;
          writeFileSync(mapPath, JSON.stringify(map));
        }
      }
    },
  }],
  build: { sourcemap: releaseBuild ? "hidden" : false },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/oauth": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/.well-known": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5173,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/oauth": {
        target: backendTarget,
        changeOrigin: true,
      },
      "/.well-known": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
});
