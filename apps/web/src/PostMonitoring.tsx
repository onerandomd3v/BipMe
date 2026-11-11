import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiRequestError, apiClient, type ApiClient } from './api/client'
import type { components } from './api/generated/schema'
import { apiProblemMessage } from './dashboardModel'
import { hasSyntheticProvenance, SyntheticDemoNotice } from './syntheticDemo'

type Assessment = components['schemas']['DraftAnalysisResponse']
type Publication = components['schemas']['PublicationLinkResponse']
type MetricEvidence = components['schemas']['MetricEvidenceResponse']
type ComparableEvidence = components['schemas']['ComparableEvidenceResponse']
type DecisionObservation = components['schemas']['DecisionObservationResponse']
type PostmortemRead = components['schemas']['PostmortemReadResponse']
type PostmortemMetric = components['schemas']['PostmortemMetricResponse']
type PostmortemObservation =
  components['schemas']['PostmortemObservationResponse']
type PostmortemPublication =
  components['schemas']['PostmortemPublicationResponse']
type MonitoringRead = components['schemas']['MonitoringReadResponse']
type MonitoringWindow = components['schemas']['MonitoringWindowResponse']
type MonitoringObservation =
  components['schemas']['MonitoringObservationResponse']
type MonitoringPublication =
  components['schemas']['MonitoringPublicationResponse']

function malformedResponse(message: string) {
  return new ApiRequestError({
    code: 'malformed_response',
    message,
    status: 200,
  })
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const POST_ID_PATTERN = /^[1-9][0-9]{0,19}$/
const HANDLE_PATTERN = /^[A-Za-z0-9_]{1,15}$/
const DATE_TIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isDateTime(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    DATE_TIME_PATTERN.test(value) &&
    !Number.isNaN(Date.parse(value))
  )
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function isNumberTupleArray(value: unknown): value is [string, number][] {
  return (
    Array.isArray(value) &&
    value.every(
      (item) =>
        Array.isArray(item) &&
        item.length === 2 &&
        typeof item[0] === 'string' &&
        isFiniteNumber(item[1]),
    )
  )
}

function isUnsignedUint64(value: unknown): value is string {
  if (typeof value !== 'string' || !POST_ID_PATTERN.test(value)) return false
  try {
    return BigInt(value) <= 2n ** 64n - 1n
  } catch {
    return false
  }
}

function isEvidenceStrength(value: unknown): boolean {
  return (
    value === 'High' ||
    value === 'Moderate' ||
    value === 'Low' ||
    value === 'Insufficient'
  )
}

function isBaselineStatistics(value: unknown): boolean {
  if (!isRecord(value)) return false
  return (
    isFiniteNumber(value.consistency_ratio) &&
    (value.dispersion_ratio === null ||
      isFiniteNumber(value.dispersion_ratio)) &&
    isFiniteNumber(value.iqr) &&
    isFiniteNumber(value.maximum) &&
    isFiniteNumber(value.maximum_weight_share) &&
    isFiniteNumber(value.median_shift_in_iqr) &&
    isFiniteNumber(value.minimum) &&
    isFiniteNumber(value.outlier_adjusted_p50) &&
    isFiniteNumber(value.outlier_count) &&
    isFiniteNumber(value.p10) &&
    isFiniteNumber(value.p25) &&
    isFiniteNumber(value.p50) &&
    isFiniteNumber(value.p75) &&
    isFiniteNumber(value.p90) &&
    (value.target_percentile_rank === null ||
      isFiniteNumber(value.target_percentile_rank)) &&
    isFiniteNumber(value.upper_outlier_count)
  )
}

function isHistoricalRange(value: unknown): boolean {
  if (!isRecord(value)) return false
  return (
    isStringArray(value.comparable_post_ids) &&
    isFiniteNumber(value.effective_sample_size) &&
    typeof value.kind === 'string' &&
    isFiniteNumber(value.lower_p25) &&
    isFiniteNumber(value.median_p50) &&
    isFiniteNumber(value.upper_p75)
  )
}

function isAcceptedHypothesis(value: unknown): boolean {
  return Boolean(
    isRecord(value) &&
    typeof value.question === 'string' &&
    typeof value.metric === 'string' &&
    typeof value.metric_definition === 'string' &&
    typeof value.unit === 'string' &&
    (value.window_kind === 'mature_cumulative' ||
      value.window_kind === 'age_aligned') &&
    typeof value.window_key === 'string' &&
    (value.expected_direction === 'higher' ||
      value.expected_direction === 'lower' ||
      value.expected_direction === 'no_direction'),
  )
}

function isSuggestedHypothesis(value: unknown): boolean {
  return Boolean(
    isRecord(value) &&
    isStringArray(value.comparison_post_ids) &&
    typeof value.is_optional === 'boolean' &&
    value.kind === 'experiment_hypothesis' &&
    typeof value.label === 'string' &&
    typeof value.metric === 'string' &&
    typeof value.metric_definition === 'string' &&
    typeof value.rationale === 'string' &&
    isStringArray(value.supporting_post_ids) &&
    typeof value.value === 'string' &&
    typeof value.variable === 'string' &&
    typeof value.window === 'string',
  )
}

function isAlgorithmVersions(value: unknown): boolean {
  return Boolean(
    isRecord(value) &&
    typeof value.baseline === 'string' &&
    typeof value.decision === 'string' &&
    typeof value.decision_config === 'string' &&
    typeof value.embedding_identity === 'string' &&
    typeof value.profile === 'string' &&
    typeof value.ranking_config === 'string' &&
    typeof value.retrieval === 'string',
  )
}

function isAssessment(value: unknown): value is Assessment {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<Assessment>
  return Boolean(
    typeof candidate.assessment_id === 'string' &&
    UUID_PATTERN.test(candidate.assessment_id) &&
    isDateTime(candidate.assessed_at) &&
    (candidate.decision_state === 'supported' ||
      candidate.decision_state === 'insufficient_evidence') &&
    typeof candidate.input_fingerprint === 'string' &&
    (candidate.retrieval_state === 'matched' ||
      candidate.retrieval_state === 'insufficient_evidence' ||
      candidate.retrieval_state === 'no_match') &&
    (isAcceptedHypothesis(candidate.accepted_hypothesis) ||
      candidate.accepted_hypothesis === null) &&
    isStringArray(candidate.assumptions) &&
    isStringArray(candidate.limitations) &&
    isStringArray(candidate.retrieval_coverage_limitations) &&
    Array.isArray(candidate.metrics) &&
    candidate.metrics.every(isMetricEvidence) &&
    Array.isArray(candidate.comparable_evidence) &&
    candidate.comparable_evidence.every(isComparableEvidence) &&
    Array.isArray(candidate.observations) &&
    candidate.observations.every(isDecisionObservation) &&
    isFiniteNumber(candidate.retrieval_candidate_count) &&
    isFiniteNumber(candidate.retrieval_eligible_count) &&
    isFiniteNumber(candidate.retrieval_excluded_count) &&
    Array.isArray(candidate.retrieval_exclusions) &&
    candidate.retrieval_exclusions.every(isCandidateExclusion) &&
    Array.isArray(candidate.exclusions) &&
    isNumberTupleArray(candidate.exclusions) &&
    typeof candidate.retrieval_truncated === 'boolean' &&
    isFiniteNumber(candidate.retrieval_vector_candidate_count) &&
    (candidate.suggested_hypothesis === null ||
      isSuggestedHypothesis(candidate.suggested_hypothesis)) &&
    isAlgorithmVersions(candidate.versions),
  )
}

function isPublication(value: unknown): value is Publication {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<Publication>
  return Boolean(
    typeof candidate.assessment_id === 'string' &&
    UUID_PATTERN.test(candidate.assessment_id) &&
    isDateTime(candidate.assessed_at) &&
    typeof candidate.assessed_fingerprint === 'string' &&
    typeof candidate.canonical_post_id === 'string' &&
    UUID_PATTERN.test(candidate.canonical_post_id) &&
    isUnsignedUint64(candidate.external_post_id) &&
    isDateTime(candidate.published_at) &&
    candidate.linkage_state === 'linked' &&
    (candidate.version_match_state === 'match' ||
      candidate.version_match_state === 'mismatch' ||
      candidate.version_match_state === 'unknown') &&
    (candidate.linked_at === undefined ||
      candidate.linked_at === null ||
      isDateTime(candidate.linked_at)) &&
    (candidate.accepted_hypothesis === null ||
      isAcceptedHypothesis(candidate.accepted_hypothesis)),
  )
}

function isPostmortemPublication(
  value: unknown,
): value is PostmortemPublication {
  return Boolean(
    isRecord(value) &&
    UUID_PATTERN.test(String(value.canonical_post_id)) &&
    isUnsignedUint64(value.external_post_id) &&
    isDateTime(value.published_at) &&
    (value.availability === 'available' ||
      value.availability === 'unavailable' ||
      value.availability === 'deleted') &&
    (value.version_match_state === 'match' ||
      value.version_match_state === 'mismatch' ||
      value.version_match_state === 'unknown'),
  )
}

function isPostmortemObservation(
  value: unknown,
): value is PostmortemObservation {
  return Boolean(
    isRecord(value) &&
    typeof value.metric === 'string' &&
    typeof value.metric_definition === 'string' &&
    typeof value.unit === 'string' &&
    isDateTime(value.observed_at) &&
    UUID_PATTERN.test(String(value.post_id)) &&
    isDateTime(value.published_at) &&
    (value.state === 'observed' || value.state === 'missing') &&
    (value.value === null || isFiniteNumber(value.value)) &&
    typeof value.window_key === 'string' &&
    (value.window_kind === 'mature_cumulative' ||
      value.window_kind === 'age_aligned'),
  )
}

function isPostmortemMetric(value: unknown): value is PostmortemMetric {
  return Boolean(
    isRecord(value) &&
    typeof value.metric === 'string' &&
    typeof value.metric_definition === 'string' &&
    typeof value.unit === 'string' &&
    (value.status === 'scored' ||
      value.status === 'unavailable' ||
      value.status === 'version_unverified') &&
    (value.observed_at === null || isDateTime(value.observed_at)) &&
    (value.observed_value === null || isFiniteNumber(value.observed_value)) &&
    (value.historical_median === null ||
      isFiniteNumber(value.historical_median)) &&
    (value.deviation_from_median === null ||
      isFiniteNumber(value.deviation_from_median)) &&
    (value.relative_percentile === null ||
      isFiniteNumber(value.relative_percentile)) &&
    (value.within_reference_range === null ||
      typeof value.within_reference_range === 'boolean') &&
    isFiniteNumber(value.effective_sample_size) &&
    isFiniteNumber(value.matched_sample_count) &&
    isStringArray(value.limitations) &&
    isStringArray(value.comparison_post_ids) &&
    Array.isArray(value.comparison_observations) &&
    value.comparison_observations.every(isPostmortemObservation),
  )
}

function isPostmortem(value: unknown): boolean {
  const hypothesis = isRecord(value) ? value.hypothesis_evaluation : null
  return Boolean(
    isRecord(value) &&
    UUID_PATTERN.test(String(value.assessment_id)) &&
    isStringArray(value.limitations) &&
    Array.isArray(value.metric_comparisons) &&
    value.metric_comparisons.every(isPostmortemMetric) &&
    Array.isArray(value.observed_outcomes) &&
    value.observed_outcomes.every(isPostmortemObservation) &&
    (hypothesis === null ||
      (isRecord(hypothesis) &&
        typeof hypothesis.metric === 'string' &&
        typeof hypothesis.status === 'string' &&
        isFiniteNumber(hypothesis.matched_sample_count))) &&
    (value.version_state === 'verified' ||
      value.version_state === 'unverified') &&
    typeof value.version === 'string' &&
    UUID_PATTERN.test(String(value.published_post_id)),
  )
}

function isPostmortemRead(value: unknown): value is PostmortemRead {
  if (!isRecord(value)) return false
  const state = value.state
  return Boolean(
    UUID_PATTERN.test(String(value.assessment_id)) &&
    isDateTime(value.assessed_at) &&
    (state === 'publication_pending' ||
      state === 'publication_unavailable' ||
      state === 'evidence_unavailable' ||
      state === 'monitoring_pending' ||
      state === 'insufficient_evidence' ||
      state === 'version_unverified' ||
      state === 'evaluated') &&
    isStringArray(value.limitations) &&
    isAssessment(value.original_outlook) &&
    (value.published_post === null ||
      isPostmortemPublication(value.published_post)) &&
    (value.postmortem === null || isPostmortem(value.postmortem)),
  )
}

function isMonitoringPublication(
  value: unknown,
): value is MonitoringPublication {
  return Boolean(
    isRecord(value) &&
    UUID_PATTERN.test(String(value.canonical_post_id)) &&
    isUnsignedUint64(value.external_post_id) &&
    isDateTime(value.published_at) &&
    ['available', 'unavailable', 'deleted'].includes(
      String(value.availability),
    ) &&
    ['match', 'mismatch', 'unknown'].includes(
      String(value.version_match_state),
    ),
  )
}

function isMonitoringObservation(
  value: unknown,
): value is MonitoringObservation {
  return Boolean(
    isRecord(value) &&
    UUID_PATTERN.test(String(value.id)) &&
    typeof value.metric === 'string' &&
    typeof value.metric_definition === 'string' &&
    typeof value.unit === 'string' &&
    (value.value === null || typeof value.value === 'string') &&
    ['observed', 'missing', 'invalid'].includes(String(value.state)) &&
    isDateTime(value.published_at) &&
    isDateTime(value.observed_at) &&
    isFiniteNumber(value.observed_age_seconds) &&
    typeof value.window_key === 'string' &&
    ['mature_cumulative', 'age_aligned'].includes(String(value.window_kind)) &&
    ['authorized_x_api', 'unknown', 'synthetic_demo'].includes(
      String(value.source),
    ) &&
    (value.missing_reason === null ||
      value.missing_reason === undefined ||
      ['not_returned', 'invalid_value'].includes(String(value.missing_reason))),
  )
}

function isMonitoringWindow(value: unknown): value is MonitoringWindow {
  return Boolean(
    isRecord(value) &&
    typeof value.window_key === 'string' &&
    value.window_key.length > 0 &&
    value.window_kind === 'age_aligned' &&
    isDateTime(value.due_at) &&
    (value.scheduled_at === null || isDateTime(value.scheduled_at)) &&
    (value.finished_at === null || isDateTime(value.finished_at)) &&
    [
      'not_scheduled',
      'pending',
      'running',
      'completed',
      'skipped',
      'missed',
      'cancelled',
      'unavailable',
      'rate_limited',
      'budget_blocked',
      'needs_reconciliation',
      'failed',
      'unknown',
    ].includes(String(value.execution_state)) &&
    ['not_available', 'partial', 'available'].includes(
      String(value.measurement_state),
    ) &&
    (value.failure_code === null || typeof value.failure_code === 'string') &&
    (value.receipt_id === null ||
      UUID_PATTERN.test(String(value.receipt_id))) &&
    Array.isArray(value.observations) &&
    value.observations.every(isMonitoringObservation),
  )
}

function isMonitoringRead(value: unknown): value is MonitoringRead {
  return Boolean(
    isRecord(value) &&
    UUID_PATTERN.test(String(value.assessment_id)) &&
    isDateTime(value.assessed_at) &&
    [
      'publication_pending',
      'publication_unavailable',
      'monitoring_unavailable',
      'monitoring_pending',
      'monitoring_running',
      'monitoring_partial',
      'monitoring_complete',
      'needs_reconciliation',
    ].includes(String(value.state)) &&
    isStringArray(value.limitations) &&
    isAssessment(value.original_outlook) &&
    (value.published_post === null ||
      isMonitoringPublication(value.published_post)) &&
    Array.isArray(value.windows) &&
    value.windows.every(isMonitoringWindow),
  )
}

function validateMonitoringIdentity(
  value: MonitoringRead,
  assessment: Assessment,
  publication: Publication | null,
) {
  const monitoringPublication = value.published_post
  return (
    value.assessment_id === assessment.assessment_id &&
    value.assessed_at === assessment.assessed_at &&
    value.original_outlook.assessment_id === assessment.assessment_id &&
    value.original_outlook.assessed_at === assessment.assessed_at &&
    value.original_outlook.input_fingerprint === assessment.input_fingerprint &&
    (!publication ||
      !monitoringPublication ||
      (monitoringPublication.canonical_post_id ===
        publication.canonical_post_id &&
        monitoringPublication.external_post_id ===
          publication.external_post_id &&
        monitoringPublication.published_at === publication.published_at &&
        monitoringPublication.version_match_state ===
          publication.version_match_state))
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isMetricEvidence(value: unknown): value is MetricEvidence {
  if (!isRecord(value)) return false
  const outlook = value.outlook
  const hasRange = outlook === null || isHistoricalRange(outlook)
  return Boolean(
    isFiniteNumber(value.coverage) &&
    isFiniteNumber(value.effective_sample_size) &&
    isFiniteNumber(value.eligible_post_count) &&
    isEvidenceStrength(value.evidence_strength) &&
    isNumberTupleArray(value.exclusion_counts) &&
    typeof value.metric === 'string' &&
    typeof value.metric_definition === 'string' &&
    typeof value.window === 'string' &&
    isStringArray(value.limitations) &&
    hasRange &&
    (value.statistics === null || isBaselineStatistics(value.statistics)) &&
    isStringArray(value.supporting_post_ids),
  )
}

function isComparableEvidence(value: unknown): value is ComparableEvidence {
  return Boolean(
    isRecord(value) &&
    UUID_PATTERN.test(String(value.post_id)) &&
    isRecord(value.components) &&
    isFiniteNumber(value.components.semantic) &&
    (value.components.format === null ||
      isFiniteNumber(value.components.format)) &&
    (value.components.intent === null ||
      isFiniteNumber(value.components.intent)) &&
    (value.components.structure === null ||
      isFiniteNumber(value.components.structure)) &&
    (value.components.topic === null ||
      isFiniteNumber(value.components.topic)) &&
    isStringArray(value.inclusion_reasons) &&
    isFiniteNumber(value.relevance) &&
    isFiniteNumber(value.retrieval_position),
  )
}

function isDecisionObservation(value: unknown): value is DecisionObservation {
  return Boolean(
    isRecord(value) &&
    (value.kind === 'repeatability' ||
      value.kind === 'outlier' ||
      value.kind === 'coverage_limitation') &&
    typeof value.explanation === 'string' &&
    isEvidenceStrength(value.evidence_strength) &&
    (value.metric === null || typeof value.metric === 'string') &&
    (value.window === null || typeof value.window === 'string') &&
    (value.metric_definition === null ||
      typeof value.metric_definition === 'string') &&
    isStringArray(value.limitations) &&
    isStringArray(value.supporting_post_ids) &&
    (value.evidence_statistics === null ||
      isBaselineStatistics(value.evidence_statistics)),
  )
}

function isCandidateExclusion(value: unknown): boolean {
  return Boolean(
    isRecord(value) &&
    typeof value.post_id === 'string' &&
    UUID_PATTERN.test(value.post_id) &&
    isStringArray(value.reasons),
  )
}

function validPostReference(value: string) {
  if (!value || value !== value.trim()) return false
  if (
    Array.from(value).some((character) => {
      const code = character.charCodeAt(0)
      return character === '\\' || code < 33 || code > 126
    })
  )
    return false
  if (POST_ID_PATTERN.test(value)) {
    try {
      return BigInt(value) <= 2n ** 64n - 1n
    } catch {
      return false
    }
  }
  try {
    const url = new URL(value)
    if (
      url.protocol !== 'https:' ||
      !['x.com', 'twitter.com'].includes(url.hostname) ||
      url.username ||
      url.password ||
      url.port ||
      url.search ||
      url.hash ||
      url.pathname.includes('//')
    )
      return false
    const parts = url.pathname.split('/').filter(Boolean)
    if (parts.length !== 3 || parts[1].toLowerCase() !== 'status') return false
    if (parts[0].toLowerCase() !== 'i' && !HANDLE_PATTERN.test(parts[0]))
      return false
    return POST_ID_PATTERN.test(parts[2]) && BigInt(parts[2]) <= 2n ** 64n - 1n
  } catch {
    return false
  }
}

function formatDate(value: string | null | undefined) {
  if (!value) return 'Unknown time'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unknown time'
    : date.toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
}

function publicationError(error: unknown) {
  if (!(error instanceof ApiRequestError)) return apiProblemMessage(error)
  if (error.status === 404 && error.code === 'publication_not_linked')
    return null
  if (error.status === 409 && error.code === 'published_post_already_linked')
    return 'This X post is already linked to another assessment.'
  if (error.status === 422 && error.code === 'publication_before_assessment')
    return 'The published post predates the original assessment and cannot be attached.'
  if (error.status === 403 && error.code === 'published_post_owner_mismatch')
    return 'The published post is not owned by the authorized X account.'
  if (
    error.status === 503 &&
    error.code === 'observation_scheduling_unavailable'
  )
    return 'The post was not attached because observation scheduling is unavailable. No assessment was changed.'
  return error.message || apiProblemMessage(error)
}

export function PostMonitoring({
  assessmentId,
  client = apiClient,
}: {
  assessmentId: string | null
  client?: ApiClient
}) {
  const [assessment, setAssessment] = useState<Assessment | null>(null)
  const [publication, setPublication] = useState<Publication | null>(null)
  const [postmortem, setPostmortem] = useState<PostmortemRead | null>(null)
  const [monitoring, setMonitoring] = useState<MonitoringRead | null>(null)
  const [input, setInput] = useState('')
  const [loadState, setLoadState] = useState<
    'loading' | 'ready' | 'unavailable'
  >('loading')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [publicationErrorState, setPublicationErrorState] = useState<
    string | null
  >(null)
  const [postmortemError, setPostmortemError] = useState<string | null>(null)
  const [monitoringError, setMonitoringError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const requestGeneration = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    const generation = ++requestGeneration.current
    setAssessment(null)
    setPublication(null)
    setPostmortem(null)
    setMonitoring(null)
    setInput('')
    setSubmitError(null)
    setPublicationErrorState(null)
    setPostmortemError(null)
    setMonitoringError(null)
    if (!assessmentId || !UUID_PATTERN.test(assessmentId)) {
      setLoadState('unavailable')
      setLoadError(
        'Open this screen from a saved assessment using its valid assessment ID.',
      )
      return () => controller.abort()
    }
    setLoadState('loading')
    setLoadError(null)
    client
      .draftAssessment(assessmentId, controller.signal)
      .then((result) => {
        if (
          controller.signal.aborted ||
          generation !== requestGeneration.current
        )
          return
        if (!isAssessment(result))
          throw malformedResponse('The saved assessment response was invalid.')
        if (result.assessment_id !== assessmentId) {
          setLoadState('unavailable')
          setLoadError(
            'The assessment identity did not match the requested screen.',
          )
          return
        }
        setAssessment(result)
        setLoadState('ready')

        client
          .publication(assessmentId, controller.signal)
          .then((publicationResult) => {
            if (
              controller.signal.aborted ||
              generation !== requestGeneration.current
            )
              return
            if (!isPublication(publicationResult))
              throw malformedResponse('The publication response was invalid.')
            if (
              publicationResult.assessment_id !== assessmentId ||
              publicationResult.assessed_at !== result.assessed_at ||
              publicationResult.assessed_fingerprint !==
                result.input_fingerprint
            )
              throw new ApiRequestError({
                code: 'publication_assessment_mismatch',
                message:
                  publicationResult.assessment_id !== assessmentId
                    ? 'The saved publication does not belong to this assessment.'
                    : 'The saved publication does not match this assessment.',
                status: 409,
              })
            setPublication(publicationResult)
            setPublicationErrorState(null)
          })
          .catch((error: unknown) => {
            if (
              controller.signal.aborted ||
              generation !== requestGeneration.current
            )
              return
            if (
              error instanceof ApiRequestError &&
              error.status === 404 &&
              error.code === 'publication_not_linked'
            ) {
              setPublication(null)
              setPublicationErrorState(null)
              return
            }
            setPublicationErrorState(
              publicationError(error) ??
                'The publication status is unavailable.',
            )
          })

        if (!client.postmortem) {
          setPostmortemError(
            'The postmortem client is unavailable in this frontend build.',
          )
          return
        }
        client
          .postmortem(assessmentId, controller.signal)
          .then((postmortemResult) => {
            if (
              controller.signal.aborted ||
              generation !== requestGeneration.current
            )
              return
            if (!isPostmortemRead(postmortemResult))
              throw malformedResponse('The postmortem response was invalid.')
            if (
              postmortemResult.assessment_id !== result.assessment_id ||
              postmortemResult.assessed_at !== result.assessed_at ||
              postmortemResult.original_outlook.assessment_id !==
                result.assessment_id ||
              postmortemResult.original_outlook.assessed_at !==
                result.assessed_at ||
              postmortemResult.original_outlook.input_fingerprint !==
                result.input_fingerprint ||
              (postmortemResult.published_post !== null &&
                postmortemResult.postmortem !== null &&
                postmortemResult.postmortem.published_post_id !==
                  postmortemResult.published_post.canonical_post_id)
            )
              throw new ApiRequestError({
                code: 'postmortem_assessment_mismatch',
                message:
                  'The postmortem response does not match this assessment.',
                status: 409,
              })
            setPostmortem(postmortemResult)
            setPostmortemError(null)
          })
          .catch((error: unknown) => {
            if (
              controller.signal.aborted ||
              generation !== requestGeneration.current
            )
              return
            setPostmortemError(
              error instanceof ApiRequestError
                ? error.message
                : 'The postmortem response was unavailable.',
            )
          })

        if (typeof client.monitoring !== 'function') {
          setMonitoringError(
            'The monitoring client is unavailable in this frontend build.',
          )
        } else {
          client
            .monitoring(assessmentId, controller.signal)
            .then((monitoringResult) => {
              if (
                controller.signal.aborted ||
                generation !== requestGeneration.current
              )
                return
              if (!isMonitoringRead(monitoringResult))
                throw malformedResponse('The monitoring response was invalid.')
              if (!validateMonitoringIdentity(monitoringResult, result, null))
                throw new ApiRequestError({
                  code: 'monitoring_assessment_mismatch',
                  message:
                    'The monitoring response does not match this assessment.',
                  status: 409,
                })
              setMonitoring(monitoringResult)
              setMonitoringError(null)
            })
            .catch((error: unknown) => {
              if (
                controller.signal.aborted ||
                generation !== requestGeneration.current
              )
                return
              setMonitoringError(
                error instanceof ApiRequestError
                  ? error.message
                  : 'The monitoring response was unavailable.',
              )
            })
        }
      })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          generation !== requestGeneration.current
        )
          return
        setLoadState('unavailable')
        setLoadError(
          error instanceof ApiRequestError
            ? error.message
            : apiProblemMessage(error),
        )
      })
    return () => controller.abort()
  }, [assessmentId, client])

  async function attachPublication(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!assessmentId || !assessment || submitting || !input.trim()) return
    if (!validPostReference(input)) {
      setSubmitError(
        'Enter a numeric X post ID or a canonical HTTPS x.com/twitter.com status URL.',
      )
      return
    }
    const generation = requestGeneration.current
    setSubmitting(true)
    setSubmitError(null)
    try {
      const result = await client.linkPublication(assessmentId, {
        post_url_or_id: input.trim(),
      })
      if (generation !== requestGeneration.current) return
      if (!isPublication(result))
        throw malformedResponse('The publication response was invalid.')
      if (
        result.assessment_id !== assessment.assessment_id ||
        result.assessed_at !== assessment.assessed_at ||
        result.assessed_fingerprint !== assessment.input_fingerprint
      ) {
        setSubmitError(
          'The publication response did not match the original assessment.',
        )
        return
      }
      setPublication(result)
      setInput('')
      if (client.postmortem) {
        try {
          const postmortemResult = await client.postmortem(assessmentId)
          if (generation !== requestGeneration.current) return
          if (!isPostmortemRead(postmortemResult))
            throw malformedResponse('The postmortem response was invalid.')
          if (
            postmortemResult.assessment_id !== assessment.assessment_id ||
            postmortemResult.assessed_at !== assessment.assessed_at ||
            postmortemResult.original_outlook.assessment_id !==
              assessment.assessment_id ||
            postmortemResult.original_outlook.assessed_at !==
              assessment.assessed_at ||
            postmortemResult.original_outlook.input_fingerprint !==
              assessment.input_fingerprint ||
            (postmortemResult.published_post !== null &&
              postmortemResult.postmortem !== null &&
              postmortemResult.postmortem.published_post_id !==
                postmortemResult.published_post.canonical_post_id)
          )
            throw new ApiRequestError({
              code: 'postmortem_assessment_mismatch',
              message:
                'The postmortem response does not match this assessment.',
              status: 409,
            })
          setPostmortem(postmortemResult)
          setPostmortemError(null)
        } catch (error) {
          if (generation !== requestGeneration.current) return
          setPostmortemError(
            error instanceof ApiRequestError
              ? error.message
              : 'The postmortem response was unavailable.',
          )
        }
      }
      if (typeof client.monitoring === 'function') {
        try {
          const monitoringResult = await client.monitoring(assessmentId)
          if (generation !== requestGeneration.current) return
          if (!isMonitoringRead(monitoringResult))
            throw malformedResponse('The monitoring response was invalid.')
          if (!validateMonitoringIdentity(monitoringResult, assessment, result))
            throw new ApiRequestError({
              code: 'monitoring_assessment_mismatch',
              message:
                'The monitoring response does not match this assessment.',
              status: 409,
            })
          setMonitoring(monitoringResult)
          setMonitoringError(null)
        } catch (error) {
          if (generation !== requestGeneration.current) return
          setMonitoringError(
            error instanceof ApiRequestError
              ? error.message
              : 'The monitoring response was unavailable.',
          )
        }
      }
    } catch (error) {
      if (generation !== requestGeneration.current) return
      setSubmitError(publicationError(error) ?? 'No publication is linked yet.')
    } finally {
      setSubmitting(false)
    }
  }

  if (loadState === 'loading')
    return (
      <section className="workspace-card" role="status">
        <h2>Loading post monitoring</h2>
        <p>Retrieving the immutable assessment and its publication link.</p>
      </section>
    )

  if (loadState === 'unavailable' || !assessment)
    return (
      <section className="workspace-card" role="alert">
        <h2>Post monitoring is unavailable</h2>
        <p>{loadError ?? 'The assessment could not be loaded.'}</p>
        <p className="workspace-card__note">
          Monitoring observations and postmortem results are not exposed by the
          authenticated API yet. This screen does not simulate metrics or infer
          outcomes.
        </p>
      </section>
    )

  const metrics = assessment.metrics
  const comparableEvidence = assessment.comparable_evidence
  const observations = assessment.observations
  const assumptions = assessment.assumptions
  const limitations = assessment.limitations
  const retrievalLimitations = assessment.retrieval_coverage_limitations
  const acceptedHypothesis = isAcceptedHypothesis(
    assessment.accepted_hypothesis,
  )
    ? assessment.accepted_hypothesis
    : null

  return (
    <div className="monitoring-stack">
      {hasSyntheticProvenance({
        assessment,
        publication,
        monitoring,
        postmortem,
      }) && (
        <SyntheticDemoNotice>
          This assessment, publication link and monitoring record use the
          isolated backend seed.
        </SyntheticDemoNotice>
      )}
      <section className="workspace-card" aria-labelledby="assessment-title">
        <div className="workspace-card__header">
          <div className="workspace-card__mark" aria-hidden="true">
            ✓
          </div>
          <div>
            <p className="card-kicker">Immutable pre-publication record</p>
            <h2 id="assessment-title">Original Distribution Outlook</h2>
          </div>
        </div>
        <dl className="detail-list">
          <div>
            <dt>Assessment ID</dt>
            <dd>{assessment.assessment_id}</dd>
          </div>
          <div>
            <dt>Assessed</dt>
            <dd>{formatDate(assessment.assessed_at)}</dd>
          </div>
          <div>
            <dt>Decision</dt>
            <dd>
              {assessment.decision_state === 'supported'
                ? 'Supported'
                : 'Insufficient evidence'}
            </dd>
          </div>
          <div>
            <dt>Forecast metrics</dt>
            <dd>{metrics.length}</dd>
          </div>
        </dl>
        <p className="workspace-card__note">
          This original assessment is preserved. Publication results never
          overwrite its timestamp, evidence or forecast.
        </p>
      </section>

      <section className="workspace-card" aria-labelledby="outlook-title">
        <div className="workspace-card__header">
          <div>
            <p className="card-kicker">Original evidence snapshot</p>
            <h2 id="outlook-title">Outlook, evidence and limitations</h2>
          </div>
        </div>
        <dl className="detail-list">
          <div>
            <dt>Input fingerprint</dt>
            <dd>
              <code>{assessment.input_fingerprint}</code>
            </dd>
          </div>
          <div>
            <dt>Retrieval state</dt>
            <dd>{assessment.retrieval_state}</dd>
          </div>
          <div>
            <dt>Evidence coverage</dt>
            <dd>
              {assessment.retrieval_eligible_count} eligible of{' '}
              {assessment.retrieval_candidate_count} candidates
            </dd>
          </div>
          <div>
            <dt>Comparable evidence</dt>
            <dd>{comparableEvidence.length} supported items</dd>
          </div>
        </dl>

        <div className="monitoring-detail-grid">
          {metrics.length === 0 ? (
            <p className="workspace-card__note">
              No metric outlook was available in the saved assessment.
            </p>
          ) : (
            metrics.map((metric) => (
              <article
                className="monitoring-detail-card"
                key={`${metric.metric}-${metric.window}`}
              >
                <h3>{metric.metric}</h3>
                <p>
                  <strong>Definition:</strong> {metric.metric_definition}
                </p>
                <p>
                  <strong>Window:</strong> {metric.window}
                </p>
                <p>
                  <strong>Evidence:</strong> {metric.evidence_strength};
                  effective sample {metric.effective_sample_size};{' '}
                  {metric.eligible_post_count} eligible posts
                </p>
                {metric.outlook ? (
                  <p>
                    <strong>Historical range:</strong>{' '}
                    {metric.outlook.lower_p25}–{metric.outlook.upper_p75},
                    median {metric.outlook.median_p50}
                  </p>
                ) : (
                  <p className="workspace-card__note">
                    Historical range unavailable; no value was substituted.
                  </p>
                )}
                {metric.limitations.length > 0 && (
                  <p className="workspace-card__note">
                    Limitations: {metric.limitations.join(' ')}
                  </p>
                )}
              </article>
            ))
          )}
        </div>

        {acceptedHypothesis && (
          <div className="monitoring-detail-card">
            <h3>Optional accepted hypothesis</h3>
            <p>{acceptedHypothesis.question}</p>
            <p>
              <strong>Metric:</strong> {acceptedHypothesis.metric} ·{' '}
              {acceptedHypothesis.metric_definition} ·{' '}
              {acceptedHypothesis.window_kind}:{acceptedHypothesis.window_key}
            </p>
            <p>
              <strong>Expected direction:</strong>{' '}
              {acceptedHypothesis.expected_direction}
            </p>
          </div>
        )}

        {comparableEvidence.length > 0 && (
          <div className="monitoring-detail-card">
            <h3>Supported comparable evidence</h3>
            <ul>
              {comparableEvidence.map((item) => (
                <li key={item.post_id}>
                  Post {item.post_id}; relevance {item.relevance.toFixed(2)}
                  {item.inclusion_reasons.length > 0
                    ? ` — ${item.inclusion_reasons.join('; ')}`
                    : ''}
                </li>
              ))}
            </ul>
          </div>
        )}

        {observations.length > 0 && (
          <div className="monitoring-detail-card">
            <h3>Historical observations</h3>
            <ul>
              {observations.map((item, index) => (
                <li key={`${item.kind}-${item.metric ?? 'unknown'}-${index}`}>
                  <strong>{item.kind}</strong>: {item.explanation} (
                  {item.evidence_strength}){item.metric && ` · ${item.metric}`}
                  {item.window && ` · ${item.window}`}
                  {item.limitations.length > 0 && (
                    <span className="workspace-card__note">
                      {' '}
                      Limitations: {item.limitations.join(' ')}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {(assumptions.length > 0 ||
          limitations.length > 0 ||
          retrievalLimitations.length > 0) && (
          <div className="monitoring-detail-card">
            <h3>Assessment limitations</h3>
            {[...assumptions, ...limitations, ...retrievalLimitations].map(
              (item, index) => (
                <p key={`${item}-${index}`}>{item}</p>
              ),
            )}
          </div>
        )}
      </section>

      <section className="workspace-card" aria-labelledby="publication-title">
        <div className="workspace-card__header">
          <div>
            <p className="card-kicker">Manual creator action</p>
            <h2 id="publication-title">Published X post</h2>
          </div>
        </div>
        {publicationErrorState && <p role="alert">{publicationErrorState}</p>}
        {publication ? (
          <div role="status">
            <p>
              <strong>Linked post:</strong> {publication.external_post_id}
            </p>
            <p>
              <strong>Published:</strong> {formatDate(publication.published_at)}
            </p>
            <p>
              <strong>Version check:</strong>{' '}
              {publication.version_match_state === 'match'
                ? 'Matches the assessed version'
                : publication.version_match_state === 'mismatch'
                  ? 'Does not match the assessed version'
                  : 'Could not verify the assessed version'}
            </p>
            <p>
              <strong>Linked at:</strong> {formatDate(publication.linked_at)}
            </p>
          </div>
        ) : (
          <form onSubmit={attachPublication}>
            <label htmlFor="post-reference">
              X post URL or numeric post ID
            </label>
            <input
              id="post-reference"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="https://x.com/.../status/123"
              autoComplete="off"
            />
            <p className="workspace-card__note">
              The server validates the URL or ID, creator ownership, publication
              time and assessed-version identity before linking. Viewing the
              existing publication status does not call X. Submitting may start
              an authorized, potentially billable official X verification;
              backend access, rights, budget and account-ownership gates remain
              authoritative.
            </p>
            {submitError && <p role="alert">{submitError}</p>}
            <button
              className="button button--primary"
              type="submit"
              disabled={submitting || !input.trim()}
            >
              {submitting ? 'Verifying publication…' : 'Verify and attach post'}
            </button>
          </form>
        )}
      </section>

      <section className="workspace-card" aria-labelledby="monitoring-title">
        <div className="workspace-card__header">
          <div>
            <p className="card-kicker">Read-only creator monitoring</p>
            <h2 id="monitoring-title">Observation windows</h2>
          </div>
        </div>
        {monitoring ? (
          <div role="status">
            <p>
              <strong>Monitoring state:</strong>{' '}
              {monitoring.state.replaceAll('_', ' ')}
            </p>
            {monitoring.published_post && (
              <p>
                <strong>Monitoring publication:</strong>{' '}
                {monitoring.published_post.external_post_id} ·{' '}
                {monitoring.published_post.availability}
              </p>
            )}
            <div className="monitoring-detail-grid">
              {monitoring.windows.map((window) => (
                <article
                  className="monitoring-detail-card"
                  key={window.window_key}
                >
                  <h3>{window.window_key}</h3>
                  <p>
                    <strong>Due:</strong> {formatDate(window.due_at)}
                  </p>
                  <p>
                    <strong>Scheduled:</strong>{' '}
                    {window.scheduled_at
                      ? formatDate(window.scheduled_at)
                      : 'Not scheduled'}
                  </p>
                  <p>
                    <strong>Finished:</strong>{' '}
                    {window.finished_at
                      ? formatDate(window.finished_at)
                      : 'Not finished'}
                  </p>
                  <p>
                    <strong>Execution:</strong>{' '}
                    {window.execution_state.replaceAll('_', ' ')}
                  </p>
                  <p>
                    <strong>Measurement:</strong>{' '}
                    {window.measurement_state.replaceAll('_', ' ')}
                  </p>
                  {window.receipt_id && (
                    <p>
                      <strong>Receipt:</strong> {window.receipt_id}
                    </p>
                  )}
                  {window.failure_code && (
                    <p className="workspace-card__note">
                      <strong>Limitation:</strong>{' '}
                      {window.failure_code.replaceAll('_', ' ')}
                    </p>
                  )}
                  {window.execution_state === 'not_scheduled' && (
                    <p className="workspace-card__note">
                      No receipt was scheduled for this window.
                    </p>
                  )}
                  {window.observations.length > 0 ? (
                    window.observations.map((observation) => (
                      <p key={observation.id}>
                        <strong>{observation.metric}:</strong>{' '}
                        {observation.value === null
                          ? 'Unavailable'
                          : observation.value}{' '}
                        {observation.unit} · {observation.state} ·{' '}
                        {observation.source} · observed{' '}
                        {formatDate(observation.observed_at)} · age{' '}
                        {observation.observed_age_seconds}s
                        {observation.missing_reason &&
                          ` · ${observation.missing_reason.replaceAll('_', ' ')}`}
                      </p>
                    ))
                  ) : (
                    <p className="workspace-card__note">
                      No observation was returned; no zero value was inferred.
                    </p>
                  )}
                </article>
              ))}
            </div>
            {monitoring.limitations.length > 0 && (
              <div className="monitoring-detail-card">
                <h3>Monitoring limitations</h3>
                {monitoring.limitations.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            )}
          </div>
        ) : monitoringError ? (
          <p role="status">{monitoringError}</p>
        ) : (
          <p role="status">Loading monitoring windows.</p>
        )}
        <p className="workspace-card__note">
          This screen reads persisted monitoring only. It does not perform paid
          X reads, schedule receipts or turn unavailable readings into zeros.
          Monitoring receipts now come from the COD-422 read contract. The
          COD-422 monitoring read contract is the source for these
          creator-scoped receipt and observation details.
        </p>
      </section>

      <section className="workspace-card" aria-labelledby="postmortem-title">
        <div className="workspace-card__header">
          <div>
            <p className="card-kicker">Evidence-aware outcome</p>
            <h2 id="postmortem-title">Postmortem and observations</h2>
          </div>
        </div>
        {postmortem ? (
          <div role="status">
            <p>
              <strong>Evaluation state:</strong>{' '}
              {postmortem.state.replaceAll('_', ' ')}
            </p>
            <p>
              <strong>Assessment:</strong> {postmortem.assessment_id} · assessed{' '}
              {formatDate(postmortem.assessed_at)}
            </p>
            {postmortem.published_post && (
              <p>
                <strong>Observed publication:</strong>{' '}
                {postmortem.published_post.external_post_id} · published{' '}
                {formatDate(postmortem.published_post.published_at)} ·{' '}
                {postmortem.published_post.version_match_state === 'match'
                  ? 'version matched'
                  : postmortem.published_post.version_match_state === 'mismatch'
                    ? 'version mismatch'
                    : 'version unverified'}
              </p>
            )}
            {postmortem.postmortem ? (
              <div className="monitoring-detail-grid">
                {postmortem.postmortem.metric_comparisons.map((metric) => (
                  <article
                    className="monitoring-detail-card"
                    key={`${metric.metric}-${metric.window_key}`}
                  >
                    <h3>{metric.metric}</h3>
                    <p>
                      <strong>Observed:</strong>{' '}
                      {metric.observed_value === null
                        ? 'Unavailable'
                        : metric.observed_value}{' '}
                      {metric.unit}; {metric.status}
                    </p>
                    <p>
                      <strong>Measurement:</strong>{' '}
                      {metric.observed_at
                        ? formatDate(metric.observed_at)
                        : 'No actual observation timestamp'}{' '}
                      · {metric.window_kind}:{metric.window_key}
                    </p>
                    {metric.reference_range && (
                      <p>
                        <strong>Historical reference:</strong>{' '}
                        {metric.reference_range.lower_p25}–
                        {metric.reference_range.upper_p75}, median{' '}
                        {metric.reference_range.median_p50}
                      </p>
                    )}
                    {metric.limitations.length > 0 && (
                      <p className="workspace-card__note">
                        Limitations: {metric.limitations.join(' ')}
                      </p>
                    )}
                  </article>
                ))}
                {postmortem.postmortem.hypothesis_evaluation && (
                  <article className="monitoring-detail-card">
                    <h3>Hypothesis evaluation</h3>
                    <p>
                      The returned evaluation is{' '}
                      {postmortem.postmortem.hypothesis_evaluation.status}.
                    </p>
                  </article>
                )}
              </div>
            ) : (
              <p className="workspace-card__note">
                No eligible postmortem result was returned; no forecast accuracy
                or causal conclusion is inferred.
              </p>
            )}
            {postmortem.limitations.length > 0 && (
              <div className="monitoring-detail-card">
                <h3>Postmortem limitations</h3>
                {postmortem.limitations.map((item) => (
                  <p key={item}>{item}</p>
                ))}
              </div>
            )}
          </div>
        ) : postmortemError ? (
          <p role="alert">{postmortemError}</p>
        ) : (
          <p role="status">Loading the evidence-aware postmortem.</p>
        )}
        <p className="workspace-card__note">
          Postmortem conclusions remain evidence-aware and never treat a missing
          reading as zero. Monitoring lifecycle details are shown in the
          read-only observation windows above.
        </p>
      </section>
    </div>
  )
}
