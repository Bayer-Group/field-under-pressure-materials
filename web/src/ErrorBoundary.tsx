import { Component, type ReactNode } from 'react'

/** Keeps a rendering error inside one part of the screen: that part shows a message, the rest keeps working.
 *  Give it a `key` that changes with what it shows (plot, tab), so moving elsewhere clears the error. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error(error)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="message error" role="alert">
        <p>This part of the page could not be shown: {this.state.error.message}</p>
        <button className="ghost" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    )
  }
}
