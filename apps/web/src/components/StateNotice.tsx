export type ViewState =
  | 'loading'
  | 'unauthenticated'
  | 'error'
  | 'empty'
  | 'rate-limited'
  | 'insufficient-evidence'

export const stateMessages: Record<
  ViewState,
  { title: string; body: string; symbol: string }
> = {
  loading: {
    title: 'Loading your workspace',
    body: 'Please wait while the requested information is retrieved.',
    symbol: '◌',
  },
  unauthenticated: {
    title: 'Sign-in required',
    body: 'A private BipMe session is required to access creator data. This interface does not provide sign-in.',
    symbol: '↗',
  },
  error: {
    title: 'We could not load this information',
    body: 'The request failed. Your existing data has not been changed.',
    symbol: '!',
  },
  empty: {
    title: 'This view is not available yet',
    body: 'This navigation shell does not load creator records, metrics or recommendations.',
    symbol: '○',
  },
  'rate-limited': {
    title: 'Request limit reached',
    body: 'The data provider is temporarily limiting requests. Try again later; no automatic retry will be made.',
    symbol: '↻',
  },
  'insufficient-evidence': {
    title: 'Not enough evidence',
    body: 'There are not enough eligible comparable observations to support a responsible recommendation.',
    symbol: '?',
  },
}

export function StateNotice({
  state,
  title,
  body,
}: {
  state: ViewState
  title?: string
  body?: string
}) {
  const message = stateMessages[state]
  const alert = state === 'error' || state === 'rate-limited'

  return (
    <section
      className={`state-notice state-notice--${state}`}
      role={alert ? 'alert' : 'status'}
      aria-live={alert ? 'assertive' : 'polite'}
    >
      <span className="state-symbol" aria-hidden="true">
        {message.symbol}
      </span>
      <div className="state-copy">
        <h2>{title ?? message.title}</h2>
        <p>{body ?? message.body}</p>
      </div>
    </section>
  )
}
