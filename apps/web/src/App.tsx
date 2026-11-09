import { useEffect, useState } from 'react'

type View = 'dashboard' | 'connection' | 'history' | 'draft' | 'monitoring'
type ViewState = 'unauthenticated' | 'loading' | 'empty' | 'error' | 'rate-limited' | 'insufficient-evidence'
type ApiHealth = { status: string }

const pages: { id: View; label: string; description: string }[] = [
  { id: 'dashboard', label: 'Intelligence', description: 'Your creator intelligence report will appear here after you connect an authorized data source.' },
  { id: 'connection', label: 'Connections', description: 'Connect an approved account or import your own history when those services are available.' },
  { id: 'history', label: 'Your history', description: 'Understand patterns in your own posts, supported by observed evidence.' },
  { id: 'draft', label: 'Analyze a draft', description: 'Compare a draft with your own history without promising future reach.' },
  { id: 'monitoring', label: 'Post monitoring', description: 'Review real observations and postmortems after a post has been linked.' },
]

const stateMessages: Record<ViewState, { title: string; body: string }> = {
  unauthenticated: { title: 'Sign-in required', body: 'A private session is required to access creator data. Authentication is not connected in this interface yet.' },
  loading: { title: 'Loading creator data', body: 'Please wait while the requested information is retrieved.' },
  empty: { title: 'No creator data yet', body: 'There are no authorized records to display. Once your history is imported, insights can appear here.' },
  error: { title: 'Something went wrong', body: 'We could not load this information. Your existing data has not been changed.' },
  'rate-limited': { title: 'Request limit reached', body: 'The data provider is temporarily limiting requests. Try again later; no additional requests will be made automatically.' },
  'insufficient-evidence': { title: 'Not enough evidence', body: 'There are not enough comparable observations to make a responsible recommendation.' },
}

function routeFromPath(): View {
  const segment = window.location.pathname.replace(/^\/+|\/+$/g, '')
  return pages.find((page) => page.id === segment)?.id ?? 'dashboard'
}

function useView() {
  const [view, setView] = useState<View>(routeFromPath)
  useEffect(() => {
    const onPopState = () => setView(routeFromPath())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])
  const navigate = (next: View) => {
    if (next !== view) window.history.pushState(null, '', next === 'dashboard' ? '/' : `/${next}`)
    setView(next)
    document.getElementById('page-title')?.focus()
  }
  return { view, navigate }
}

export function StateNotice({ state }: { state: ViewState }) {
  const message = stateMessages[state]
  return (
    <section className="state-notice" role={state === 'error' || state === 'rate-limited' ? 'alert' : 'status'} aria-live="polite">
      <span className="state-symbol" aria-hidden="true">{state === 'loading' ? '◌' : '◇'}</span>
      <div>
        <h2>{message.title}</h2>
        <p>{message.body}</p>
      </div>
    </section>
  )
}

export function App() {
  const { view, navigate } = useView()
  const [health, setHealth] = useState<'checking' | 'connected' | 'unavailable'>('checking')
  const [showStates, setShowStates] = useState(false)
  const [previewState, setPreviewState] = useState<ViewState>('unauthenticated')
  const page = pages.find((item) => item.id === view) ?? pages[0]

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('API unavailable')
        return (await response.json()) as ApiHealth
      })
      .then((data) => setHealth(data.status === 'ok' ? 'connected' : 'unavailable'))
      .catch(() => { if (!controller.signal.aborted) setHealth('unavailable') })
    return () => controller.abort()
  }, [])

  return (
    <div className="app-layout">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark" aria-hidden="true">b.</span><span>BipMe<small>Creator intelligence</small></span></div>
        <nav aria-label="Product pages">
          {pages.map((item) => (
            <a key={item.id} href={item.id === 'dashboard' ? '/' : `/${item.id}`}
              aria-current={view === item.id ? 'page' : undefined}
              onClick={(event) => { if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { event.preventDefault(); navigate(item.id) } }}>
              {item.label}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot"><span className="dot" /> API: {health === 'checking' ? 'Checking' : health === 'connected' ? 'Connected' : 'Unavailable'}<small>API health does not indicate sign-in.</small></div>
      </aside>
      <div className="content-wrap">
        <header className="topbar"><span>Private workspace</span><span className="environment-tag">Development · No live creator data</span></header>
        <main id="main-content" className="main-content">
          <p className="eyebrow">BipMe / {page.label}</p>
          <h1 id="page-title" tabIndex={-1}>{page.label}</h1>
          <p className="intro">{page.description}</p>
          <div className="feature-grid">
            <section className="feature-card">
              <div className="card-label">Product readiness</div>
              <h2>Built for evidence, not guesswork.</h2>
              <p>This screen is a navigation and state-handling foundation. It does not show invented creator metrics or claim a live connection.</p>
            </section>
            <section className="feature-card muted-card">
              <div className="card-label">Data access</div>
              <StateNotice state="unauthenticated" />
            </section>
          </div>
          <section className="preview-panel" aria-labelledby="preview-title">
            <div className="preview-heading"><div><p className="eyebrow">Development tools</p><h2 id="preview-title">Reusable interface states</h2></div><button type="button" className="secondary-button" aria-expanded={showStates} onClick={() => setShowStates((value) => !value)}>{showStates ? 'Hide preview' : 'Preview states'}</button></div>
            {showStates && <div className="preview-body"><label htmlFor="preview-state">State to preview (synthetic UI only)</label><select id="preview-state" value={previewState} onChange={(event) => setPreviewState(event.target.value as ViewState)}>{Object.keys(stateMessages).map((key) => <option key={key} value={key}>{key.replaceAll('-', ' ')}</option>)}</select><StateNotice state={previewState} /></div>}
          </section>
        </main>
      </div>
    </div>
  )
}
