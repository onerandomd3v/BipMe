import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import type { components } from './api/generated/schema'
import { ApiRequestError, apiClient, type ApiClient } from './api/client'
import {
  apiProblemMessage,
  dashboardLoadState,
  nicheAvailability,
  recordList,
  reportCoverageLabel,
  reportIsStale,
  suggestionsForReport,
  stringList,
} from './dashboardModel'
import type { DraftAnalysisContext } from './dashboardModel'

type ProfileState = components['schemas']['CreatorProfileStateResponse']
type Profile = components['schemas']['CreatorProfileResponse']
type Permission = components['schemas']['DataPermissionResponse']
type ReportState = components['schemas']['CreatorReportStateResponse']
type Report = components['schemas']['CreatorReportResponse']
type Outcome =
  components['schemas']['CreatorProfileUpdate']['priority_outcomes'][number]
type Style = NonNullable<
  components['schemas']['CreatorProfileUpdate']['preferred_styles']
>[number]

const outcomes: { value: Outcome; label: string }[] = [
  { value: 'conversation', label: 'Relevant conversation' },
  { value: 'qualified_interest', label: 'Qualified interest' },
  { value: 'reach', label: 'Reach' },
  { value: 'authority', label: 'Authority' },
]

const styles: { value: Style; label: string }[] = [
  { value: 'personal_story', label: 'Personal story' },
  { value: 'technical_explainer', label: 'Technical explainer' },
  { value: 'opinion', label: 'Opinion' },
  { value: 'question', label: 'Question-led' },
  { value: 'tutorial', label: 'Tutorial' },
  { value: 'other', label: 'Other' },
]

function reportRecord(report: Report) {
  return report.report && typeof report.report === 'object'
    ? (report.report as Record<string, unknown>)
    : {}
}

function permissionRecord(report: Report, key: string) {
  const permissions = report.processing_permissions
  if (!permissions || typeof permissions !== 'object') return null
  const value = (permissions as Record<string, unknown>)[key]
  return value && typeof value === 'object'
    ? (value as Record<string, unknown>)
    : null
}

function dateLabel(value: unknown) {
  if (typeof value !== 'string') return 'Unknown date'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown date'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
}

function fieldError(error: unknown, field: string) {
  if (!(error instanceof ApiRequestError) || !Array.isArray(error.details))
    return null
  const detail = error.details.find((item) => {
    if (!item || typeof item !== 'object') return false
    const loc = (item as { loc?: unknown }).loc
    return Array.isArray(loc) && loc.some((part) => part === field)
  })
  return detail && typeof detail === 'object' && 'msg' in detail
    ? String((detail as { msg: unknown }).msg)
    : null
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === 'AbortError'
}

function draftContext(
  profileState: ProfileState,
  report: Report,
): DraftAnalysisContext {
  return {
    creatorKey: profileState.profile?.creator_key ?? report.creator_key,
    reportId: report.id,
    goalsRevision: report.goals_revision,
    reportAsOf: report.as_of,
    coverage: report.coverage,
  }
}

function ReportEvidenceSection({ report }: { report: Report }) {
  const content = reportRecord(report)
  const personalFindings = recordList(content.personal_findings)
  const nicheFindings = recordList(content.niche_findings)
  const suggestions = suggestionsForReport(report)
  const evidence = report.evidence as Record<string, unknown>
  const sources = recordList(evidence.sources)
  const observations = recordList(evidence.observations)
  const nicheState = nicheAvailability(report)

  return (
    <div className="report-sections">
      <section className="report-section" aria-labelledby="history-title">
        <div className="report-section__heading">
          <div>
            <p className="card-kicker">Your history</p>
            <h2 id="history-title">What your permitted history shows</h2>
          </div>
          <span className="metric-pill">
            {observations.length} observations
          </span>
        </div>
        {personalFindings.length === 0 ? (
          <p className="muted-copy">
            No usable creator-owned observations are included in this snapshot.
            BipMe will not fill this gap with assumed performance.
          </p>
        ) : (
          <div className="finding-list">
            {personalFindings.map((finding, index) => (
              <article
                className="finding"
                key={`${String(finding.summary)}-${index}`}
              >
                <div className="finding__topline">
                  <span className="evidence-label">
                    {String(finding.kind ?? 'observation')}
                  </span>
                  <span>
                    {String(finding.evidence_strength ?? 'Unknown')} evidence
                  </span>
                </div>
                <p>{String(finding.summary ?? 'Observed pattern')}</p>
                <small>
                  Metric: {String(finding.metric ?? 'not specified')} · Sample:{' '}
                  {String(finding.effective_sample_size ?? 'not reported')} ·
                  Evidence:{' '}
                  {stringList(finding.evidence_ids).join(', ') || 'not cited'}
                </small>
              </article>
            ))}
          </div>
        )}
        <div className="source-summary">
          <strong>Sources</strong>
          {sources.length === 0 ? (
            <span>No source snapshot was included.</span>
          ) : (
            sources.map((source, index) => (
              <span key={`${String(source.source_id)}-${index}`}>
                {String(source.source_id ?? 'Unnamed source')} · observed{' '}
                {dateLabel(source.observed_at)}
              </span>
            ))
          )}
        </div>
        {observations.length > 0 && (
          <div className="observation-list" aria-label="Observed metrics">
            {observations.slice(0, 8).map((observation, index) => (
              <div
                className="observation"
                key={`${String(observation.post_id)}-${String(observation.metric)}-${index}`}
              >
                <strong>
                  {String(observation.metric ?? 'Metric not named')}
                </strong>
                <span>
                  {String(
                    observation.metric_definition ?? 'Definition not reported',
                  )}{' '}
                  · {String(observation.window ?? 'Window not reported')}
                </span>
                <small>
                  Value: {String(observation.value ?? 'not observed')} ·
                  observed {dateLabel(observation.observed_at)} · post{' '}
                  {String(observation.post_id ?? 'not cited')}
                </small>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="report-section" aria-labelledby="niche-title">
        <div className="report-section__heading">
          <div>
            <p className="card-kicker">What’s happening in your niche</p>
            <h2 id="niche-title">Permissioned niche evidence</h2>
          </div>
          <span className="metric-pill metric-pill--muted">
            {nicheState.label}
          </span>
        </div>
        {nicheFindings.length === 0 ? (
          <div className="inline-limitation">
            <strong>Niche discovery is unavailable</strong>
            <p>
              This snapshot does not contain enough permitted niche evidence to
              claim current niche trends or private signals.
            </p>
            <small>{nicheState.detail}</small>
          </div>
        ) : (
          <div className="finding-list">
            {nicheFindings.map((finding, index) => (
              <article
                className="finding"
                key={`${String(finding.summary)}-${index}`}
              >
                <div className="finding__topline">
                  <span className="evidence-label">
                    Observed niche evidence
                  </span>
                  <span>{String(finding.freshness ?? 'unknown')}</span>
                </div>
                <p>{String(finding.summary ?? 'Observed niche pattern')}</p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="report-section" aria-labelledby="experiments-title">
        <div className="report-section__heading">
          <div>
            <p className="card-kicker">Testable next steps</p>
            <h2 id="experiments-title">Hypotheses, not promises</h2>
          </div>
          <span className="metric-pill">{suggestions.length} ideas</span>
        </div>
        {suggestions.length === 0 ? (
          <p className="muted-copy">
            No evidence-linked experiment is justified by this snapshot yet.
          </p>
        ) : (
          <div className="finding-list">
            {suggestions.map((suggestion, index) => (
              <article
                className="finding"
                key={`${suggestion.kind}-${suggestion.text}-${index}`}
              >
                <div className="finding__topline">
                  <span className="evidence-label">
                    {suggestion.kind === 'hypothesis'
                      ? 'Hypothesis'
                      : 'Evidence-linked opportunity'}
                  </span>
                  <span>{suggestion.evidenceStrength} evidence</span>
                </div>
                <p>{suggestion.text}</p>
                <small>
                  Evidence: {suggestion.evidenceIds.join(', ') || 'not cited'}
                  {suggestion.kind === 'opportunity' && (
                    <> · Metric: {suggestion.metric}</>
                  )}
                </small>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function OnboardingForm({
  existing,
  permission,
  onComplete,
  client,
}: {
  existing: Profile | null
  permission: Permission | null
  onComplete: (profile: Profile, report: Report) => void
  client: ApiClient
}) {
  const [niche, setNiche] = useState(existing?.niche ?? '')
  const [audience, setAudience] = useState(existing?.intended_audience ?? '')
  const [selectedOutcomes, setSelectedOutcomes] = useState<Outcome[]>(
    existing?.priority_outcomes ?? ['conversation'],
  )
  const [selectedStyles, setSelectedStyles] = useState<Style[]>(
    existing?.preferred_styles ?? ['personal_story'],
  )
  const [allowHistory, setAllowHistory] = useState(
    permission?.personal_history === 'granted',
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState('')
  const mounted = useRef(true)
  const controllerRef = useRef<AbortController | null>(null)
  const feedbackRef = useRef<HTMLDivElement>(null)
  const submittingRef = useRef(false)

  useEffect(
    () => () => {
      mounted.current = false
      controllerRef.current?.abort()
    },
    [],
  )

  useEffect(() => {
    if (error !== null) feedbackRef.current?.focus()
  }, [error])

  const toggle = <T extends string>(
    values: T[],
    value: T,
    setter: (next: T[]) => void,
  ) =>
    setter(
      values.includes(value)
        ? values.filter((item) => item !== value)
        : [...values, value],
    )

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submittingRef.current) return
    submittingRef.current = true
    setSaving(true)
    setError(null)
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    try {
      const profile = await client.saveProfile(
        {
          niche,
          intended_audience: audience,
          priority_outcomes: selectedOutcomes,
          preferred_styles: selectedStyles,
        },
        controller.signal,
      )
      await client.saveDataPermissions(
        { allow_personal_history: allowHistory },
        controller.signal,
      )
      const report = await client.generateReport(
        { data_sources: allowHistory ? ['personal_history'] : [] },
        `cod-379-${crypto.randomUUID()}`,
        controller.signal,
      )
      if (mounted.current && !controller.signal.aborted) {
        setStatus('Your report is ready.')
        onComplete(profile, report)
      }
    } catch (submissionError) {
      if (
        mounted.current &&
        !(
          submissionError instanceof DOMException &&
          submissionError.name === 'AbortError'
        )
      )
        setError(submissionError)
    } finally {
      if (mounted.current && controllerRef.current === controller)
        setSaving(false)
      if (controllerRef.current === controller) {
        controllerRef.current = null
        submittingRef.current = false
      }
    }
  }

  return (
    <form
      className="onboarding-card"
      onSubmit={submit}
      aria-labelledby="onboarding-title"
      aria-busy={saving}
    >
      <div className="workspace-card__header">
        <div className="workspace-card__mark" aria-hidden="true">
          1
        </div>
        <div>
          <p className="card-kicker">Start with your context</p>
          <h2 id="onboarding-title">Set up your Creator Intelligence Report</h2>
        </div>
      </div>
      <p className="muted-copy">
        These are declared goals, not inferred audience facts. BipMe will use
        them to organize permitted evidence and show what is still unknown.
      </p>
      {error !== null && (
        <div
          className="form-error"
          role="alert"
          tabIndex={-1}
          ref={feedbackRef}
        >
          {apiProblemMessage(error)}
        </div>
      )}
      <div className="sr-only" aria-live="polite" tabIndex={-1}>
        {status}
      </div>
      <div className="form-grid">
        <label htmlFor="creator-niche">
          Niche or area of work
          <input
            id="creator-niche"
            value={niche}
            onChange={(event) => setNiche(event.target.value)}
            minLength={2}
            required
            aria-invalid={fieldError(error, 'niche') ? true : undefined}
            aria-describedby={
              fieldError(error, 'niche') ? 'niche-error' : undefined
            }
          />
          {fieldError(error, 'niche') && (
            <span id="niche-error" className="field-error">
              {fieldError(error, 'niche')}
            </span>
          )}
        </label>
        <label htmlFor="creator-audience">
          Intended audience
          <input
            id="creator-audience"
            value={audience}
            onChange={(event) => setAudience(event.target.value)}
            minLength={2}
            required
            aria-invalid={
              fieldError(error, 'intended_audience') ? true : undefined
            }
            aria-describedby={
              fieldError(error, 'intended_audience')
                ? 'audience-error'
                : undefined
            }
          />
          {fieldError(error, 'intended_audience') && (
            <span id="audience-error" className="field-error">
              {fieldError(error, 'intended_audience')}
            </span>
          )}
        </label>
      </div>
      <fieldset>
        <legend>What outcomes matter most?</legend>
        <div className="choice-grid">
          {outcomes.map((option) => (
            <label className="choice" key={option.value}>
              <input
                type="checkbox"
                checked={selectedOutcomes.includes(option.value)}
                onChange={() =>
                  toggle(selectedOutcomes, option.value, setSelectedOutcomes)
                }
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend>Which content styles feel like you?</legend>
        <div className="choice-grid">
          {styles.map((option) => (
            <label className="choice" key={option.value}>
              <input
                type="checkbox"
                checked={selectedStyles.includes(option.value)}
                onChange={() =>
                  toggle(selectedStyles, option.value, setSelectedStyles)
                }
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="consent-row">
        <input
          type="checkbox"
          checked={allowHistory}
          onChange={(event) => setAllowHistory(event.target.checked)}
        />
        <span>
          <strong>Allow processing of my personal history</strong>
          <small>
            This is a revocable, creator-owned permission. Niche discovery
            remains unavailable until its separate official-source policy gates
            pass.
          </small>
        </span>
      </label>
      <div className="form-actions">
        <button
          className="button button--primary"
          type="submit"
          disabled={saving || selectedOutcomes.length === 0}
        >
          {saving ? 'Preparing your report…' : 'Build my report'}
        </button>
        <span className="form-hint">
          No draft is required. No X search is made.
        </span>
      </div>
    </form>
  )
}

export function CreatorDashboard({
  onAnalyzeDraft,
  onSessionExpired,
  client: clientProp,
}: {
  onAnalyzeDraft: (context: DraftAnalysisContext) => void
  onSessionExpired?: () => void
  client?: ApiClient
}) {
  const client = clientProp ?? apiClient
  const [profileState, setProfileState] = useState<ProfileState | null>(null)
  const [permission, setPermission] = useState<Permission | null>(null)
  const [reportState, setReportState] = useState<ReportState | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [deleting, setDeleting] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [announcement, setAnnouncement] = useState('')
  const mounted = useRef(true)
  const mutationController = useRef<AbortController | null>(null)
  const errorRef = useRef<HTMLDivElement>(null)
  const dialogRef = useRef<HTMLElement>(null)
  const cancelDeleteRef = useRef<HTMLButtonElement>(null)
  const deleteTriggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      mutationController.current?.abort()
    }
  }, [])

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true)
      setError(null)
      try {
        const [profileResult, permissionResult, latestResult] =
          await Promise.all([
            client.profile(signal),
            client.dataPermissions(signal),
            client.latestReport(signal),
          ])
        if (!signal?.aborted && mounted.current) {
          setProfileState(profileResult)
          setPermission(permissionResult)
          setReportState(latestResult)
          setReport(latestResult.latest_report)
        }
      } catch (loadError) {
        if (!(
          loadError instanceof DOMException && loadError.name === 'AbortError'
        ))
          if (mounted.current) {
            setError(loadError)
            if (
              loadError instanceof ApiRequestError &&
              loadError.status === 401
            )
              onSessionExpired?.()
          }
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [client, onSessionExpired],
  )

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [load])

  useEffect(() => {
    if (error && !loading) errorRef.current?.focus()
  }, [error, loading])

  useEffect(() => {
    if (!confirmDelete) return
    cancelDeleteRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setConfirmDelete(false)
        requestAnimationFrame(() => deleteTriggerRef.current?.focus())
        return
      }
      if (event.key !== 'Tab') return
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
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
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [confirmDelete])

  const pageState = useMemo(
    () => dashboardLoadState(profileState?.status ?? null, reportState),
    [profileState?.status, reportState],
  )

  const regenerate = async () => {
    if (generating || deleting || mutationController.current) return
    const controller = new AbortController()
    mutationController.current = controller
    setGenerating(true)
    setError(null)
    setAnnouncement('')
    try {
      const nextReport = await client.generateReport(
        {
          data_sources:
            permission?.personal_history === 'granted'
              ? ['personal_history']
              : [],
        },
        `cod-379-refresh-${crypto.randomUUID()}`,
        controller.signal,
      )
      if (mounted.current && !controller.signal.aborted) {
        setReport(nextReport)
        setReportState({ status: 'available', latest_report: nextReport })
        setAnnouncement('Report refreshed successfully.')
      }
    } catch (generationError) {
      if (mounted.current && !isAbortError(generationError)) {
        setError(generationError)
        if (
          generationError instanceof ApiRequestError &&
          generationError.status === 401
        )
          onSessionExpired?.()
      }
    } finally {
      if (mounted.current && mutationController.current === controller)
        setGenerating(false)
      if (mutationController.current === controller)
        mutationController.current = null
    }
  }

  const deleteReports = async () => {
    if (deleting || generating || mutationController.current) return
    setConfirmDelete(false)
    const controller = new AbortController()
    mutationController.current = controller
    setDeleting(true)
    setError(null)
    setAnnouncement('')
    try {
      await client.deleteReports(controller.signal)
      await load(controller.signal)
      if (mounted.current && !controller.signal.aborted)
        setAnnouncement('Report snapshots deleted successfully.')
    } catch (deletionError) {
      if (mounted.current && !isAbortError(deletionError)) {
        setError(deletionError)
        if (
          deletionError instanceof ApiRequestError &&
          deletionError.status === 401
        )
          onSessionExpired?.()
      }
    } finally {
      if (mounted.current && mutationController.current === controller)
        setDeleting(false)
      if (mutationController.current === controller)
        mutationController.current = null
    }
  }

  if (loading)
    return (
      <div className="workspace-card">
        <StateBlock
          title="Loading your report workspace"
          body="Checking your declared context, data permissions and latest report."
        />
      </div>
    )
  if (error && !profileState) {
    const unauthenticated =
      error instanceof ApiRequestError && error.status === 401
    return (
      <div className="workspace-card">
        <StateBlock
          title={
            unauthenticated
              ? 'Sign-in required'
              : 'We could not load your report'
          }
          body={apiProblemMessage(error)}
          tone="error"
        />
      </div>
    )
  }
  if (!profileState) return null

  if (pageState === 'onboarding') {
    return (
      <OnboardingForm
        existing={profileState.profile}
        permission={permission}
        client={client}
        onComplete={(savedProfile, savedReport) => {
          setProfileState({ status: 'configured', profile: savedProfile })
          setReport(savedReport)
          setReportState({ status: 'available', latest_report: savedReport })
          setAnnouncement('Your creator report is ready.')
        }}
      />
    )
  }

  if (pageState === 'awaiting-import') {
    return (
      <div className="report-dashboard">
        <div className="workspace-card">
          <p className="card-kicker">History status</p>
          <h2>Your report is waiting for permitted history</h2>
          <p className="muted-copy">
            Your goals are saved. An importer-owned history source is not
            available yet, so BipMe will not fabricate personal patterns.
          </p>
          <div className="availability-grid">
            <StatusTile label="Creator context" value="Ready" />
            <StatusTile label="Personal history" value="Awaiting import" />
            <StatusTile label="Niche discovery" value="Unavailable" />
          </div>
          <div className="form-actions">
            <button
              className="button button--primary"
              type="button"
              onClick={regenerate}
              disabled={generating}
            >
              {generating ? 'Building…' : 'Build available report'}
            </button>
            <button
              className="button button--secondary"
              type="button"
              disabled
              aria-describedby="draft-unavailable-description"
            >
              Analyze a Draft
            </button>
            <p id="draft-unavailable-description" className="form-hint">
              Draft analysis becomes available after a report snapshot is ready.
            </p>
          </div>
          {error !== null && (
            <div className="form-error" role="alert">
              {apiProblemMessage(error)}
            </div>
          )}
        </div>
      </div>
    )
  }

  if (!report) return null
  const stale = reportIsStale(report)
  const nicheState = nicheAvailability(report)
  const personalHistoryStatus = permissionRecord(
    report,
    'personal_history',
  )?.status

  return (
    <div className="report-dashboard" aria-busy={generating || deleting}>
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
      {error !== null && (
        <div className="form-error" role="alert" tabIndex={-1} ref={errorRef}>
          {apiProblemMessage(error)}
        </div>
      )}
      <section className="report-hero" aria-labelledby="report-title">
        <div>
          <p className="eyebrow">
            <span className="eyebrow__dot" aria-hidden="true" /> Creator
            Intelligence Report
          </p>
          <h2 id="report-title">A grounded view of what you can learn next</h2>
          <p className="muted-copy">
            Built from your declared context and the evidence BipMe was
            permitted to process. It describes associations and gaps, not
            guaranteed reach.
          </p>
        </div>
        <div className="report-hero__actions">
          <span className="coverage-badge">
            {reportCoverageLabel(report.coverage)}
          </span>
          <button
            className="button button--primary"
            type="button"
            onClick={() => onAnalyzeDraft(draftContext(profileState, report))}
          >
            Analyze a Draft
          </button>
        </div>
      </section>
      {stale && (
        <StateBlock
          title="Some evidence is historical"
          body="This report includes older or historical observations. Treat opportunities as experiments, not current niche trends."
        />
      )}
      <div className="availability-grid">
        <StatusTile label="Generated" value={dateLabel(report.generated_at)} />
        <StatusTile label="Evidence as of" value={dateLabel(report.as_of)} />
        <StatusTile
          label="Personal history"
          value={String(personalHistoryStatus ?? 'unknown').replaceAll(
            '_',
            ' ',
          )}
        />
        <StatusTile label="Niche discovery" value={nicheState.label} />
      </div>
      <ReportEvidenceSection report={report} />
      <section
        className="report-footer-card"
        aria-labelledby="limitations-title"
      >
        <div>
          <p className="card-kicker">Boundaries and freshness</p>
          <h2 id="limitations-title">What this report does not claim</h2>
        </div>
        <ul>
          {report.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
        <div className="form-actions">
          <button
            className="button button--secondary"
            type="button"
            onClick={regenerate}
            disabled={generating}
          >
            {generating ? 'Refreshing…' : 'Refresh report'}
          </button>
          <button
            ref={deleteTriggerRef}
            className="button button--danger"
            type="button"
            onClick={() => setConfirmDelete(true)}
            disabled={deleting}
          >
            {deleting ? 'Deleting…' : 'Delete report snapshots'}
          </button>
        </div>
      </section>
      {confirmDelete && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="workspace-card confirmation-dialog"
            role="alertdialog"
            aria-modal="true"
            ref={dialogRef}
            aria-labelledby="delete-report-title"
            aria-describedby="delete-report-description"
          >
            <h2 id="delete-report-title">Delete report snapshots?</h2>
            <p id="delete-report-description">
              This permanently removes BipMe report snapshots. Underlying
              imported source records are retained by their source owner and are
              not deleted by this action.
            </p>
            <div className="form-actions">
              <button
                ref={cancelDeleteRef}
                className="button button--secondary"
                type="button"
                onClick={() => {
                  setConfirmDelete(false)
                  requestAnimationFrame(() => deleteTriggerRef.current?.focus())
                }}
              >
                Cancel
              </button>
              <button
                className="button button--danger"
                type="button"
                onClick={deleteReports}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Delete snapshots'}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function StateBlock({
  title,
  body,
  tone = 'neutral',
}: {
  title: string
  body: string
  tone?: 'neutral' | 'error'
}) {
  return (
    <div
      className={`dashboard-state dashboard-state--${tone}`}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      <span aria-hidden="true">{tone === 'error' ? '!' : '◌'}</span>
      <div>
        <h2>{title}</h2>
        <p>{body}</p>
      </div>
    </div>
  )
}
