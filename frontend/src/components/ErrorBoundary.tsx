import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error in Dashboard:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-[#080c14] text-slate-100 flex flex-col items-center justify-center p-6 font-mono">
          <div className="bg-[#0d131f] border border-red-500/30 rounded-xl p-6 max-w-lg w-full shadow-2xl text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center mx-auto">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <h2 className="text-lg font-bold text-slate-100">Terminal Render Exception Caught</h2>
            <p className="text-xs text-slate-400 leading-relaxed">
              {this.state.error?.message || "An unexpected error occurred while rendering trading chart components."}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.reload();
              }}
              className="inline-flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-black font-bold rounded-lg text-xs transition-colors"
            >
              <RefreshCw className="w-4 h-4" /> Reload Terminal
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
