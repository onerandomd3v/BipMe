import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  apiClient,
  type ApiClient,
  type BaselineQuery,
} from './api/client'
import type { components } from './api/generated/schema'
import { hasSyntheticProvenance, SyntheticDemoNotice } from './syntheticDemo'

type EvidencePage = components['schemas']['EvidencePage']
type ImportPage = components['schemas']['ImportPage']
type PostEvidence = components['schemas']['PostEvidence']
type CreatorBaseline = components['schemas']['CreatorBaselineResponse']
type Observation = components['schemas']['MetricObservationEvidence']
type MetricIdentity = components['schemas']['MetricIdentity']
type MetricDimension = MetricIdentity & {
  key: string
  coverage: string[]
  eligible: boolean
}
type LoadState = 'loading' | 'ready' | 'empty' | 'error'
type Disclosure = PostEvidence['disclosure']
type Freshness = PostEvidence['freshness']
type Source = PostEvidence['source']

const DISCLOSURES = [
  'permitted',
  'permission_required',
  'source_policy_blocked',
  'not_known_at_cutoff',
] as const
const FRESHNESS_VALUES = ['recorded', 'unknown', 'not_known_at_cutoff'] as const
const SOURCES = [
  'authorized_x_api',
  'archive',
  'unknown',
  'synthetic_demo',
] as const
const SAFE_SOURCE_HOSTS = new Set(['x.com', 'twitter.com'])
const SOURCE_POST_PATH = /^\/i\/status\/[1-9][0-9]{0,19}$/

export function CreatorHistoryDashboard({
  client = apiClient,
  onSessionExpired,
}: {
  client?: ApiClient
  onSessionExpired?: () => void
}) {
  const [loadState, setLoadState] = useState<LoadState>('loading')
  const [imports, setImports] = useState<ImportPage | null>(null)
  const [page, setPage] = useState<EvidencePage | null>(null)
  const [posts, setPosts] = useState<PostEvidence[]>([])
  const [historyError, setHistoryError] = useState<unknown>(null)
  const [baseline, setBaseline] = useState<CreatorBaseline | null>(null)
  const [baselineError, setBaselineError] = useState<unknown>(null)
  const [baselineLoading, setBaselineLoading] = useState(false)
  const [selectedMetricKey, setSelectedMetricKey] = useState('')
  const [baselineRetry, setBaselineRetry] = useState(0)
  const [loadingMore, setLoadingMore] = useState(false)
  const mounted = useRef(true)
  const loadMoreController = useRef<AbortController | null>(null)
  const baselineController = useRef<AbortController | null>(null)
  const sessionExpiredRef = useRef(onSessionExpired)

  useEffect(() => {
    sessionExpiredRef.current = onSessionExpired
  }, [onSessionExpired])

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    setLoadState('loading')
    setHistoryError(null)
    setBaseline(null)
    setBaselineError(null)
    setSelectedMetricKey('')
    void Promise.all([
      client.historyImports(50, controller.signal),
      client.historyPosts({ limit: 20 }, controller.signal),
    ])
      .then(([nextImports, nextPage]) => {
        if (controller.signal.aborted || !mounted.current) return
        setImports(nextImports)
        setPage(nextPage)
        setPosts(nextPage.items)
        setLoadState(nextPage.items.length > 0 ? 'ready' : 'empty')
      })
      .catch((nextError: unknown) => {
        if (controller.signal.aborted || !mounted.current) return
        setHistoryError(nextError)
        if (isAuthenticationFailure(nextError)) sessionExpiredRef.current?.()
        setLoadState('error')
      })
    return () => {
      mounted.current = false
      loadMoreController.current?.abort()
      baselineController.current?.abort()
      controller.abort()
    }
  }, [client])

  const dimensions = useMemo(() => metricDimensions(posts), [posts])
  const eligibleDimensions = useMemo(
    () => dimensions.filter(({ eligible }) => eligible),
    [dimensions],
  )
  const selectedMetric = useMemo(
    () => dimensions.find(({ key }) => key === selectedMetricKey),
    [dimensions, selectedMetricKey],
  )

  useEffect(() => {
    if (
      selectedMetricKey &&
      dimensions.some(({ key }) => key === selectedMetricKey)
    )
      return
    setSelectedMetricKey(dimensions[0]?.key ?? '')
  }, [dimensions, selectedMetricKey])

  useEffect(() => {
    if (!page || !selectedMetric || loadState === 'loading') return
    const controller = new AbortController()
    baselineController.current?.abort()
    baselineController.current = controller
    setBaselineLoading(true)
    setBaselineError(null)
    setBaseline(null)
    const query: BaselineQuery = {
      metric: selectedMetric.metric,
      definition: selectedMetric.definition,
      unit: selectedMetric.unit,
      window_kind: selectedMetric.window_kind,
      window_key: selectedMetric.window_key,
      as_of: page.as_of,
    }
    void client
      .baseline(query, controller.signal)
      .then((nextBaseline) => {
        if (controller.signal.aborted || !mounted.current) return
        const identityMatches = matchesMetricIdentity(
          nextBaseline?.metric,
          query,
        )
        if (!identityMatches || !isRenderableBaseline(nextBaseline)) {
          setBaselineError(
            new ApiRequestError({
              status: null,
              code: 'baseline_response_invalid',
              message: identityMatches
                ? 'The baseline response was unavailable in a safe format.'
                : 'The baseline response did not match the selected metric series.',
            }),
          )
          return
        }
        setBaseline(nextBaseline)
      })
      .catch((nextError: unknown) => {
        if (!controller.signal.aborted && mounted.current) {
          setBaselineError(nextError)
          if (isAuthenticationFailure(nextError)) sessionExpiredRef.current?.()
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && mounted.current)
          setBaselineLoading(false)
      })
    return () => controller.abort()
  }, [client, loadState, page, selectedMetric, baselineRetry])

  const loadMore = async () => {
    if (!page?.next_cursor || loadingMore) return
    const controller = new AbortController()
    loadMoreController.current = controller
    setLoadingMore(true)
    try {
      const nextPage = await client.historyPosts(
        { limit: 20, cursor: page.next_cursor },
        controller.signal,
      )
      if (!mounted.current) return
      setPage(nextPage)
      setPosts((current) => {
        const ids = new Set(current.map(({ id }) => id))
        return [...current, ...nextPage.items.filter(({ id }) => !ids.has(id))]
      })
    } catch (nextError) {
      if (mounted.current && !controller.signal.aborted) {
        setHistoryError(nextError)
        if (isAuthenticationFailure(nextError)) sessionExpiredRef.current?.()
      }
    } finally {
      if (loadMoreController.current === controller) {
        loadMoreController.current = null
        if (mounted.current) setLoadingMore(false)
      }
    }
  }

  if (loadState === 'loading')
    return (
      <HistoryState
        title="Loading your content history"
        body="Reading permitted history and import status."
      />
    )
  if (loadState === 'error')
    return (
      <HistoryState
        title={errorTitle(historyError)}
        body={errorMessage(historyError)}
        tone="error"
      />
    )
  const latestImport = imports?.items[0] ?? null
  return (
    <div className="history-dashboard" aria-busy={loadingMore}>
      <section
        className="history-overview"
        aria-labelledby="history-overview-title"
      >
        <div>
          <p className="card-kicker">Your Content History</p>
          <h2 id="history-overview-title">
            Evidence you are permitted to inspect
          </h2>
          <p className="muted-copy">
            Observed values and creator-relative distributions are shown with
            their source, measurement window and known limitations.
          </p>
        </div>
        <div className="history-summary-grid">
          <SummaryTile
            label="Latest import posts"
            value={
              latestImport
                ? countLabel(latestImport.imported_posts)
                : 'Not reported'
            }
          />
          <SummaryTile
            label="Import status"
            value={
              latestImport
                ? importStatusLabel(latestImport.status)
                : 'No import record'
            }
          />
          <SummaryTile
            label="Last updated"
            value={
              latestImport
                ? dateLabel(
                    latestImport.completed_at ?? latestImport.started_at,
                  )
                : 'Not available'
            }
          />
          <SummaryTile
            label="Evidence cutoff"
            value={page ? dateLabel(page.as_of) : 'Not available'}
          />
        </div>
      </section>
      {hasSyntheticProvenance({ latestImport, page }) && (
        <SyntheticDemoNotice>
          History and observations are from the isolated backend seed.
        </SyntheticDemoNotice>
      )}
      {latestImport && latestImport.status !== 'complete' && (
        <section className="history-notice" role="status">
          <strong>{importStatusLabel(latestImport.status)}</strong>
          <span>
            {countLabel(latestImport.imported_posts)} of{' '}
            {countLabel(latestImport.requested_posts)} requested posts are
            currently available.
            {latestImport.next_page_available
              ? ' More source pages may be available.'
              : ''}
          </span>
        </section>
      )}
      <section className="history-section" aria-labelledby="dimensions-title">
        <div className="section-heading">
          <div>
            <p className="card-kicker">Observed metric coverage</p>
            <h2 id="dimensions-title">Supported metric dimensions</h2>
          </div>
        </div>
        {dimensions.length === 0 ? (
          <p className="muted-copy">
            No metric identities were returned for this history snapshot.
          </p>
        ) : (
          <>
            <p className="form-hint">
              These series were discovered in the currently loaded history
              pages; they are not a complete server-side catalogue.
            </p>
            <ul className="metric-dimension-list">
              {dimensions.map((dimension) => (
                <li key={dimension.key}>
                  <strong>{dimension.metric}</strong>
                  <span>
                    {dimension.definition} · {dimension.unit} ·{' '}
                    {dimension.window_kind}:{dimension.window_key}
                    {' · '}
                    {dimension.coverage.join(', ')}
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <BaselineSection
        baseline={baseline}
        baselineError={baselineError}
        baselineLoading={baselineLoading}
        dimensions={eligibleDimensions}
        selectedMetricKey={selectedMetricKey}
        onMetricChange={setSelectedMetricKey}
        onRetry={() => setBaselineRetry((value) => value + 1)}
      />
      <section className="history-section" aria-labelledby="posts-title">
        <div className="section-heading">
          <div>
            <p className="card-kicker">Authorized history</p>
            <h2 id="posts-title">Posts and observation caveats</h2>
          </div>
          <span className="section-count">{posts.length} loaded</span>
        </div>
        {posts.length === 0 ? (
          <p className="muted-copy">
            No permitted history posts are available at this cutoff.
          </p>
        ) : (
          <div className="history-post-list">
            {posts.map((post) => (
              <PostCard key={post.id} post={post} />
            ))}
          </div>
        )}
        {page?.next_cursor && (
          <button
            className="button button--secondary history-load-more"
            type="button"
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? 'Loading…' : 'Load more history'}
          </button>
        )}
        {historyError !== null && (
          <p className="form-error" role="alert">
            {errorMessage(historyError)}
          </p>
        )}
      </section>
    </div>
  )
}

function BaselineSection({
  baseline,
  baselineError,
  baselineLoading,
  dimensions,
  selectedMetricKey,
  onMetricChange,
  onRetry,
}: {
  baseline: CreatorBaseline | null
  baselineError: unknown
  baselineLoading: boolean
  dimensions: MetricDimension[]
  selectedMetricKey: string
  onMetricChange: (value: string) => void
  onRetry: () => void
}) {
  return (
    <section className="history-section" aria-labelledby="baseline-title">
      <div className="section-heading">
        <div>
          <p className="card-kicker">Creator-relative baseline</p>
          <h2 id="baseline-title">
            Derived distribution for a selected series
          </h2>
        </div>
      </div>
      {dimensions.length === 0 ? (
        <p className="muted-copy">
          A baseline requires an observed metric series with an exact
          definition, unit and measurement window. No eligible series is
          available.
        </p>
      ) : (
        <>
          <label htmlFor="baseline-metric">
            Metric series discovered in loaded history
          </label>
          <select
            id="baseline-metric"
            value={selectedMetricKey}
            onChange={(event) => onMetricChange(event.target.value)}
          >
            {dimensions.map((dimension) => (
              <option key={dimension.key} value={dimension.key}>
                {dimension.metric} · {dimension.definition} · {dimension.unit} ·{' '}
                {dimension.window_kind}:{dimension.window_key}
              </option>
            ))}
          </select>
          {baselineLoading && (
            <p className="muted-copy" role="status">
              Loading the selected creator-relative distribution…
            </p>
          )}
          {baselineError && (
            <div className="history-notice" role="alert">
              <strong>{baselineErrorTitle(baselineError)}</strong>
              <span>{baselineErrorMessage(baselineError)}</span>
              <button
                className="button button--secondary"
                type="button"
                onClick={onRetry}
              >
                Retry baseline
              </button>
            </div>
          )}
          {baseline && <BaselineContent baseline={baseline} />}
        </>
      )}
    </section>
  )
}

function BaselineContent({ baseline }: { baseline: CreatorBaseline }) {
  return (
    <>
      <div className="section-heading">
        <div>
          <h3>
            {baseline.metric.metric} · {baseline.metric.window_kind}:
            {baseline.metric.window_key}
          </h3>
          <p className="muted-copy">
            {baseline.metric.definition} · {baseline.metric.unit}
          </p>
        </div>
        <span
          className={`evidence-badge evidence-badge--${baseline.evidence_strength.toLowerCase()}`}
        >
          {baseline.evidence_strength} evidence
        </span>
      </div>
      <p className="form-hint">
        Percentiles are creator-relative derived statistics, not directly
        observed values or causal performance guarantees.
      </p>
      <div className="baseline-summary">
        <SummaryTile
          label="Eligible posts"
          value={String(baseline.eligible_post_count)}
        />
        <SummaryTile
          label="Effective sample"
          value={String(baseline.effective_sample_size)}
        />
        <SummaryTile
          label="Repeatability"
          value={formatRatio(baseline.repeatability_ratio)}
        />
        <SummaryTile
          label="Outliers"
          value={
            baseline.outlier_count === null
              ? 'Unknown'
              : String(baseline.outlier_count)
          }
        />
      </div>
      {baseline.statistics ? (
        <dl className="percentile-grid">
          {(['p10', 'p25', 'p50', 'p75', 'p90'] as const).map((key) => (
            <div key={key}>
              <dt>{key.toUpperCase()}</dt>
              <dd>{formatMetric(baseline.statistics![key])}</dd>
            </div>
          ))}
          <div>
            <dt>Minimum</dt>
            <dd>{formatMetric(baseline.statistics!.minimum)}</dd>
          </div>
          <div>
            <dt>Maximum</dt>
            <dd>{formatMetric(baseline.statistics!.maximum)}</dd>
          </div>
          <div>
            <dt>IQR</dt>
            <dd>{formatMetric(baseline.statistics!.iqr)}</dd>
          </div>
          <div>
            <dt>Consistency</dt>
            <dd>{formatMetric(baseline.statistics!.consistency_ratio)}</dd>
          </div>
          <div>
            <dt>Upper outliers</dt>
            <dd>{String(baseline.statistics!.upper_outlier_count)}</dd>
          </div>
          <div>
            <dt>Outlier-adjusted P50</dt>
            <dd>{formatMetric(baseline.statistics!.outlier_adjusted_p50)}</dd>
          </div>
        </dl>
      ) : (
        <p className="muted-copy">
          Insufficient eligible observations support percentile statistics.
        </p>
      )}
      <p>
        <strong>Excluded posts</strong>
      </p>
      {Object.keys(baseline.exclusions).length === 0 ? (
        <p className="muted-copy">
          No posts were excluded from this calculation.
        </p>
      ) : (
        <ul className="limitation-list">
          {Object.entries(baseline.exclusions).map(([reason, count]) => (
            <li key={reason}>
              {reason}: {count}
            </li>
          ))}
        </ul>
      )}
      {baseline.limitations.length > 0 && (
        <ul className="limitation-list">
          {baseline.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </>
  )
}

function PostCard({ post }: { post: PostEvidence }) {
  const disclosure = isDisclosure(post.disclosure) ? post.disclosure : null
  const disclosedText =
    disclosure === 'permitted' && typeof post.text === 'string'
      ? post.text
      : null
  const disclosedUrl =
    disclosure === 'permitted' ? safeSourceUrl(post.source_url) : null
  const observations = canDisplayObservations(disclosure)
    ? Array.isArray(post.observations)
      ? post.observations.filter(isRenderableObservation)
      : []
    : []
  const sourceObservedAt =
    disclosure === 'permitted' ? dateLabelValue(post.source_observed_at) : null
  return (
    <article className="history-post-card">
      <div className="history-post-card__heading">
        <div>
          <p className="card-kicker">{sourceLabel(post.source)}</p>
          <h3>{dateLabel(post.published_at)}</h3>
        </div>
        <span className="disclosure-badge">{disclosureLabel(disclosure)}</span>
      </div>
      {disclosedText ? (
        <p className="history-post-text">{disclosedText}</p>
      ) : (
        <p className="muted-copy">
          Post content is unavailable under the current disclosure state.
        </p>
      )}
      {disclosedUrl && (
        <a
          className="history-post-link"
          href={disclosedUrl}
          target="_blank"
          rel="noreferrer"
        >
          Open disclosed source post
        </a>
      )}
      <p className="form-hint">
        Snapshot freshness: {freshnessLabel(post.freshness)}
        {sourceObservedAt
          ? ` · source observed ${dateLabel(sourceObservedAt)}`
          : ''}
      </p>
      <div className="observation-list">
        {observations.length === 0 ? (
          <span className="muted-copy">No observations were returned.</span>
        ) : (
          observations.map((observation) => (
            <ObservationRow key={observation.id} observation={observation} />
          ))
        )}
      </div>
      {post.observations_truncated && (
        <p className="form-hint">Only the bounded observation set is shown.</p>
      )}
    </article>
  )
}
function ObservationRow({ observation }: { observation: Observation }) {
  const value =
    observation.state === 'observed' &&
    isSerializedDecimal(observation.metric_value)
      ? observation.metric_value
      : observationStateLabel(observation)
  return (
    <div className="observation-row">
      <strong>{observation.metric_name}</strong>
      <span>{value}</span>
      <small>
        {observation.metric_definition} · {observation.metric_unit} ·{' '}
        {observation.window_kind}:{observation.window_key} · observed{' '}
        {dateLabel(observation.observed_at)} · age{' '}
        {ageLabel(observation.observed_age_seconds)} ·{' '}
        {sourceLabel(observation.source)}
      </small>
    </div>
  )
}
function HistoryState({
  title,
  body,
  tone = 'neutral',
}: {
  title: string
  body: string
  tone?: 'neutral' | 'error'
}) {
  return (
    <div className="workspace-card">
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
    </div>
  )
}
function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-tile">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
function metricDimensions(posts: PostEvidence[]): MetricDimension[] {
  const dimensions = new Map<string, MetricDimension>()
  posts.forEach((post) => {
    if (!canDisplayObservations(post.disclosure)) return
    const observations = Array.isArray(post.observations)
      ? post.observations.filter(isRenderableObservation)
      : []
    observations.forEach((item) => {
      const key = metricKey(item)
      const existing = dimensions.get(key)
      const coverage = observationCoverageLabel(item)
      if (existing) {
        if (!existing.coverage.includes(coverage))
          existing.coverage.push(coverage)
        existing.eligible ||= isEligibleMetricValue(item)
      } else {
        dimensions.set(key, {
          key,
          metric: item.metric_name,
          definition: item.metric_definition,
          unit: item.metric_unit,
          window_kind: item.window_kind,
          window_key: item.window_key,
          coverage: [coverage],
          eligible: isEligibleMetricValue(item),
        })
      }
    })
  })
  return [...dimensions.values()]
}
function metricKey(item: MetricIdentity | Observation) {
  const metric = 'metric' in item ? item.metric : item.metric_name
  const definition =
    'definition' in item ? item.definition : item.metric_definition
  const unit = 'unit' in item ? item.unit : item.metric_unit
  return JSON.stringify([
    metric,
    definition,
    unit,
    item.window_kind,
    item.window_key,
  ])
}
function dateLabelValue(value: unknown): string | null {
  if (typeof value !== 'string' || value.length === 0) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : value
}
function dateLabel(value: unknown) {
  const safeValue = dateLabelValue(value)
  return safeValue
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(new Date(safeValue))
    : 'Not available'
}
function formatMetric(value: number | null | undefined) {
  return value === null || value === undefined || !Number.isFinite(value)
    ? 'Unavailable'
    : new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(
        value,
      )
}
function formatRatio(value: number | null) {
  return value === null ? 'Unavailable' : formatMetric(value)
}
function countLabel(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value)
    ? String(value)
    : 'Unavailable'
}
function ageLabel(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return 'unknown'
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`
  return `${(seconds / 86400).toFixed(1)}d`
}
function sourceLabel(source: unknown) {
  return source === 'authorized_x_api'
    ? 'Official X API'
    : source === 'archive'
      ? 'Creator archive'
      : source === 'synthetic_demo'
        ? 'Synthetic demonstration data'
        : 'Source unknown'
}
function isDisclosure(value: unknown): value is Disclosure {
  return (
    typeof value === 'string' &&
    (DISCLOSURES as readonly string[]).includes(value)
  )
}
function isFreshness(value: unknown): value is Freshness {
  return (
    typeof value === 'string' &&
    (FRESHNESS_VALUES as readonly string[]).includes(value)
  )
}
function isSource(value: unknown): value is Source {
  return (
    typeof value === 'string' && (SOURCES as readonly string[]).includes(value)
  )
}
function freshnessLabel(value: unknown) {
  return isFreshness(value) ? value.replaceAll('_', ' ') : 'unknown'
}
function disclosureLabel(value: Disclosure | null) {
  return value === 'permitted'
    ? 'Content disclosed'
    : value
      ? value.replaceAll('_', ' ')
      : 'Content unavailable'
}
function canDisplayObservations(value: Disclosure | null) {
  return value === 'permitted' || value === 'not_known_at_cutoff'
}
function safeSourceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    if (
      url.protocol !== 'https:' ||
      url.username ||
      url.password ||
      url.port ||
      url.search ||
      url.hash ||
      !SAFE_SOURCE_HOSTS.has(url.hostname.toLowerCase()) ||
      !SOURCE_POST_PATH.test(url.pathname)
    )
      return null
    return url.href
  } catch {
    return null
  }
}
function isSerializedDecimal(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value)
  )
}
function isEligibleMetricValue(item: Observation) {
  return item.state === 'observed' && isSerializedDecimal(item.metric_value)
}
function observationCoverageLabel(item: Observation) {
  if (item.state === 'observed')
    return isSerializedDecimal(item.metric_value)
      ? 'Observed'
      : 'Unknown / unavailable'
  if (item.state === 'missing')
    return `Missing${item.provenance?.missing_reason ? ` (${item.provenance.missing_reason})` : ''}`
  if (item.state === 'invalid') return 'Invalid'
  return 'Unknown / unavailable'
}
function observationStateLabel(item: Observation) {
  if (item.state === 'missing')
    return `Missing${item.provenance?.missing_reason ? ` (${item.provenance.missing_reason})` : ''}`
  if (item.state === 'invalid') return 'Invalid value'
  return 'Unknown / unavailable'
}
function isRenderableObservation(value: unknown): value is Observation {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return (
    typeof item.id === 'string' &&
    typeof item.metric_name === 'string' &&
    typeof item.metric_definition === 'string' &&
    typeof item.metric_unit === 'string' &&
    (item.state === 'observed' ||
      item.state === 'missing' ||
      item.state === 'invalid') &&
    (item.window_kind === 'mature_cumulative' ||
      item.window_kind === 'age_aligned') &&
    typeof item.window_key === 'string' &&
    dateLabelValue(item.observed_at) !== null &&
    typeof item.observed_age_seconds === 'number' &&
    Number.isFinite(item.observed_age_seconds) &&
    isSource(item.source)
  )
}
function matchesMetricIdentity(value: unknown, expected: BaselineQuery) {
  if (!value || typeof value !== 'object') return false
  const metric = value as Record<string, unknown>
  return (
    metric.metric === expected.metric &&
    metric.definition === expected.definition &&
    metric.unit === expected.unit &&
    metric.window_kind === expected.window_kind &&
    metric.window_key === expected.window_key
  )
}
function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}
function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || isFiniteNumber(value)
}
function isRenderableBaseline(value: unknown): value is CreatorBaseline {
  if (!value || typeof value !== 'object') return false
  const baseline = value as Record<string, unknown>
  const metric = baseline.metric
  const statistics = baseline.statistics
  const exclusions = baseline.exclusions
  const limitations = baseline.limitations
  if (!metric || typeof metric !== 'object') return false
  const identity = metric as Record<string, unknown>
  if (
    typeof identity.metric !== 'string' ||
    typeof identity.definition !== 'string' ||
    typeof identity.unit !== 'string' ||
    (identity.window_kind !== 'mature_cumulative' &&
      identity.window_kind !== 'age_aligned') ||
    typeof identity.window_key !== 'string' ||
    typeof baseline.calculation_version !== 'string' ||
    dateLabelValue(baseline.as_of) === null ||
    !isFiniteNumber(baseline.eligible_post_count) ||
    !isFiniteNumber(baseline.effective_sample_size) ||
    !['High', 'Moderate', 'Low', 'Insufficient'].includes(
      String(baseline.evidence_strength),
    ) ||
    !isNullableFiniteNumber(baseline.repeatability_ratio) ||
    !(
      baseline.outlier_count === null || isFiniteNumber(baseline.outlier_count)
    ) ||
    !(
      baseline.upper_outlier_count === null ||
      isFiniteNumber(baseline.upper_outlier_count)
    ) ||
    !Array.isArray(baseline.supporting_post_ids) ||
    !baseline.supporting_post_ids.every((item) => typeof item === 'string') ||
    !exclusions ||
    typeof exclusions !== 'object' ||
    Array.isArray(exclusions) ||
    !Object.values(exclusions).every(isFiniteNumber) ||
    !Array.isArray(limitations) ||
    !limitations.every((item) => typeof item === 'string')
  )
    return false
  if (statistics === null) return true
  if (!statistics || typeof statistics !== 'object') return false
  const stats = statistics as Record<string, unknown>
  return (
    [
      'p10',
      'p25',
      'p50',
      'p75',
      'p90',
      'minimum',
      'maximum',
      'iqr',
      'consistency_ratio',
      'outlier_count',
      'upper_outlier_count',
      'outlier_adjusted_p50',
      'median_shift_in_iqr',
      'maximum_weight_share',
    ].every((key) => isFiniteNumber(stats[key])) &&
    isNullableFiniteNumber(stats.dispersion_ratio) &&
    isNullableFiniteNumber(stats.target_percentile_rank)
  )
}
function importStatusLabel(value: unknown) {
  return value === 'partial'
    ? 'Partial import'
    : value === 'running'
      ? 'Import in progress'
      : value === 'unavailable'
        ? 'Import unavailable'
        : 'Import complete'
}
function isAuthenticationFailure(error: unknown) {
  return (
    error instanceof ApiRequestError &&
    (error.status === 401 ||
      (error.status === 403 &&
        [
          'csrf_validation_failed',
          'session_invalid',
          'session_expired',
        ].includes(error.code)))
  )
}
function errorTitle(error: unknown) {
  return error instanceof ApiRequestError && error.status === 429
    ? 'History requests are rate-limited'
    : 'We could not load your history'
}
function errorMessage(error: unknown) {
  if (error instanceof ApiRequestError && error.status === 401)
    return 'Sign in again to view your private creator history.'
  if (error instanceof ApiRequestError && error.status === 403)
    return 'This history is not permitted for the current creator session.'
  if (error instanceof ApiRequestError && error.status === 429)
    return 'Try again later; BipMe did not retry automatically.'
  return error instanceof ApiRequestError
    ? error.message
    : 'The history service could not be reached. Your existing data has not been changed.'
}
function baselineErrorTitle(error: unknown) {
  if (error instanceof ApiRequestError && error.status === 429)
    return 'Baseline requests are rate-limited'
  if (error instanceof ApiRequestError && error.status === 422)
    return 'This metric series cannot be analyzed'
  if (error instanceof ApiRequestError && error.status === 503)
    return 'Baseline analysis is temporarily unavailable'
  if (error instanceof ApiRequestError && error.status === 401)
    return 'Your session expired'
  return 'Baseline analysis is unavailable'
}
function baselineErrorMessage(error: unknown) {
  if (error instanceof ApiRequestError && error.status === 429)
    return 'Try again later; the loaded history remains available.'
  if (error instanceof ApiRequestError && error.status === 422)
    return 'The selected metric or measurement window is unsupported for this snapshot.'
  if (error instanceof ApiRequestError && error.status === 503)
    return 'The history and observations remain available while analysis recovers.'
  if (error instanceof ApiRequestError && error.status === 401)
    return 'Sign in again to calculate a private baseline.'
  return error instanceof ApiRequestError
    ? error.message
    : 'The selected distribution could not be calculated.'
}
