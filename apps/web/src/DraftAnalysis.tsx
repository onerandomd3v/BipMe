import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import type { components } from './api/generated/schema'
import { ApiRequestError, apiClient, type ApiClient } from './api/client'
import type { DraftAnalysisContext } from './dashboardModel'

type DraftRequest = components['schemas']['DraftAnalysisRequest']
type DraftResponse = components['schemas']['DraftAnalysisResponse']
type PostEvidence = components['schemas']['PostEvidence']
type EvidencePage = components['schemas']['EvidencePage']
type EvidencePageEnvelope = Omit<EvidencePage, 'items'> & { items: unknown[] }

type DraftStatus =
  | 'idle'
  | 'validating'
  | 'loading'
  | 'success'
  | 'insufficient-evidence'
  | 'rate-limited'
  | 'unauthorized'
  | 'unavailable'
  | 'error'

type Props = {
  context: DraftAnalysisContext | null
  onSessionExpired?: () => void
  onBackToDashboard?: () => void
  client?: ApiClient
}

const MAX_TEXT_LENGTH = 10_000
const MAX_TOPIC_LENGTH = 120

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

const SOURCES = ['authorized_x_api', 'archive', 'unknown'] as const
const DISCLOSURES = [
  'permitted',
  'permission_required',
  'source_policy_blocked',
  'not_known_at_cutoff',
] as const
const FRESHNESS = ['recorded', 'unknown', 'not_known_at_cutoff'] as const
const EVIDENCE_STRENGTH = ['High', 'Moderate', 'Low', 'Insufficient'] as const
const METRIC_STATES = ['observed', 'missing', 'invalid'] as const

function oneOf<T extends readonly string[]>(
  value: unknown,
  values: T,
): value is T[number] {
  return typeof value === 'string' && values.includes(value as T[number])
}

function finiteNumber(
  value: unknown,
  nullable = false,
): value is number | null {
  return (
    (nullable && value === null) ||
    (typeof value === 'number' && Number.isFinite(value))
  )
}

function validDate(value: unknown, nullable = false): value is string | null {
  return (
    (nullable && value === null) ||
    (typeof value === 'string' &&
      value.length > 0 &&
      !Number.isNaN(new Date(value).getTime()))
  )
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function countPairs(value: unknown): value is [string, number][] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        Array.isArray(item) &&
        item.length === 2 &&
        typeof item[0] === 'string' &&
        finiteNumber(item[1]),
    )
  )
}

function validStatistics(value: unknown): boolean {
  if (value === null) return true
  if (!isRecord(value)) return false
  return (
    [
      'consistency_ratio',
      'iqr',
      'maximum',
      'maximum_weight_share',
      'median_shift_in_iqr',
      'minimum',
      'outlier_adjusted_p50',
      'outlier_count',
      'p10',
      'p25',
      'p50',
      'p75',
      'p90',
      'upper_outlier_count',
    ].every((key) => finiteNumber(value[key])) &&
    finiteNumber(value.dispersion_ratio, true) &&
    finiteNumber(value.target_percentile_rank, true)
  )
}

function validAcceptedHypothesis(value: unknown): boolean {
  if (value === null) return true
  return (
    isRecord(value) &&
    oneOf(value.expected_direction, [
      'higher',
      'lower',
      'no_direction',
    ] as const) &&
    ['metric', 'metric_definition', 'question', 'unit', 'window_key'].every(
      (key) => typeof value[key] === 'string',
    ) &&
    oneOf(value.window_kind, ['mature_cumulative', 'age_aligned'] as const)
  )
}

function validComparable(value: unknown): boolean {
  if (
    !isRecord(value) ||
    typeof value.post_id !== 'string' ||
    !finiteNumber(value.relevance) ||
    !finiteNumber(value.retrieval_position) ||
    !stringArray(value.inclusion_reasons) ||
    !isRecord(value.components)
  )
    return false
  const components = value.components
  return ['semantic', 'topic', 'intent', 'format', 'structure'].every((key) =>
    finiteNumber(components[key], true),
  )
}

function validMetric(value: unknown): boolean {
  if (
    !isRecord(value) ||
    typeof value.metric !== 'string' ||
    typeof value.metric_definition !== 'string' ||
    typeof value.window !== 'string' ||
    !oneOf(value.evidence_strength, EVIDENCE_STRENGTH) ||
    !finiteNumber(value.coverage) ||
    !finiteNumber(value.effective_sample_size) ||
    !finiteNumber(value.eligible_post_count) ||
    !countPairs(value.exclusion_counts) ||
    !stringArray(value.limitations) ||
    !stringArray(value.supporting_post_ids) ||
    !validStatistics(value.statistics)
  )
    return false
  if (value.outlook !== null) {
    if (!isRecord(value.outlook)) return false
    const outlook = value.outlook
    if (
      !stringArray(outlook.comparable_post_ids) ||
      !['effective_sample_size', 'lower_p25', 'median_p50', 'upper_p75'].every(
        (key) => finiteNumber(outlook[key]),
      ) ||
      typeof outlook.kind !== 'string'
    )
      return false
  }
  return true
}

function validObservation(value: unknown): boolean {
  return (
    isRecord(value) &&
    oneOf(value.kind, [
      'repeatability',
      'outlier',
      'coverage_limitation',
    ] as const) &&
    oneOf(value.evidence_strength, EVIDENCE_STRENGTH) &&
    typeof value.explanation === 'string' &&
    (value.metric === null || typeof value.metric === 'string') &&
    (value.metric_definition === null ||
      typeof value.metric_definition === 'string') &&
    (value.window === null || typeof value.window === 'string') &&
    stringArray(value.supporting_post_ids) &&
    stringArray(value.limitations) &&
    validStatistics(value.evidence_statistics)
  )
}

function validHypothesis(value: unknown): boolean {
  if (value === null) return true
  return (
    isRecord(value) &&
    value.kind === 'experiment_hypothesis' &&
    value.is_optional === true &&
    [
      'label',
      'metric',
      'metric_definition',
      'rationale',
      'value',
      'variable',
      'window',
    ].every((key) => typeof value[key] === 'string') &&
    stringArray(value.comparison_post_ids) &&
    stringArray(value.supporting_post_ids)
  )
}

function isDraftResponse(value: unknown): value is DraftResponse {
  if (
    !isRecord(value) ||
    typeof value.assessment_id !== 'string' ||
    !validDate(value.assessed_at) ||
    !oneOf(value.decision_state, [
      'supported',
      'insufficient_evidence',
    ] as const) ||
    !Array.isArray(value.comparable_evidence) ||
    !value.comparable_evidence.every(validComparable) ||
    !Array.isArray(value.metrics) ||
    !value.metrics.every(validMetric) ||
    !Array.isArray(value.observations) ||
    !value.observations.every(validObservation) ||
    !stringArray(value.assumptions) ||
    !stringArray(value.limitations) ||
    !stringArray(value.retrieval_coverage_limitations) ||
    !countPairs(value.exclusions) ||
    !Array.isArray(value.retrieval_exclusions) ||
    !value.retrieval_exclusions.every(
      (item) =>
        isRecord(item) &&
        typeof item.post_id === 'string' &&
        stringArray(item.reasons),
    ) ||
    ![
      'retrieval_candidate_count',
      'retrieval_eligible_count',
      'retrieval_excluded_count',
      'retrieval_vector_candidate_count',
    ].every((key) => finiteNumber(value[key])) ||
    typeof value.retrieval_truncated !== 'boolean' ||
    !validHypothesis(value.suggested_hypothesis) ||
    !validAcceptedHypothesis(value.accepted_hypothesis) ||
    !isRecord(value.versions)
  )
    return false
  const versions = value.versions
  return [
    'baseline',
    'decision',
    'decision_config',
    'embedding_identity',
    'profile',
    'ranking_config',
    'retrieval',
  ].every((key) => typeof versions[key] === 'string')
}

function validEvidenceObservation(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.metric_definition === 'string' &&
    value.metric_definition.trim().length > 0 &&
    typeof value.metric_name === 'string' &&
    value.metric_name.trim().length > 0 &&
    typeof value.metric_unit === 'string' &&
    value.metric_unit.trim().length > 0 &&
    (value.state === 'observed'
      ? typeof value.metric_value === 'string' &&
        /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(
          value.metric_value,
        ) &&
        Number.isFinite(Number(value.metric_value))
      : value.metric_value === null) &&
    finiteNumber(value.observed_age_seconds) &&
    validDate(value.observed_at) &&
    validDate(value.published_at) &&
    oneOf(value.source, SOURCES) &&
    oneOf(value.state, METRIC_STATES) &&
    typeof value.window_key === 'string' &&
    value.window_key.trim().length > 0 &&
    oneOf(value.window_kind, ['mature_cumulative', 'age_aligned'] as const) &&
    isRecord(value.provenance) &&
    oneOf(value.provenance.source, SOURCES) &&
    (value.provenance.missing_reason === undefined ||
      value.provenance.missing_reason === null ||
      oneOf(value.provenance.missing_reason, [
        'not_returned',
        'invalid_value',
        'unavailable',
      ] as const))
  )
}

function validEvidenceItem(value: unknown): value is PostEvidence {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    oneOf(value.disclosure, DISCLOSURES) &&
    oneOf(value.freshness, FRESHNESS) &&
    validDate(value.published_at) &&
    oneOf(value.source, SOURCES) &&
    (value.source_observed_at === null ||
      validDate(value.source_observed_at)) &&
    (value.source_url === null || typeof value.source_url === 'string') &&
    (value.text === null || typeof value.text === 'string') &&
    Array.isArray(value.observations) &&
    value.observations.every(validEvidenceObservation) &&
    typeof value.observations_truncated === 'boolean'
  )
}

function isEvidencePage(value: unknown): value is EvidencePageEnvelope {
  return (
    isRecord(value) &&
    typeof value.assessment_id === 'string' &&
    validDate(value.as_of) &&
    Array.isArray(value.items) &&
    (value.next_cursor === undefined ||
      value.next_cursor === null ||
      typeof value.next_cursor === 'string')
  )
}

function isAbortError(error: unknown) {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (isRecord(error) && error.name === 'AbortError')
  )
}

function dateLabel(value: unknown) {
  if (typeof value !== 'string') return 'Unknown date'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown date'
    : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date)
}

function numberLabel(value: unknown) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unavailable'
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(
    value,
  )
}

function safeSourceUrl(value: unknown, disclosure: unknown) {
  if (disclosure !== 'permitted' || typeof value !== 'string') return null
  try {
    const url = new URL(value)
    if (
      url.protocol !== 'https:' ||
      !['x.com', 'twitter.com'].includes(url.hostname) ||
      url.username ||
      url.password ||
      url.port ||
      url.search ||
      url.hash
    )
      return null
    return /^\/i\/status\/\d+$/.test(url.pathname) ? url.href : null
  } catch {
    return null
  }
}

function disclosureLabel(disclosure: unknown) {
  switch (disclosure) {
    case 'permitted':
      return 'Permitted source'
    case 'not_known_at_cutoff':
      return 'Not known at assessment cutoff'
    case 'source_policy_blocked':
      return 'Source policy blocks disclosure'
    case 'permission_required':
      return 'Permission required'
    default:
      return 'Disclosure unavailable'
  }
}

function metricStateLabel(state: unknown, value: unknown) {
  if (state === 'observed')
    return value === null ? 'Observed value unavailable' : String(value)
  if (state === 'missing') return 'Missing from source'
  if (state === 'invalid') return 'Invalid source value'
  return 'Metric unavailable'
}

function sourceLabel(source: unknown) {
  switch (source) {
    case 'authorized_x_api':
      return 'Authorized X API'
    case 'archive':
      return 'Creator archive'
    case 'unknown':
      return 'Source unknown'
    default:
      return 'Source unavailable'
  }
}

type DisclosurePolicy = {
  showContent: boolean
  showObservations: boolean
  showSourceMetadata: boolean
}

function disclosurePolicy(disclosure: unknown): DisclosurePolicy {
  switch (disclosure) {
    case 'permitted':
      return {
        showContent: true,
        showObservations: true,
        showSourceMetadata: true,
      }
    case 'not_known_at_cutoff':
      return {
        showContent: false,
        showObservations: true,
        showSourceMetadata: false,
      }
    default:
      return {
        showContent: false,
        showObservations: false,
        showSourceMetadata: false,
      }
  }
}

function pairLabels(pairs: [string, number][]) {
  return pairs.length === 0
    ? 'None recorded'
    : pairs
        .map(([reason, count]) => `${reason.replaceAll('_', ' ')}: ${count}`)
        .join(' · ')
}

function errorMessage(error: unknown) {
  if (!(error instanceof ApiRequestError))
    return 'The draft analysis could not be completed. No draft was published.'
  if (error.status === 401)
    return 'Your private session is no longer valid. Sign in again before analyzing a draft.'
  if (error.status === 403)
    return 'This analysis is not permitted for the current creator session.'
  if (error.status === 404)
    return 'That saved assessment is not available to this creator session.'
  if (error.status === 409)
    return error.code === 'idempotency_key_reused'
      ? 'This retry key belongs to different draft content. Edit the draft or start a fresh request.'
      : error.message || 'The draft conflicts with an existing assessment.'
  if (error.status === 422)
    return 'The draft or its metadata did not match the analysis contract.'
  if (error.status === 429)
    return 'Analysis is rate-limited. Try again later; no automatic retry was made.'
  if (error.status === 503)
    return 'The analysis service is temporarily unavailable. Your draft was not published.'
  return error.message || 'The draft analysis could not be completed.'
}

function statusForError(error: unknown): DraftStatus {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) return 'unauthorized'
    if (error.status === 429) return 'rate-limited'
    if (error.status === 503) return 'unavailable'
  }
  return 'error'
}

function fingerprint(body: DraftRequest) {
  return JSON.stringify(body)
}

function validateDraft(text: string, topic: string) {
  if (!text.trim()) return 'Enter a draft before requesting analysis.'
  if (text.length > MAX_TEXT_LENGTH)
    return `Drafts must be ${MAX_TEXT_LENGTH.toLocaleString()} characters or fewer.`
  if (topic.length > MAX_TOPIC_LENGTH)
    return `Topics must be ${MAX_TOPIC_LENGTH} characters or fewer.`
  return null
}

function statusCopy(status: DraftStatus) {
  switch (status) {
    case 'validating':
      return 'Checking the draft before sending it.'
    case 'loading':
      return 'Comparing the draft with eligible creator evidence.'
    case 'success':
      return 'Analysis complete.'
    case 'insufficient-evidence':
      return 'The assessment completed without enough evidence for an outlook.'
    case 'rate-limited':
      return 'The service is rate-limited. No automatic retry was made.'
    case 'unauthorized':
      return 'A valid private session is required.'
    case 'unavailable':
      return 'The analysis service is unavailable.'
    case 'error':
      return 'The assessment failed without publishing the draft.'
    default:
      return 'Your draft stays in this browser until you submit it for analysis.'
  }
}

function EvidenceCard({
  item,
  comparable,
}: {
  item: PostEvidence
  comparable: DraftResponse['comparable_evidence'][number] | undefined
}) {
  const url = safeSourceUrl(item.source_url, item.disclosure)
  const policy = disclosurePolicy(item.disclosure)
  const observations = policy.showObservations ? item.observations : []
  return (
    <article className="draft-evidence-card">
      <div className="draft-evidence-card__heading">
        <div>
          <p className="card-kicker">Comparable post</p>
          <h3>{dateLabel(item.published_at)}</h3>
        </div>
        <span className="coverage-badge">
          {comparable
            ? `Retrieval relevance: ${comparable.relevance.toFixed(2)} (ranking score, not probability)`
            : 'Matched'}
        </span>
      </div>
      <p className="form-hint">{disclosureLabel(item.disclosure)}</p>
      {policy.showSourceMetadata ? (
        <p className="form-hint">Source: {sourceLabel(item.source)}</p>
      ) : (
        <p className="form-hint">Source metadata unavailable at this cutoff.</p>
      )}
      {policy.showSourceMetadata && item.source_observed_at && (
        <p className="form-hint">
          Source observed: {dateLabel(item.source_observed_at)}
        </p>
      )}
      {policy.showContent && item.text ? (
        <blockquote>{item.text}</blockquote>
      ) : (
        <p className="muted-copy">
          Post text is not displayed because the source disclosure does not
          permit it.
        </p>
      )}
      {policy.showContent && url && (
        <a href={url} target="_blank" rel="noreferrer">
          Open permitted source
        </a>
      )}
      {comparable && comparable.inclusion_reasons.length > 0 && (
        <div className="draft-reasons">
          <strong>Why it was included</strong>
          <ul>
            {comparable.inclusion_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="draft-metric-list">
        {observations.length === 0 ? (
          <p className="muted-copy">
            No observations are available for this post.
          </p>
        ) : (
          observations.map((observation) => (
            <div className="draft-metric" key={observation.id}>
              <span>
                {observation.metric_name} · {observation.metric_unit} ·{' '}
                {observation.window_key}
              </span>
              <strong>
                {metricStateLabel(observation.state, observation.metric_value)}
              </strong>
              <small>
                Observation source: {sourceLabel(observation.provenance.source)}{' '}
                · observed {dateLabel(observation.observed_at)}
              </small>
            </div>
          ))
        )}
      </div>
      {item.observations_truncated && policy.showObservations && (
        <p className="form-hint">
          Observations truncated; additional observations are unavailable.
        </p>
      )}
      {item.freshness !== 'recorded' && (
        <p className="form-hint">
          Freshness: {item.freshness.replaceAll('_', ' ')}
        </p>
      )}
    </article>
  )
}

function ResultView({
  response,
  evidence,
  evidenceError,
  onReload,
  reloading,
}: {
  response: DraftResponse
  evidence: PostEvidence[]
  evidenceError: string | null
  onReload: () => void
  reloading: boolean
}) {
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.id, item])),
    [evidence],
  )
  const primaryObservation = response.observations[0]
  const hypothesis = response.suggested_hypothesis
  return (
    <div className="draft-results">
      <div className="draft-result-actions">
        <p className="form-hint">Assessment {response.assessment_id}</p>
        <button
          className="button button--secondary"
          type="button"
          onClick={onReload}
          disabled={reloading}
        >
          {reloading ? 'Refreshing…' : 'Refresh saved assessment'}
        </button>
      </div>
      <section className="draft-callout" aria-labelledby="draft-guidance-title">
        <p className="eyebrow">
          <span className="eyebrow__dot" aria-hidden="true" /> Decision guidance
        </p>
        <h2 id="draft-guidance-title">
          What the evidence suggests trying next
        </h2>
        {hypothesis ? (
          <>
            <p>
              <strong>{hypothesis.label}</strong>
            </p>
            <p>{hypothesis.rationale}</p>
            <p className="form-hint">
              Testable hypothesis: {hypothesis.variable} = {hypothesis.value} (
              {hypothesis.metric}, {hypothesis.window}).
            </p>
          </>
        ) : primaryObservation ? (
          <p>{primaryObservation.explanation}</p>
        ) : (
          <p className="muted-copy">
            No specific next action was returned. The available evidence does
            not support a responsible recommendation.
          </p>
        )}
        {hypothesis && (
          <p className="form-hint">
            Suggested experiment only: it has not been accepted or saved. This
            view cannot change an existing assessment.
          </p>
        )}
      </section>

      <section className="draft-section" aria-labelledby="draft-outlook-title">
        <div className="draft-section__heading">
          <div>
            <p className="card-kicker">Relative outlook</p>
            <h2 id="draft-outlook-title">Creator-relative metric ranges</h2>
          </div>
          <span className="coverage-badge">
            {response.decision_state.replaceAll('_', ' ')}
          </span>
        </div>
        {response.metrics.length === 0 ? (
          <p className="muted-copy">No supported metric series was returned.</p>
        ) : (
          <div className="draft-metric-grid">
            {response.metrics.map((metric) => (
              <article
                className="draft-outlook-card"
                key={`${metric.metric}:${metric.metric_definition}:${metric.window}`}
              >
                <h3>{metric.metric}</h3>
                <p className="form-hint">
                  {metric.metric_definition} · {metric.window}
                </p>
                <strong>{metric.evidence_strength} evidence</strong>
                {metric.outlook ? (
                  <p>
                    {numberLabel(metric.outlook.lower_p25)}–
                    {numberLabel(metric.outlook.upper_p75)} typical range;
                    median {numberLabel(metric.outlook.median_p50)}
                  </p>
                ) : (
                  <p className="muted-copy">
                    No outlook is supported for this metric.
                  </p>
                )}
                <p className="form-hint">
                  Eligible posts: {metric.eligible_post_count}; effective
                  sample: {numberLabel(metric.effective_sample_size)}
                </p>
                <p className="form-hint">
                  Derived creator-relative summary · exclusions:{' '}
                  {pairLabels(metric.exclusion_counts)}
                </p>
                {metric.limitations.length > 0 && (
                  <p className="form-hint">
                    Metric limitations: {metric.limitations.join(' · ')}
                  </p>
                )}
                {metric.statistics && (
                  <p className="form-hint">
                    Outliers: {metric.statistics.outlier_count}; upper outliers:{' '}
                    {metric.statistics.upper_outlier_count}
                  </p>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <section
        className="draft-section"
        aria-labelledby="draft-observations-title"
      >
        <div className="draft-section__heading">
          <div>
            <p className="card-kicker">Traceable observations</p>
            <h2 id="draft-observations-title">What the comparables show</h2>
          </div>
        </div>
        {response.observations.length === 0 ? (
          <p className="muted-copy">
            No concise observation was supported by the returned evidence.
          </p>
        ) : (
          <ul className="draft-observation-list">
            {response.observations.slice(0, 2).map((observation, index) => (
              <li key={`${observation.kind}-${index}`}>
                <strong>{observation.kind.replaceAll('_', ' ')}</strong>
                <span>{observation.explanation}</span>
                <small>
                  {observation.evidence_strength} evidence ·{' '}
                  {observation.supporting_post_ids.length} supporting post(s)
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        className="draft-section"
        aria-labelledby="draft-comparables-title"
      >
        <div className="draft-section__heading">
          <div>
            <p className="card-kicker">Comparable evidence</p>
            <h2 id="draft-comparables-title">
              Historical posts used in the assessment
            </h2>
          </div>
          <span className="coverage-badge">
            {response.comparable_evidence.length} matched
          </span>
        </div>
        {evidenceError && (
          <div className="form-error" role="alert">
            Comparable post enrichment status: {evidenceError}
          </div>
        )}
        {response.comparable_evidence.length === 0 ? (
          <p className="muted-copy">
            No comparable posts were eligible for this draft.
          </p>
        ) : evidence.length === 0 && !evidenceError ? (
          <p className="muted-copy">
            No displayable comparable metadata was returned.
          </p>
        ) : (
          <div className="draft-evidence-grid">
            {response.comparable_evidence.map((comparable) => {
              const item = evidenceById.get(comparable.post_id)
              return item ? (
                <EvidenceCard
                  key={item.id}
                  item={item}
                  comparable={comparable}
                />
              ) : null
            })}
          </div>
        )}
      </section>

      <section
        className="draft-section draft-limitations"
        aria-labelledby="draft-limitations-title"
      >
        <p className="card-kicker">Boundaries and sample quality</p>
        <h2 id="draft-limitations-title">
          Read this as evidence, not a promise
        </h2>
        <p className="muted-copy">
          BipMe does not know X's hidden ranking system, and these associations
          do not prove causality or guarantee future reach.
        </p>
        <ul>
          {[...response.limitations, ...response.assumptions].map((item) => (
            <li key={item}>{item}</li>
          ))}
          {response.retrieval_coverage_limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
          <li>Assessment exclusions: {pairLabels(response.exclusions)}.</li>
          <li>
            Retrieval candidates: {response.retrieval_candidate_count};
            eligible: {response.retrieval_eligible_count}; excluded:{' '}
            {response.retrieval_excluded_count}.
          </li>
          {response.retrieval_exclusions.length > 0 && (
            <li>
              Retrieval exclusion reasons:{' '}
              {response.retrieval_exclusions
                .flatMap((item) => item.reasons)
                .join(', ')}
            </li>
          )}
          {response.retrieval_truncated && (
            <li>
              Candidate retrieval was truncated; this is not a complete eligible
              sample.
            </li>
          )}
        </ul>
      </section>
    </div>
  )
}

export function DraftAnalysis({
  context,
  onSessionExpired,
  onBackToDashboard,
  client: clientProp,
}: Props) {
  const client = clientProp ?? apiClient
  const [text, setText] = useState('')
  const [topic, setTopic] = useState('')
  const [intent, setIntent] = useState<DraftRequest['declared_intent']>(null)
  const [topology, setTopology] = useState<DraftRequest['topology']>('original')
  const [media, setMedia] = useState<DraftRequest['media_types']>(null)
  const [status, setStatus] = useState<DraftStatus>('idle')
  const [response, setResponse] = useState<DraftResponse | null>(null)
  const [evidence, setEvidence] = useState<PostEvidence[]>([])
  const [error, setError] = useState<string | null>(null)
  const [evidenceError, setEvidenceError] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [assessmentId, setAssessmentId] = useState<string | null>(null)
  const [reloading, setReloading] = useState(false)
  const controllerRef = useRef<AbortController | null>(null)
  const inFlightRef = useRef(false)
  const generationRef = useRef(0)
  const bodyFingerprintRef = useRef<string | null>(null)
  const keyRef = useRef<string | null>(null)
  const fingerprintRef = useRef<string | null>(null)
  const errorRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => controllerRef.current?.abort(), [])
  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  const body = useMemo<DraftRequest>(
    () => ({
      text,
      declared_topic: topic.trim() || null,
      declared_intent: intent,
      topology,
      thread_role: topology === 'original' ? 'single' : null,
      media_types: media && media.length > 0 ? media : null,
      metric_preferences: [],
    }),
    [intent, media, text, topology, topic],
  )

  const bodyIdentity = useMemo(() => fingerprint(body), [body])

  useEffect(() => {
    if (bodyFingerprintRef.current === null) {
      bodyFingerprintRef.current = bodyIdentity
      return
    }
    if (bodyFingerprintRef.current === bodyIdentity) return
    bodyFingerprintRef.current = bodyIdentity
    generationRef.current += 1
    controllerRef.current?.abort()
    controllerRef.current = null
    inFlightRef.current = false
    keyRef.current = null
    fingerprintRef.current = null
    setResponse(null)
    setEvidence([])
    setAssessmentId(null)
    setEvidenceError(null)
    setError(null)
    setReloading(false)
    setStatus('idle')
    setAnnouncement(
      'Draft input changed; the previous assessment no longer applies.',
    )
  }, [bodyIdentity])

  const loadEvidence = async (
    result: DraftResponse,
    signal: AbortSignal,
    generation: number,
  ) => {
    const isCurrent = () =>
      generationRef.current === generation && !signal.aborted
    if (isCurrent()) setEvidence([])
    const ids = result.comparable_evidence
      .map((item) => item.post_id)
      .slice(0, 50)
    if (ids.length === 0) {
      if (isCurrent()) {
        setEvidence([])
        setEvidenceError(null)
      }
      return
    }
    try {
      if (new Set(ids).size !== ids.length)
        throw new Error(
          'The assessment returned duplicate comparable post IDs.',
        )
      const page = await client.historyEvidence(
        { post_ids: ids, assessment_id: result.assessment_id },
        signal,
      )
      if (!isEvidencePage(page))
        throw new Error('The evidence response was malformed.')
      if (page.assessment_id !== result.assessment_id)
        throw new Error(
          'The evidence response belongs to a different assessment.',
        )
      const cutoff = new Date(result.assessed_at).getTime()
      if (new Date(page.as_of).getTime() !== cutoff)
        throw new Error(
          'The evidence cutoff does not match the immutable assessment timestamp.',
        )
      const requested = new Set(ids)
      const returned = new Set<string>()
      const validItems: PostEvidence[] = []
      for (const raw of page.items) {
        const policy = isRecord(raw) ? disclosurePolicy(raw.disclosure) : null
        const candidate =
          isRecord(raw) && policy
            ? {
                ...raw,
                text: policy.showContent ? raw.text : null,
                source_url: policy.showContent ? raw.source_url : null,
                source_observed_at: policy.showSourceMetadata
                  ? raw.source_observed_at
                  : null,
                observations: policy.showObservations ? raw.observations : [],
              }
            : raw
        if (!validEvidenceItem(candidate)) {
          continue
        }
        if (
          new Date(candidate.published_at).getTime() > cutoff ||
          (candidate.source_observed_at !== null &&
            new Date(candidate.source_observed_at).getTime() > cutoff) ||
          candidate.observations.some((observation) => {
            const observed = new Date(observation.observed_at).getTime()
            const published = new Date(observation.published_at).getTime()
            return (
              observed > cutoff ||
              published !== new Date(candidate.published_at).getTime() ||
              observed < published ||
              observation.observed_age_seconds < 0 ||
              Math.abs(
                observation.observed_age_seconds -
                  (observed - published) / 1000,
              ) > 0.001
            )
          })
        )
          throw new Error(
            'The evidence response included impossible or future observations.',
          )
        if (!requested.has(candidate.id))
          throw new Error('The evidence response included an unexpected post.')
        if (returned.has(candidate.id))
          throw new Error('The evidence response included a duplicate post.')
        returned.add(candidate.id)
        validItems.push(candidate)
      }
      if (isCurrent()) {
        setEvidence(validItems)
        const unavailableCount = requested.size - returned.size
        setEvidenceError(
          unavailableCount > 0
            ? `${validItems.length} of ${requested.size} comparable posts were validated; ${unavailableCount} are unavailable and were not inferred.`
            : null,
        )
      }
    } catch (loadError) {
      if (isAbortError(loadError) || !isCurrent()) return
      if (loadError instanceof ApiRequestError && loadError.status === 401)
        onSessionExpired?.()
      setEvidenceError(errorMessage(loadError))
    }
  }

  const acceptResult = async (
    result: DraftResponse,
    signal: AbortSignal,
    generation: number,
    expectedAssessmentId?: string,
  ) => {
    if (!isDraftResponse(result))
      throw new Error('The assessment response was malformed.')
    if (generationRef.current !== generation || signal.aborted) return
    if (expectedAssessmentId && result.assessment_id !== expectedAssessmentId)
      throw new Error(
        'The saved assessment response had a different assessment ID.',
      )
    setResponse(result)
    setAssessmentId(result.assessment_id)
    setStatus(
      result.decision_state === 'insufficient_evidence'
        ? 'insufficient-evidence'
        : 'success',
    )
    setAnnouncement(
      result.decision_state === 'insufficient_evidence'
        ? 'Assessment completed with insufficient evidence.'
        : 'Assessment completed.',
    )
    await loadEvidence(result, signal, generation)
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!context) return
    if (inFlightRef.current) return
    setStatus('validating')
    setError(null)
    setEvidenceError(null)
    const validation = validateDraft(text, topic)
    if (validation) {
      setError(validation)
      setStatus('error')
      return
    }
    const nextFingerprint = fingerprint(body)
    if (fingerprintRef.current !== nextFingerprint || !keyRef.current) {
      keyRef.current = crypto.randomUUID()
      fingerprintRef.current = nextFingerprint
    }
    const controller = new AbortController()
    const generation = generationRef.current
    const submittedBody = body
    controllerRef.current?.abort()
    controllerRef.current = controller
    inFlightRef.current = true
    setStatus('loading')
    try {
      const result = await client.createDraftAssessment(
        submittedBody,
        keyRef.current,
        controller.signal,
      )
      if (!controller.signal.aborted && generationRef.current === generation)
        await acceptResult(result, controller.signal, generation)
    } catch (submitError) {
      if (
        !isAbortError(submitError) &&
        !controller.signal.aborted &&
        generationRef.current === generation
      ) {
        setError(errorMessage(submitError))
        setStatus(statusForError(submitError))
        if (
          submitError instanceof ApiRequestError &&
          submitError.status === 401
        )
          onSessionExpired?.()
      }
    } finally {
      if (generationRef.current === generation) {
        inFlightRef.current = false
        if (controllerRef.current === controller) controllerRef.current = null
      }
    }
  }

  const reload = async () => {
    if (!assessmentId || inFlightRef.current) return
    const controller = new AbortController()
    const generation = generationRef.current
    const requestedAssessmentId = assessmentId
    controllerRef.current?.abort()
    controllerRef.current = controller
    inFlightRef.current = true
    setReloading(true)
    setError(null)
    setEvidenceError(null)
    setStatus('loading')
    try {
      const result = await client.draftAssessment(
        requestedAssessmentId,
        controller.signal,
      )
      if (!controller.signal.aborted && generationRef.current === generation)
        await acceptResult(
          result,
          controller.signal,
          generation,
          requestedAssessmentId,
        )
    } catch (loadError) {
      if (
        !isAbortError(loadError) &&
        !controller.signal.aborted &&
        generationRef.current === generation
      ) {
        setError(errorMessage(loadError))
        setStatus(statusForError(loadError))
        if (loadError instanceof ApiRequestError && loadError.status === 401)
          onSessionExpired?.()
      }
    } finally {
      if (generationRef.current === generation) {
        inFlightRef.current = false
        setReloading(false)
        if (controllerRef.current === controller) controllerRef.current = null
      }
    }
  }

  return (
    <div className="draft-analysis">
      <section
        className="workspace-card"
        aria-labelledby="draft-analysis-title"
      >
        <p className="eyebrow">
          <span className="eyebrow__dot" aria-hidden="true" /> Draft analysis
        </p>
        <h2 id="draft-analysis-title">Find a grounded next experiment</h2>
        <p className="muted-copy">
          Your draft is compared with eligible historical evidence. BipMe does
          not publish, rewrite or send it to X.
        </p>
        {context ? (
          <p className="form-hint">
            Using report context {context.reportId} as of{' '}
            {dateLabel(context.reportAsOf)} ·{' '}
            {context.coverage.replaceAll('_', ' ')}.
          </p>
        ) : (
          <div className="form-error" role="alert">
            Open Draft Analysis from a current Creator Intelligence Report. This
            direct or refreshed route cannot submit without that in-memory
            handoff.
            {onBackToDashboard && (
              <button
                className="button button--secondary"
                type="button"
                onClick={onBackToDashboard}
              >
                Back to Creator Intelligence
              </button>
            )}
          </div>
        )}
        <form onSubmit={submit} noValidate>
          <label htmlFor="draft-text">Draft text</label>
          <textarea
            id="draft-text"
            value={text}
            disabled={!context}
            onChange={(event) => setText(event.target.value)}
            maxLength={MAX_TEXT_LENGTH}
            rows={8}
            aria-describedby="draft-text-help"
          />
          <div id="draft-text-help" className="form-hint">
            {text.length.toLocaleString()} / {MAX_TEXT_LENGTH.toLocaleString()}{' '}
            characters. Required.
          </div>
          <div className="draft-form-grid">
            <div>
              <label htmlFor="draft-topic">
                Topic <span className="form-hint">(optional)</span>
              </label>
              <input
                id="draft-topic"
                value={topic}
                disabled={!context}
                onChange={(event) => setTopic(event.target.value)}
                maxLength={MAX_TOPIC_LENGTH}
              />
            </div>
            <div>
              <label htmlFor="draft-intent">
                Intent <span className="form-hint">(optional)</span>
              </label>
              <select
                id="draft-intent"
                value={intent ?? ''}
                disabled={!context}
                onChange={(event) =>
                  setIntent(
                    (event.target.value ||
                      null) as DraftRequest['declared_intent'],
                  )
                }
              >
                <option value="">Not specified</option>
                <option value="inform">Inform</option>
                <option value="ask">Ask</option>
                <option value="promote">Promote</option>
                <option value="entertain">Entertain</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label htmlFor="draft-topology">Topology</label>
              <select
                id="draft-topology"
                value={topology}
                disabled={!context}
                onChange={(event) =>
                  setTopology(event.target.value as DraftRequest['topology'])
                }
              >
                <option value="original">Original</option>
                <option value="reply">Reply</option>
                <option value="quote">Quote</option>
              </select>
            </div>
            <div>
              <label htmlFor="draft-media">
                Media <span className="form-hint">(optional)</span>
              </label>
              <select
                id="draft-media"
                value={media?.[0] ?? ''}
                disabled={!context}
                onChange={(event) =>
                  setMedia(
                    event.target.value
                      ? [
                          event.target.value as NonNullable<
                            DraftRequest['media_types']
                          >[number],
                        ]
                      : null,
                  )
                }
              >
                <option value="">None specified</option>
                <option value="image">Image</option>
                <option value="video">Video</option>
                <option value="gif">GIF</option>
                <option value="audio">Audio</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>
          <p className="form-hint">
            Metric preferences are not preselected. The analysis returns only
            exact metric series supported by the service.
          </p>
          <div className="form-actions">
            <button
              className="button button--primary"
              type="submit"
              disabled={
                !context || status === 'loading' || status === 'validating'
              }
            >
              {status === 'loading' ? 'Analyzing…' : 'Analyze this draft'}
            </button>
            <span className="form-hint">
              Submitting does not publish the draft.
            </span>
          </div>
        </form>
        <div className="sr-only" role="status" aria-live="polite">
          {announcement || statusCopy(status)}
        </div>
        {error && (
          <div className="form-error" role="alert" tabIndex={-1} ref={errorRef}>
            {error}
          </div>
        )}
      </section>
      {response && (
        <ResultView
          response={response}
          evidence={evidence}
          evidenceError={evidenceError}
          onReload={reload}
          reloading={reloading}
        />
      )}
    </div>
  )
}
