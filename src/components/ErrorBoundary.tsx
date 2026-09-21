import { Component, type ReactNode } from "react";
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <div className="connect-page">
          <h1>页面暂时无法显示</h1>
          <p>请重新载入应用，已保存的本地数据不受影响。</p>
          <button className="button primary" onClick={() => location.reload()}>
            重新载入
          </button>
        </div>
      );
    return this.props.children;
  }
}

