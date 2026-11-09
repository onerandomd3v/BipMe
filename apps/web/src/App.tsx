import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
} from 'react'
import { authApi, ApiResponseError } from './auth/client'
import { ConnectionsPage } from './connections/ConnectionsPage'
import {
  StateNotice,
  stateMessages,
  type ViewState,
} from './components/StateNotice'

type View = 'dashboard' | 'connections' | 'history' | 'draft' | 'monitoring'
type ApiHealth = 'checking' | 'available' | 'unavailable'
export type SessionStatus =
  'checking' | 'authenticated' | 'unauthenticated' | 'unavailable'

type Page = {
  id: View
  label: string
  path: string
  aliases: string[]
  description: string
  stateTitle: string
  stateBody: string
}

const pages: Page[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    path: '/',
    aliases: ['/dashboard'],
    description: 'Your private creator intelligence workspace.',
    stateTitle: 'Your report is not ready yet',
    stateBody:
      'A report can appear here after a private BipMe session and permitted creator evidence are available.',
  },
  {
    id: 'connections',
    label: 'Connections',
    path: '/connections',
    aliases: ['/connection'],
    description: 'Manage authorized sources for your creator history.',
    stateTitle: 'Sign-in required',
    stateBody:
      'Sign in to view your private session and manage optional data sources.',
  },
  {
    id: 'history',
    label: 'Content History',
    path: '/content-history',
    aliases: ['/history'],
    description: 'Review your permitted publishing history and its evidence.',
    stateTitle: 'Your history is not available',
    stateBody:
      'No creator records are shown in this development interface. History requires a private session and an authorized data source.',
  },
  {
    id: 'draft',
    label: 'Analyze a Draft',
    path: '/draft-analysis',
    aliases: ['/draft'],
    description:
      'Consider a draft using eligible evidence from your own history.',
    stateTitle: 'Draft analysis is not available',
    stateBody:
      'Draft guidance requires an authenticated session and eligible historical evidence. This navigation foundation does not analyze drafts.',
  },
  {
    id: 'monitoring',
    label: 'Post Monitoring',
    path: '/post-monitoring',
    aliases: ['/monitoring'],
    description: 'Review real, timestamped observations after publishing.',
    stateTitle: 'Post monitoring is not available',
    stateBody:
      'Monitoring requires an authenticated session and authorized observations. This navigation foundation does not collect post metrics.',
  },
]

const pathToView = new Map<string, View>(
  pages.flatMap((page) => [
    [page.path, page.id],
    ...page.aliases.map((alias) => [alias, page.id] as [string, View]),
  ]),
)

function routeFromPath(): View {
  return (
    pathToView.get(window.location.pathname.replace(/\/$/, '') || '/') ??
    'dashboard'
  )
}

function useView() {
  const [view, setView] = useState<View>(routeFromPath)

  useEffect(() => {
    const onPopState = () => setView(routeFromPath())
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = (next: View) => {
    const destination = pages.find((page) => page.id === next)?.path ?? '/'
    if (window.location.pathname !== destination)
      window.history.pushState(null, '', destination)
    setView(next)
  }

  return { view, navigate }
}

function DevelopmentStatePreview() {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<ViewState>('unauthenticated')

  if (!import.meta.env.DEV) return null

  return (
    <section className="state-preview" aria-labelledby="state-preview-title">
      <div className="state-preview__heading">
        <div>
          <p className="eyebrow">Development fixture</p>
          <h2 id="state-preview-title">Shared interface states</h2>
          <p className="state-preview__description">
            Preview only. These controls do not authenticate or load creator
            data.
          </p>
        </div>
        <button
          className="button button--secondary"
          type="button"
          aria-expanded={open}
          aria-controls="state-fixture"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Hide preview' : 'Preview states'}
        </button>
      </div>
      {open && (
        <div className="state-preview__body" id="state-fixture">
          <label htmlFor="state-fixture-select">State fixture</label>
          <select
            id="state-fixture-select"
            value={state}
            onChange={(event) => setState(event.target.value as ViewState)}
          >
            {Object.keys(stateMessages).map((value) => (
              <option key={value} value={value}>
                {value.replaceAll('-', ' ')}
              </option>
            ))}
          </select>
          <StateNotice state={state} />
        </div>
      )}
    </section>
  )
}

export function App() {
  const { view, navigate } = useView()
  const [health, setHealth] = useState<ApiHealth>('checking')
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('checking')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const wasDrawerOpen = useRef(false)
  const page = pages.find((item) => item.id === view) ?? pages[0]

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/health', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('API health check failed')
        return (await response.json()) as { status?: string }
      })
      .then((data) =>
        setHealth(data.status === 'ok' ? 'available' : 'unavailable'),
      )
      .catch(() => {
        if (!controller.signal.aborted) setHealth('unavailable')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    authApi
      .readSession(controller.signal)
      .then(() => setSessionStatus('authenticated'))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiResponseError && error.status === 401)
          setSessionStatus('unauthenticated')
        else setSessionStatus('unavailable')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (drawerOpen) {
      sidebarRef.current
        ?.querySelector<HTMLButtonElement>('.drawer-close')
        ?.focus()
      document.body.classList.add('drawer-is-open')
    } else {
      document.body.classList.remove('drawer-is-open')
      if (wasDrawerOpen.current) triggerRef.current?.focus()
    }
    wasDrawerOpen.current = drawerOpen
    return () => document.body.classList.remove('drawer-is-open')
  }, [drawerOpen])

  const previousView = useRef(view)
  useEffect(() => {
    document.title = `${page.label} · BipMe`
    if (previousView.current !== view)
      document.getElementById('page-title')?.focus()
    previousView.current = view
  }, [page.label, view])

  const workspaceState: ViewState =
    sessionStatus === 'checking'
      ? 'loading'
      : sessionStatus === 'unauthenticated'
        ? 'unauthenticated'
        : sessionStatus === 'unavailable'
          ? 'error'
          : 'empty'
  const sessionLabel =
    sessionStatus === 'checking'
      ? 'Checking sign-in'
      : sessionStatus === 'authenticated'
        ? 'Private session active'
        : sessionStatus === 'unauthenticated'
          ? 'Sign-in required'
          : 'Sign-in status unavailable'
  const sessionDescription =
    sessionStatus === 'checking'
      ? 'Checking the private session with the BipMe API.'
      : sessionStatus === 'authenticated'
        ? 'A private BipMe session is active in this browser.'
        : sessionStatus === 'unauthenticated'
          ? 'No private BipMe session is active in this browser.'
          : 'The BipMe API could not verify the private session.'

  const closeDrawer = () => setDrawerOpen(false)

  const openDrawer = () => {
    setDrawerOpen(true)
    window.requestAnimationFrame(() => {
      const sidebar = sidebarRef.current
      if (sidebar?.dataset.open === 'true') {
        sidebar.querySelector<HTMLButtonElement>('.drawer-close')?.focus()
      }
    })
  }

  const onDrawerKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      setDrawerOpen(false)
      triggerRef.current?.focus()
      return
    }
    if (event.key !== 'Tab') return

    const focusable = Array.from(
      sidebarRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled)',
      ) ?? [],
    ).filter((element) => element.offsetParent !== null)
    const first = focusable[0]
    const last = focusable.at(-1)
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const onNavigate = (
    event: MouseEvent<HTMLAnchorElement>,
    destination: View,
  ) => {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    )
      return
    event.preventDefault()
    navigate(destination)
    setDrawerOpen(false)
  }

  return (
    <div className="app-layout">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {drawerOpen && (
        <button
          className="drawer-backdrop"
          type="button"
          aria-label="Close navigation"
          onClick={closeDrawer}
        />
      )}

      <aside
        id="primary-navigation"
        className="sidebar"
        ref={sidebarRef}
        data-open={drawerOpen}
        role={drawerOpen ? 'dialog' : undefined}
        aria-modal={drawerOpen || undefined}
        aria-label={drawerOpen ? 'Mobile navigation' : 'Primary navigation'}
        onKeyDown={drawerOpen ? onDrawerKeyDown : undefined}
      >
        <div className="brand-row">
          <a
            className="brand"
            href="/"
            aria-label="BipMe dashboard"
            onClick={(event) => onNavigate(event, 'dashboard')}
          >
            <span className="brand-mark" aria-hidden="true">
              b,
            </span>
            <span className="brand-name">
              bip<span>me</span>
              <small>Creator intelligence</small>
            </span>
          </a>
          <button
            className="drawer-close"
            type="button"
            aria-label="Close navigation"
            onClick={closeDrawer}
          >
            ×
          </button>
        </div>

        <nav aria-label="Workspace">
          <p className="nav-heading">Workspace</p>
          {pages.map((item, index) => (
            <a
              className="nav-link"
              key={item.id}
              href={item.path}
              aria-current={view === item.id ? 'page' : undefined}
              onClick={(event) => onNavigate(event, item.id)}
            >
              <span className="nav-icon" aria-hidden="true">
                {['⌂', '↔', '▤', '✎', '◷'][index]}
              </span>
              <span>{item.label}</span>
            </a>
          ))}
        </nav>

        <div className="sidebar-status">
          <div className="session-status">
            <span
              className={`status-dot status-dot--${sessionStatus === 'authenticated' ? 'available' : sessionStatus === 'unavailable' ? 'unavailable' : sessionStatus === 'checking' ? 'checking' : 'neutral'}`}
              aria-hidden="true"
            />
            {sessionLabel}
          </div>
          <p>{sessionDescription}</p>
          <div className="sidebar-divider" />
          <div className="health-status" aria-live="polite">
            <span
              className={`status-dot status-dot--${health}`}
              aria-hidden="true"
            />
            <span>
              API health ·{' '}
              {health === 'checking'
                ? 'Checking'
                : health === 'available'
                  ? 'Available'
                  : 'Unavailable'}
            </span>
          </div>
          <p>Health status is separate from sign-in.</p>
        </div>
      </aside>

      <div className="content-wrap">
        <header className="topbar">
          <div className="topbar__start">
            <button
              ref={triggerRef}
              className="drawer-trigger"
              type="button"
              aria-label="Open navigation"
              aria-expanded={drawerOpen}
              aria-controls="primary-navigation"
              onClick={openDrawer}
            >
              <span aria-hidden="true">☰</span>
            </button>
            <span className="topbar-brand">
              <span className="topbar-brand__mark" aria-hidden="true">
                b,
              </span>{' '}
              bip<span>me</span>
            </span>
            <span className="topbar-separator" aria-hidden="true">
              /
            </span>
            <span className="topbar-context">Private workspace</span>
          </div>
          <span className="environment-tag">
            <span className="environment-tag__dot" aria-hidden="true" />
            Development · No live creator data
          </span>
        </header>

        <main id="main-content" className="main-content">
          <div className="page-heading">
            <p className="eyebrow">
              <span className="eyebrow__dot" aria-hidden="true" />
              Creator intelligence overview
            </p>
            <h1 id="page-title" tabIndex={-1}>
              {page.label}
            </h1>
            <p className="intro">{page.description}</p>
          </div>

          {view === 'connections' ? (
            <ConnectionsPage
              sessionStatus={sessionStatus}
              onSessionStatus={setSessionStatus}
            />
          ) : (
            <section
              className="workspace-card"
              aria-labelledby="workspace-card-title"
            >
              <div className="workspace-card__header">
                <div className="workspace-card__mark" aria-hidden="true">
                  i
                </div>
                <div>
                  <p className="card-kicker">Private workspace</p>
                  <h2 id="workspace-card-title">
                    Built for evidence, not guesswork.
                  </h2>
                </div>
              </div>
              <StateNotice
                state={workspaceState}
                title={
                  workspaceState === 'unauthenticated'
                    ? page.stateTitle
                    : undefined
                }
                body={
                  workspaceState === 'unauthenticated'
                    ? page.stateBody
                    : undefined
                }
              />
              <p className="workspace-card__note">
                BipMe will show observed creator data only after access and
                evidence are available.
              </p>
            </section>
          )}

          <DevelopmentStatePreview />
          <footer className="page-footer">
            BipMe <span aria-hidden="true">·</span> Private creator intelligence
          </footer>
        </main>
      </div>
    </div>
  )
}
