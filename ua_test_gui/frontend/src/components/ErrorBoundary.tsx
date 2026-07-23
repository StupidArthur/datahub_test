// 错误边界:捕获子组件渲染错误,显示详情便于排查白屏。
import React, { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  info: React.ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error, info: null };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ error, info });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-4 text-sm text-destructive flex flex-col gap-2">
          <div className="font-bold">页面渲染出错</div>
          <pre className="bg-muted p-2 rounded overflow-auto whitespace-pre-wrap">
            {this.state.error.toString()}
            {"\n"}
            {this.state.info?.componentStack || ""}
          </pre>
        </div>
      );
    }
    return this.props.children;
  }
}
