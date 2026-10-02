import { replayIntegration } from "@sentry/react";

export function createReplay() {
  return replayIntegration({
    maskAllText: true, maskAllInputs: true, blockAllMedia: true,
    unmask: [], unblock: [],
    block: ["[data-sentry-block]", ".sso-sensitive"],
    maskAttributes: ["title", "aria-label", "data-value"],
    networkDetailAllowUrls: [], networkCaptureBodies: false,
    networkRequestHeaders: [], networkResponseHeaders: [],
    maxReplayDuration: 300000,
    workerUrl: "/sentry-replay-worker.js", useCompression: true,
    beforeAddRecordingEvent: () => null, // No console/network/custom payloads in v1.
  });
}
