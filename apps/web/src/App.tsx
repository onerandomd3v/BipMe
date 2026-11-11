import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type FormEvent,
} from 'react'
import { ApiRequestError, apiClient } from './api/client'
import { CreatorHistoryDashboard } from './CreatorHistoryDashboard'
import { PostMonitoring } from './PostMonitoring'
import { CreatorDashboard } from './CreatorDashboard'
import { DraftAnalysis } from './DraftAnalysis'
import type { DraftAnalysisContext } from './dashboardModel'

type View = 'dashboard' | 'connections' | 'history' | 'draft' | 'monitoring'
type ViewState =
  | 'loading'
  | 'unauthenticated'
  | 'error'
  | 'empty'
  | 'rate-limited'
  | 'insufficient-evidence'
type SessionStatus =
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
    label: 'Overview',
    path: '/',
    aliases: ['/dashboard'],
    description: 'Your creator report and next steps.',
    stateTitle: 'Your report is not ready yet',
    stateBody:
      'A report can appear here after a private BipMe session and permitted creator evidence are available.',
  },
  {
    id: 'connections',
    label: 'Connections',
    path: '/connections',
    aliases: ['/connection'],
    description: 'Manage sources for your creator history.',
    stateTitle: 'Sign-in required',
    stateBody:
      'This demo does not connect to X. The workspace uses only data already permitted for your account.',
  },
  {
    id: 'history',
    label: 'Content History',
    path: '/content-history',
    aliases: ['/history'],
    description: 'See your posts and the evidence behind them.',
    stateTitle: 'Your history is not available',
    stateBody:
      'Your history needs an authorized source. No posts can be shown until data is imported.',
  },
  {
    id: 'draft',
    label: 'Analyze a Draft',
    path: '/draft-analysis',
    aliases: ['/draft'],
    description: 'Compare a draft with your own history.',
    stateTitle: 'Draft analysis is not available',
    stateBody:
      'A saved report and enough comparable posts are needed before draft analysis is available.',
  },
  {
    id: 'monitoring',
    label: 'Post Monitoring',
    path: '/post-monitoring',
    aliases: ['/monitoring'],
    description: 'Review what happened after publishing.',
    stateTitle: 'Post monitoring is not available',
    stateBody:
      'Post monitoring appears after a draft assessment is linked to a published post.',
  },
]

const navigationPages = pages.filter((page) => page.id !== 'connections')
const pageIcons: Record<View, string> = {
  dashboard: '⌂',
  connections: '↔',
  history: '▤',
  draft: '✎',
  monitoring: '◷',
}

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
  const [locationKey, setLocationKey] = useState(
    () => `${window.location.pathname}${window.location.search}`,
  )

  useEffect(() => {
    const onPopState = () => {
      setView(routeFromPath())
      setLocationKey(`${window.location.pathname}${window.location.search}`)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  const navigate = (next: View) => {
    const destination = pages.find((page) => page.id === next)?.path ?? '/'
    if (window.location.pathname !== destination)
      window.history.pushState(null, '', destination)
    setView(next)
    setLocationKey(`${window.location.pathname}${window.location.search}`)
  }

  const navigateToMonitoring = (assessmentId: string) => {
    const destination = `/post-monitoring?assessment_id=${encodeURIComponent(assessmentId)}`
    window.history.pushState(null, '', destination)
    setView('monitoring')
    setLocationKey(destination)
  }

  return { view, navigate, navigateToMonitoring, locationKey }
}

const stateMessages: Record<
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
    body: 'Sign in to view your creator workspace.',
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

export function App() {
  const { view, navigate, navigateToMonitoring, locationKey } = useView()
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>('checking')
  const [privateSecret, setPrivateSecret] = useState('')
  const [privateLoginError, setPrivateLoginError] = useState<string | null>(
    null,
  )
  const [privateLoginPending, setPrivateLoginPending] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [draftContext, setDraftContext] = useState<DraftAnalysisContext | null>(
    null,
  )
  const triggerRef = useRef<HTMLButtonElement>(null)
  const sidebarRef = useRef<HTMLElement>(null)
  const wasDrawerOpen = useRef(false)
  const page = pages.find((item) => item.id === view) ?? pages[0]

  useEffect(() => {
    return apiClient.subscribeSessionInvalidation(() => {
      setSessionStatus('unauthenticated')
      setDraftContext(null)
    })
  }, [])

  useEffect(() => {
    if (view !== 'draft') setDraftContext(null)
  }, [view])

  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .session(controller.signal)
      .then((session) => {
        if (controller.signal.aborted) return
        setSessionStatus(
          session.authenticated ? 'authenticated' : 'unauthenticated',
        )
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiRequestError && error.status === 401) {
          setSessionStatus('unauthenticated')
          return
        }
        setSessionStatus('unavailable')
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
  const closeDrawer = () => setDrawerOpen(false)

  const signIn = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (privateLoginPending) return
    setPrivateLoginPending(true)
    setPrivateLoginError(null)
    try {
      const session = await apiClient.privateSession(privateSecret)
      setSessionStatus(
        session.authenticated ? 'authenticated' : 'unauthenticated',
      )
    } catch (error) {
      setPrivateLoginError(
        error instanceof ApiRequestError && error.status === 401
          ? 'The private sign-in secret was rejected.'
          : 'Private sign-in is unavailable. Check the API configuration and try again.',
      )
    } finally {
      setPrivateSecret('')
      setPrivateLoginPending(false)
    }
  }

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

  if (sessionStatus !== 'authenticated') {
    return (
      <main className="sign-in-screen">
        <a className="sign-in-brand" href="/" aria-label="BipMe home">
          <span className="brand-mark" aria-hidden="true">
            b,
          </span>
          <span className="brand-name">
            bip<span>me</span>
            <small>Creator intelligence</small>
          </span>
        </a>
        <section className="sign-in-card" aria-labelledby="sign-in-title">
          {sessionStatus === 'checking' ? (
            <StateNotice
              state="loading"
              title="Checking your session"
              body=""
            />
          ) : (
            <>
              <p className="card-kicker">Private creator workspace</p>
              <h1 id="sign-in-title">Welcome back</h1>
              <p className="muted-copy">
                Sign in to see your report and content history.
              </p>
              {sessionStatus === 'unavailable' && (
                <p className="form-error" role="alert">
                  BipMe could not reach the sign-in service. Check that the API
                  is running, then try again.
                </p>
              )}
              {privateLoginError && (
                <p className="form-error" role="alert">
                  {privateLoginError}
                </p>
              )}
              <form className="private-sign-in" onSubmit={signIn}>
                <label htmlFor="private-sign-in-secret">
                  Private sign-in secret
                </label>
                <input
                  id="private-sign-in-secret"
                  type="password"
                  autoComplete="current-password"
                  minLength={32}
                  value={privateSecret}
                  onChange={(event) => setPrivateSecret(event.target.value)}
                  required
                />
                <button
                  className="button button--primary"
                  type="submit"
                  disabled={privateLoginPending}
                >
                  {privateLoginPending ? 'Signing in…' : 'Sign in'}
                </button>
              </form>
            </>
          )}
        </section>
      </main>
    )
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
          {navigationPages.map((item) => (
            <a
              className="nav-link"
              key={item.id}
              href={item.path}
              aria-current={view === item.id ? 'page' : undefined}
              onClick={(event) => onNavigate(event, item.id)}
            >
              <span className="nav-icon" aria-hidden="true">
                {pageIcons[item.id]}
              </span>
              <span>{item.label}</span>
            </a>
          ))}
        </nav>

        <p className="sidebar-caption">Private creator workspace</p>
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
          </div>
        </header>

        <main
          id="main-content"
          className={`main-content main-content--${view}`}
        >
          {view !== 'dashboard' && (
            <div className="page-heading">
              <h1 id="page-title" tabIndex={-1}>
                {page.label}
              </h1>
              <p className="intro">{page.description}</p>
            </div>
          )}

          {view === 'dashboard' && sessionStatus === 'authenticated' ? (
            <CreatorDashboard
              onAnalyzeDraft={(context) => {
                setDraftContext(context)
                navigate('draft')
              }}
              onSessionExpired={() => {
                setSessionStatus('unauthenticated')
                setDraftContext(null)
              }}
            />
          ) : view === 'draft' && sessionStatus === 'authenticated' ? (
            <DraftAnalysis
              context={draftContext}
              onViewMonitoring={navigateToMonitoring}
              onBackToDashboard={() => navigate('dashboard')}
              onSessionExpired={() => {
                setSessionStatus('unauthenticated')
                setDraftContext(null)
              }}
            />
          ) : view === 'history' && sessionStatus === 'authenticated' ? (
            <CreatorHistoryDashboard
              onSessionExpired={() => {
                setSessionStatus('unauthenticated')
                setDraftContext(null)
              }}
            />
          ) : view === 'monitoring' && sessionStatus === 'authenticated' ? (
            <PostMonitoring
              assessmentId={new URLSearchParams(
                locationKey.split('?')[1] ?? '',
              ).get('assessment_id')}
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
            </section>
          )}

          <footer className="page-footer">
            BipMe <span aria-hidden="true">·</span> Private creator intelligence
          </footer>
        </main>
      </div>
    </div>
  )
}
