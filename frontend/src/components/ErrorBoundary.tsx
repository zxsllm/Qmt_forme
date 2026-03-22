import { Component, type ReactNode } from 'react';
import { Alert } from 'antd';

interface Props {
  children: ReactNode;
  fallbackMsg?: string;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <Alert
          type="error"
          message={this.props.fallbackMsg || '组件渲染出错'}
          description={this.state.error.message}
          showIcon
          style={{ margin: 8 }}
        />
      );
    }
    return this.props.children;
  }
}
