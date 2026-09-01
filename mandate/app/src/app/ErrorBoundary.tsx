import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  area: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  message: string | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { message: null };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { message: error instanceof Error ? error.message : "Unknown failure" };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`MANDATE ${this.props.area} failed`, error, info.componentStack);
  }

  render() {
    if (this.state.message === null) return this.props.children;
    return (
      <section className="mandate-chrome surface-failure" role="alert">
        <b>{this.props.area} could not be rendered</b>
        <p>
          This panel failed, and the console is showing you the failure rather than a blank
          screen. Nothing was sent to the broker. Reload to try again.
        </p>
        <code>{this.state.message}</code>
        <button type="button" className="text-button" onClick={() => location.reload()}>
          Reload the console
        </button>
      </section>
    );
  }
}
