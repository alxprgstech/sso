import { Component, type ReactNode } from "react";
import { captureContractFailure } from "../telemetry/sentry";

export class ErrorBoundary extends Component<{
  children: ReactNode;
  fallback: ReactNode;
  onError?: () => void;
}, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() {
    // Never forward component values or exception text to the optional SDK.
    captureContractFailure();
    this.props.onError?.();
  }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}
