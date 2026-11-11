import { useEffect, useState, type FormEvent } from 'react'
import { ApiRequestError, apiClient } from '../api/client'
import type { components } from '../api/generated/schema'
import {
  ApiResponseError,
  authApi,
  getXAuthorizationUrl,
  type XConnection,
} from '../auth/client'
import { StateNotice, type ViewState } from '../components/StateNotice'
import type { SessionStatus } from '../App'

type HistoryImportStatus = components['schemas']['ImportStatus']

type ImportState =
  'not-started' | 'in-progress' | 'partial' | 'failed' | 'completed'
type ConnectionFixture =
  | 'none'
  | 'session-expired'
  | 'connection-expired'
  | 'consent-denied'
  | 'account-not-allowed'
  | 'rate-limited'
  | 'unavailable'
  | 'refreshing'
  | 'disconnecting'
type StepId =
  'welcome' | 'goals' | 'source' | 'permissions' | 'import' | 'report'

const steps: { id: StepId; label: string }[] = [
  { id: 'welcome', label: 'Welcome' },
  { id: 'goals', label: 'Your goals' },
  { id: 'source', label: 'Connect' },
  { id: 'permissions', label: 'Permissions' },
  { id: 'import', label: 'Import' },
  { id: 'report', label: 'First report' },
]

const importFixtures: Record<
  ImportState,
  { title: string; body: string; progress?: number; state?: ViewState }
> = {
  'not-started': {
    title: 'Import not started',
    body: 'Synthetic fixture. No creator data has been uploaded or read.',
  },
  'in-progress': {
    title: 'Import in progress',
    body: 'Synthetic fixture · deterministic preview only; no import is running.',
    progress: 42,
  },
  partial: {
    title: 'Partial import',
    body: 'Synthetic fixture · some permitted records are unavailable.',
    progress: 68,
    state: 'insufficient-evidence',
  },
  failed: {
    title: 'Import failed',
    body: 'Synthetic fixture · the import service is not connected to this preview.',
    state: 'error',
  },
  completed: {
    title: 'Import completed',
    body: 'Synthetic fixture · this does not mean any creator history was imported.',
    progress: 100,
  },
}

const connectionFixtures: Partial<
  Record<ConnectionFixture, { state: ViewState; title: string; body: string }>
> = {
  'session-expired': {
    state: 'unauthenticated',
    title: 'Private session expired',
    body: 'Synthetic fixture only. X authorization expiry is a separate state.',
  },
  'connection-expired': {
    state: 'error',
    title: 'X authorization expired',
    body: 'Synthetic fixture only. The private BipMe session remains separate.',
  },
  'consent-denied': {
    state: 'error',
    title: 'X access was not granted',
    body: 'Synthetic fixture only. You can keep using BipMe without X.',
  },
  'account-not-allowed': {
    state: 'error',
    title: 'X account not allowed',
    body: 'Synthetic fixture only. The server allowlist remains authoritative.',
  },
  'rate-limited': {
    state: 'rate-limited',
    title: 'Connection request rate limited',
    body: 'Synthetic fixture only. No automatic retry is performed.',
  },
  unavailable: {
    state: 'error',
    title: 'Connection unavailable',
    body: 'Synthetic fixture only. No live connection status is implied.',
  },
  refreshing: {
    state: 'loading',
    title: 'Refreshing X authorization',
    body: 'Synthetic fixture only. No refresh request is running.',
  },
  disconnecting: {
    state: 'loading',
    title: 'Disconnecting X',
    body: 'Synthetic fixture only. No account is being disconnected.',
  },
}

function friendlyError(error: unknown) {
  if (!(error instanceof ApiResponseError))
    return 'The BipMe API could not be reached. No connection state was changed.'
  if (error.status === 429)
    return 'The service is rate limiting requests. Wait before trying again; BipMe will not retry automatically.'
  switch (error.code) {
    case 'authentication_required':
    case 'session_invalid':
      return 'Your private session is no longer available. Sign in again to continue.'
    case 'private_session_not_configured':
      return 'Private sign-in is not configured for this environment.'
    case 'x_reauthorization_required':
      return 'The X authorization has expired. Reconnect the account to continue.'
    case 'x_consent_denied':
      return 'X access was not granted. You can continue without connecting X.'
    case 'x_account_not_allowed':
      return 'This X account is not on the authorized account allowlist.'
    case 'invalid_request':
    case 'invalid_return_url':
    case 'oauth_callback_invalid':
      return 'The authorization response could not be verified. Start a new authorization if you still want to connect X.'
    default:
      return 'The request could not be completed. Your connection settings were not changed.'
  }
}

export function ConnectionsPage({
  sessionStatus,
  onSessionStatus,
}: {
  sessionStatus: SessionStatus
  onSessionStatus: (status: SessionStatus) => void
}) {
  const [step, setStep] = useState(0)
  const [secret, setSecret] = useState('')
  const [loginBusy, setLoginBusy] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)
  const [connection, setConnection] = useState<XConnection | null>(null)
  const [connectionBusy, setConnectionBusy] = useState(false)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [action, setAction] = useState<'refresh' | 'disconnect' | null>(null)
  const [goal, setGoal] = useState('')
  const [niche, setNiche] = useState('')
  const [audience, setAudience] = useState('')
  const [fixture, setFixture] = useState<ImportState>('not-started')
  const [historyImports, setHistoryImports] = useState<
    HistoryImportStatus[] | null
  >(null)
  const [historyImportError, setHistoryImportError] = useState<{
    state: 'error' | 'rate-limited'
    message: string
  } | null>(null)
  const [historyImportsBusy, setHistoryImportsBusy] = useState(false)
  const [historyImportsRefresh, setHistoryImportsRefresh] = useState(0)
  const [connectionFixture, setConnectionFixture] =
    useState<ConnectionFixture>('none')
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    if (sessionStatus !== 'authenticated') {
      setConnection(null)
      return
    }
    const controller = new AbortController()
    setConnectionBusy(true)
    setConnectionError(null)
    authApi
      .readXConnection(controller.signal)
      .then((result) => setConnection(result))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (
          error instanceof ApiResponseError &&
          (error.status === 401 ||
            error.code === 'authentication_required' ||
            error.code === 'session_invalid')
        ) {
          onSessionStatus('unauthenticated')
          return
        }
        setConnectionError(friendlyError(error))
      })
      .finally(() => {
        if (!controller.signal.aborted) setConnectionBusy(false)
      })
    return () => controller.abort()
  }, [sessionStatus, onSessionStatus])

  useEffect(() => {
    if (step !== 4 || sessionStatus !== 'authenticated') {
      setHistoryImports(null)
      setHistoryImportError(null)
      setHistoryImportsBusy(false)
      return
    }
    const controller = new AbortController()
    setHistoryImportsBusy(true)
    setHistoryImportError(null)
    apiClient
      .historyImports(20, controller.signal)
      .then((result) => setHistoryImports(result.items))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (
          error instanceof ApiRequestError &&
          (error.status === 401 ||
            error.code === 'authentication_required' ||
            error.code === 'session_invalid')
        ) {
          onSessionStatus('unauthenticated')
          return
        }
        setHistoryImportError({
          state:
            error instanceof ApiRequestError && error.status === 429
              ? 'rate-limited'
              : 'error',
          message:
            error instanceof ApiRequestError && error.status === 429
              ? 'The import status service is rate limiting requests. Wait before checking again; BipMe will not retry automatically.'
              : 'The server-reported import status is unavailable. No import was started or changed.',
        })
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryImportsBusy(false)
      })
    return () => controller.abort()
  }, [step, sessionStatus, historyImportsRefresh, onSessionStatus])

  useEffect(() => {
    if (
      new URLSearchParams(window.location.search).get('x_connection') ===
      'connected'
    ) {
      const url = new URL(window.location.href)
      url.searchParams.delete('x_connection')
      window.history.replaceState(
        null,
        '',
        `${url.pathname}${url.search}${url.hash}`,
      )
      // The callback marker is only a navigation hint. Verify the result with
      // the authenticated connection endpoint before presenting success.
      const controller = new AbortController()
      authApi
        .readXConnection(controller.signal)
        .then((result) => {
          if (controller.signal.aborted || !result.connected) return
          setConnection(result)
          setStep(2)
          setNotice('The BipMe server confirmed the X connection.')
        })
        .catch(() => {
          if (!controller.signal.aborted)
            setConnectionError(
              'The connection result could not be verified with the BipMe API.',
            )
        })
      return () => controller.abort()
    }
  }, [])

  async function submitPrivateLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submittedSecret = secret
    setSecret('')
    setLoginError(null)
    setLoginBusy(true)
    try {
      await authApi.createPrivateSession(submittedSecret)
      onSessionStatus('authenticated')
      setStep(0)
    } catch (error) {
      setLoginError(friendlyError(error))
    } finally {
      setSecret('')
      setLoginBusy(false)
    }
  }

  async function checkSession() {
    onSessionStatus('checking')
    try {
      await authApi.readSession()
      onSessionStatus('authenticated')
    } catch (error) {
      onSessionStatus(
        error instanceof ApiResponseError && error.status === 401
          ? 'unauthenticated'
          : 'unavailable',
      )
    }
  }

  async function refreshConnection() {
    if (action || connectionBusy) return
    setAction('refresh')
    setConnectionError(null)
    try {
      const result = await authApi.refreshXConnection()
      setConnection(result)
      setNotice('X connection refreshed by the BipMe server.')
    } catch (error) {
      if (
        error instanceof ApiResponseError &&
        error.code === 'x_reauthorization_required'
      ) {
        setConnection(
          (current) =>
            current && {
              ...current,
              connected: false,
              state: 'reauth_required',
            },
        )
      } else if (error instanceof ApiResponseError && error.status === 401) {
        if (
          error.code === 'authentication_required' ||
          error.code === 'session_invalid'
        )
          onSessionStatus('unauthenticated')
        else
          setConnection(
            (current) =>
              current && {
                ...current,
                connected: false,
                state: 'reauth_required',
              },
          )
      }
      setConnectionError(friendlyError(error))
    } finally {
      setAction(null)
    }
  }

  async function disconnectConnection() {
    if (action || connectionBusy) return
    const confirmed = window.confirm(
      'Disconnect this X account? BipMe will remove its stored connection tokens. You can continue using an archive-only workflow when the import service is available.',
    )
    if (!confirmed) return
    setAction('disconnect')
    setConnectionError(null)
    try {
      await authApi.disconnectXConnection()
      setConnection({
        connected: false,
        state: 'revoked',
        scopes: [],
        expires_at: null,
      })
      setNotice('The BipMe server disconnected the X account.')
    } catch (error) {
      if (error instanceof ApiResponseError && error.status === 401) {
        if (
          error.code === 'authentication_required' ||
          error.code === 'session_invalid'
        )
          onSessionStatus('unauthenticated')
      }
      setConnectionError(friendlyError(error))
    } finally {
      setAction(null)
    }
  }

  if (sessionStatus === 'checking')
    return <StateNotice state="loading" title="Checking your private session" />

  if (sessionStatus === 'unavailable')
    return (
      <section className="connections-access workspace-card">
        <p className="eyebrow">Private workspace</p>
        <h2>Sign-in status unavailable</h2>
        <p>
          The BipMe API could not verify your private session. Try again when
          the service is available.
        </p>
        <button
          className="button button--primary"
          type="button"
          onClick={checkSession}
        >
          Check session again
        </button>
      </section>
    )

  if (sessionStatus === 'unauthenticated')
    return (
      <section
        className="connections-access workspace-card"
        aria-labelledby="private-login-title"
      >
        <p className="eyebrow">Secure private access</p>
        <h2 id="private-login-title">Sign in to your BipMe workspace</h2>
        <p>
          Use the provisioned private-session secret. X authorization is
          optional and is not needed for archive-only use.
        </p>
        <form className="private-login-form" onSubmit={submitPrivateLogin}>
          <label htmlFor="private-session-secret">Private-session secret</label>
          <input
            id="private-session-secret"
            type="password"
            autoComplete="off"
            maxLength={512}
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
            required
            aria-describedby="private-login-hint"
          />
          <p id="private-login-hint">
            The secret is sent only to the same-origin BipMe API and cleared
            from this form after submission.
          </p>
          {loginError && (
            <StateNotice
              state="error"
              title="Sign-in unavailable"
              body={loginError}
            />
          )}
          <button
            className="button button--primary"
            type="submit"
            disabled={loginBusy || !secret}
          >
            {loginBusy ? 'Signing in…' : 'Continue securely'}
          </button>
        </form>
      </section>
    )

  const activeStep = steps[step]
  const expired = Boolean(
    connection?.expires_at && Date.parse(connection.expires_at) <= Date.now(),
  )
  const connectionLabel = connectionBusy
    ? 'Checking X connection'
    : connectionError
      ? 'Connection unavailable'
      : connection?.state === 'reauth_required'
        ? 'Authorization expired'
        : connection?.connected && expired
          ? 'Access token expired'
          : connection?.connected
            ? 'Connected'
            : 'Not connected'
  const importState = importFixtures[fixture]
  const latestHistoryImport = historyImports
    ?.slice()
    .sort(
      (left, right) =>
        Date.parse(right.started_at) - Date.parse(left.started_at),
    )[0]

  function refreshHistoryImportStatus() {
    if (historyImportsBusy) return
    setHistoryImportsRefresh((value) => value + 1)
  }

  return (
    <div className="connections-page">
      <section className="connections-intro">
        <p className="eyebrow">Get started</p>
        <h2>Build intelligence from your own work.</h2>
        <p>
          Set up BipMe in a few clear steps. You stay in control of what you
          share.
        </p>
        {notice && (
          <p className="inline-confirmation" role="status">
            {notice}
          </p>
        )}
      </section>

      <nav className="onboarding-progress" aria-label="Onboarding progress">
        <ol>
          {steps.map((item, index) => (
            <li key={item.id}>
              <button
                type="button"
                aria-current={step === index ? 'step' : undefined}
                aria-label={`Step ${index + 1}: ${item.label}${step === index ? ', current step' : ''}`}
                disabled={index > step}
                onClick={() => setStep(index)}
              >
                <span>{index + 1}</span>
                <small>{item.label}</small>
              </button>
            </li>
          ))}
        </ol>
      </nav>

      <section
        className="onboarding-card"
        aria-labelledby="onboarding-step-title"
      >
        <p className="card-kicker">Step {step + 1} of 6</p>
        <div className="onboarding-card__body">
          <div className="onboarding-brand-mark" aria-hidden="true">
            b,
          </div>
          {step === 0 && (
            <div className="onboarding-copy">
              <h3 id="onboarding-step-title">Welcome to BipMe</h3>
              <p>
                We help you find patterns in your published content and turn
                them into practical next moves—not vague scores or promises.
              </p>
              <ul className="benefit-list">
                <li>Evidence behind every recommendation</li>
                <li>Clear limits when the data is thin</li>
                <li>Your data stays under your control</li>
              </ul>
            </div>
          )}
          {step === 1 && (
            <div className="onboarding-copy">
              <h3 id="onboarding-step-title">What are you creating toward?</h3>
              <p>
                Your choices are held in this page only. They are not sent to or
                saved by the server.
              </p>
              <fieldset className="goal-options">
                <legend>Choose your main goal</legend>
                {[
                  'Grow an engaged audience',
                  'Build a personal brand',
                  'Find customer leads',
                  'Improve content quality',
                ].map((option) => (
                  <label
                    key={option}
                    className={
                      goal === option
                        ? 'choice-card choice-card--selected'
                        : 'choice-card'
                    }
                  >
                    <input
                      type="radio"
                      name="creator-goal"
                      value={option}
                      checked={goal === option}
                      onChange={() => setGoal(option)}
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </fieldset>
              <div className="onboarding-fields">
                <label htmlFor="creator-niche">Primary niche</label>
                <select
                  id="creator-niche"
                  value={niche}
                  onChange={(event) => setNiche(event.target.value)}
                >
                  <option value="">Choose a niche</option>
                  <option>Creative entrepreneurship</option>
                  <option>Technology</option>
                  <option>Business</option>
                  <option>Lifestyle</option>
                  <option>Other</option>
                </select>
                <label htmlFor="creator-audience">
                  Intended audience <span>(optional)</span>
                </label>
                <input
                  id="creator-audience"
                  value={audience}
                  onChange={(event) => setAudience(event.target.value)}
                  maxLength={120}
                  placeholder="e.g. independent product designers"
                />
              </div>
              <p className="prototype-note">
                Prototype only · goals, niche and audience are not persisted.
              </p>
            </div>
          )}
          {step === 2 && (
            <div className="onboarding-copy">
              <h3 id="onboarding-step-title">Choose a data source</h3>
              <p>
                Pick the path that fits. X is optional. No account is assumed
                connected.
              </p>
              <div className="source-status" aria-live="polite">
                <span
                  className={`status-dot ${connectionBusy ? 'status-dot--checking' : connection?.connected ? 'status-dot--available' : 'status-dot--neutral'}`}
                  aria-hidden="true"
                />
                <strong>{connectionLabel}</strong>
                {connection?.state && (
                  <span className="source-status__detail">
                    {' '}
                    · {connection.state.replaceAll('_', ' ')}
                  </span>
                )}
              </div>
              <div className="source-options">
                <article className="source-option">
                  <div className="source-option__icon" aria-hidden="true">
                    𝕏
                  </div>
                  <div>
                    <h4>
                      Connect an authorized X account{' '}
                      <span className="optional-tag">Optional</span>
                    </h4>
                    <p>
                      Read-only access for supported X features. Authorization
                      is handled by the BipMe server.
                    </p>
                  </div>
                  <a
                    className="button button--primary"
                    href={getXAuthorizationUrl()}
                  >
                    {connection?.connected ? 'Reconnect X' : 'Connect X'}
                  </a>
                </article>
                <article className="source-option source-option--muted">
                  <div className="source-option__icon" aria-hidden="true">
                    ⇧
                  </div>
                  <div>
                    <h4>
                      Use a permitted creator archive{' '}
                      <span className="prototype-tag">Unavailable</span>
                    </h4>
                    <p>
                      Archive import is unavailable until its format, rights,
                      retention and deletion requirements are resolved.
                    </p>
                  </div>
                  <button
                    className="button button--secondary"
                    type="button"
                    disabled
                  >
                    Archive import unavailable
                  </button>
                </article>
              </div>
              {connectionError && (
                <StateNotice
                  state="error"
                  title="Connection status unavailable"
                  body={connectionError}
                />
              )}
              {connection?.connected && (
                <div className="connection-actions">
                  {expired && (
                    <StateNotice
                      state="error"
                      title="X access token expired"
                      body="The server returned an expiry time in the past. Your private BipMe session is separate."
                    />
                  )}
                  <button
                    className="button button--secondary"
                    type="button"
                    disabled={action !== null || connectionBusy}
                    onClick={refreshConnection}
                  >
                    {action === 'refresh'
                      ? 'Refreshing…'
                      : 'Refresh authorization'}
                  </button>
                  <button
                    className="button button--danger"
                    type="button"
                    disabled={action !== null || connectionBusy}
                    onClick={disconnectConnection}
                  >
                    {action === 'disconnect'
                      ? 'Disconnecting…'
                      : 'Disconnect X'}
                  </button>
                </div>
              )}
              {connection?.state === 'reauth_required' && (
                <StateNotice
                  state="unauthenticated"
                  title="Reconnect X"
                  body="X authorization has expired or needs renewed consent. Your BipMe private session remains separate."
                />
              )}
              {import.meta.env.DEV && (
                <details className="connection-fixture">
                  <summary>Development fixture · connection states</summary>
                  <label htmlFor="connection-state-fixture">
                    Synthetic connection state
                  </label>
                  <select
                    id="connection-state-fixture"
                    value={connectionFixture}
                    onChange={(event) =>
                      setConnectionFixture(
                        event.target.value as ConnectionFixture,
                      )
                    }
                  >
                    {(
                      [
                        'none',
                        ...Object.keys(connectionFixtures),
                      ] as ConnectionFixture[]
                    ).map((state) => (
                      <option key={state} value={state}>
                        {state.replaceAll('-', ' ')}
                      </option>
                    ))}
                  </select>
                  {connectionFixture !== 'none' &&
                    connectionFixtures[connectionFixture] && (
                      <StateNotice
                        {...connectionFixtures[connectionFixture]!}
                      />
                    )}
                </details>
              )}
            </div>
          )}
          {step === 3 && (
            <div className="onboarding-copy">
              <h3 id="onboarding-step-title">Review data permissions</h3>
              <p>
                Only the BipMe server requests and stores provider permissions.
                BipMe does not publish for you.
              </p>
              <ul className="permission-list">
                <li>
                  <strong>Read published posts</strong>
                  <span>
                    Used only by server features that have passed their access
                    and cost gates.
                  </span>
                </li>
                <li>
                  <strong>Read engagement counts</strong>
                  <span>
                    Displayed only when the authorized API returns them.
                  </span>
                </li>
                <li>
                  <strong>No publishing permission</strong>
                  <span>BipMe cannot create or delete posts.</span>
                </li>
              </ul>
              {connection?.scopes?.length ? (
                <p className="scope-list">
                  Server-reported scopes: {connection.scopes.join(', ')}
                </p>
              ) : (
                <p className="prototype-note">
                  No X scopes have been granted to this session.
                </p>
              )}
            </div>
          )}
          {step === 4 && (
            <div className="onboarding-copy">
              <h3 id="onboarding-step-title">Prepare your content history</h3>
              <p>
                When a permitted source and import service are available, BipMe
                can organize eligible posts before a report is prepared.
              </p>
              <div className="import-status-card">
                <p className="card-kicker">Import status</p>
                {historyImportError ? (
                  <StateNotice
                    state={historyImportError.state}
                    title={
                      historyImportError.state === 'rate-limited'
                        ? 'Import status rate limited'
                        : 'Import status unavailable'
                    }
                    body={historyImportError.message}
                  />
                ) : historyImportsBusy || historyImports === null ? (
                  <StateNotice
                    state="loading"
                    title="Checking import status"
                    body="Reading existing import records from the authenticated BipMe server. This check does not start or resume an import."
                  />
                ) : latestHistoryImport ? (
                  <>
                    <StateNotice
                      state={
                        latestHistoryImport.status === 'running'
                          ? 'loading'
                          : latestHistoryImport.status === 'partial'
                            ? 'insufficient-evidence'
                            : latestHistoryImport.status === 'unavailable'
                              ? 'error'
                              : 'empty'
                      }
                      title={
                        latestHistoryImport.status === 'running'
                          ? 'Import in progress'
                          : latestHistoryImport.status === 'partial'
                            ? 'Partial import'
                            : latestHistoryImport.status === 'unavailable'
                              ? 'Import unavailable'
                              : 'Import completed'
                      }
                      body={`The server reports ${latestHistoryImport.imported_posts} of ${latestHistoryImport.requested_posts} requested posts imported across ${latestHistoryImport.pages_read} pages. Source: ${latestHistoryImport.source}. Refreshing checks status only; it does not resume provider work.`}
                    />
                    {latestHistoryImport.status !== 'unavailable' &&
                      latestHistoryImport.requested_posts > 0 && (
                        <div className="fixture-progress">
                          <div className="fixture-progress__label">
                            <span>Server-reported imported posts</span>
                            <strong>
                              {latestHistoryImport.imported_posts} /{' '}
                              {latestHistoryImport.requested_posts}
                            </strong>
                          </div>
                          <progress
                            max={latestHistoryImport.requested_posts}
                            value={Math.min(
                              latestHistoryImport.imported_posts,
                              latestHistoryImport.requested_posts,
                            )}
                            aria-label="Server-reported imported posts"
                          />
                        </div>
                      )}
                  </>
                ) : (
                  <StateNotice
                    state="empty"
                    title="No import has been started"
                    body="The server reports no existing history import. Starting or resuming provider work is unavailable from this screen."
                  />
                )}
                <button
                  className="button button--secondary"
                  type="button"
                  onClick={refreshHistoryImportStatus}
                  disabled={historyImportsBusy}
                >
                  {historyImportsBusy ? 'Checking status…' : 'Refresh status'}
                </button>
                {import.meta.env.DEV && (
                  <div className="import-fixture-preview">
                    <p className="card-kicker">
                      Development-only synthetic state fixture
                    </p>
                    <div className="fixture-selector">
                      <label htmlFor="import-state-fixture">
                        Development fixture (synthetic)
                      </label>
                      <select
                        id="import-state-fixture"
                        value={fixture}
                        onChange={(event) =>
                          setFixture(event.target.value as ImportState)
                        }
                      >
                        {Object.keys(importFixtures).map((state) => (
                          <option key={state} value={state}>
                            {state.replaceAll('-', ' ')}
                          </option>
                        ))}
                      </select>
                    </div>
                    <StateNotice
                      state={
                        importState.state ??
                        (importState.progress ? 'loading' : 'empty')
                      }
                      title={importState.title}
                      body={importState.body}
                    />
                    {fixture !== 'not-started' && (
                      <div className="fixture-progress">
                        <div className="fixture-progress__label">
                          <span>Synthetic fixture progress</span>
                          <strong>{importState.progress ?? 0}%</strong>
                        </div>
                        <progress
                          max="100"
                          value={importState.progress ?? 0}
                          aria-label="Synthetic import fixture progress"
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          {step === 5 && (
            <div className="onboarding-copy">
              <h3 id="onboarding-step-title">
                Your first report will start here
              </h3>
              <p>
                We’ll separate observed patterns, hypotheses and recommendations
                so you always know what the evidence supports.
              </p>
              <StateNotice
                state="empty"
                title="First report unavailable"
                body="A report requires permitted creator evidence and its own product workflow. This preview does not include sample metrics or a simulated report."
              />
            </div>
          )}
        </div>
        <div className="onboarding-card__footer">
          <button
            className="button button--secondary"
            type="button"
            disabled={step === 0}
            onClick={() => setStep((current) => Math.max(0, current - 1))}
          >
            Back
          </button>
          <button
            className="button button--primary"
            type="button"
            onClick={() =>
              setStep((current) => Math.min(steps.length - 1, current + 1))
            }
          >
            {step === steps.length - 1 ? 'Finish preview' : 'Continue'}{' '}
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </section>
      <p className="onboarding-footnote">
        X is optional. Goals stay local to this page. Import and reporting
        remain unavailable until their authorization and data safeguards are
        ready.
      </p>
      <span className="sr-only" aria-live="polite">
        Current step: {activeStep.label}
      </span>
    </div>
  )
}
