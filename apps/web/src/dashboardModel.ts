import type { components } from './api/generated/schema'
import { ApiRequestError } from './api/client'

type Report = components['schemas']['CreatorReportResponse']
type ReportState = components['schemas']['CreatorReportStateResponse']

export type DraftAnalysisContext = {
  creatorKey: string
  reportId: string
  goalsRevision: number
  reportAsOf: string
  coverage: Report['coverage']
}

export type DashboardSuggestion = {
  kind: 'hypothesis' | 'opportunity'
  text: string
  evidenceStrength: string
  evidenceIds: string[]
  metric?: string
  personalEvidenceIds?: string[]
  nicheEvidenceIds?: string[]
}

export type DashboardLoadState =
  'loading' | 'onboarding' | 'awaiting-import' | 'report' | 'error'

export function dashboardLoadState(
  profileStatus: 'configured' | 'not_configured' | null,
  reportState: ReportState | null,
): DashboardLoadState {
  if (profileStatus === 'not_configured') return 'onboarding'
  if (!reportState || reportState.status === 'awaiting_profile')
    return 'onboarding'
  if (reportState.status === 'awaiting_import') return 'awaiting-import'
  return 'report'
}

export function reportCoverageLabel(coverage: Report['coverage']) {
  switch (coverage) {
    case 'personal_and_niche':
      return 'Personal + niche evidence'
    case 'personal_only_partial':
      return 'Personal-only partial report'
    case 'insufficient_evidence':
      return 'Insufficient evidence'
  }
}

export function reportIsStale(report: Report) {
  return Object.values(report.freshness).some(
    (value) => value === 'stale' || value === 'historical',
  )
}

export function nicheAvailability(report: Report) {
  const content = recordValue(report.report)
  const findings = recordList(content?.niche_findings)
  const permission = recordValue(
    recordValue(report.processing_permissions)?.niche_discovery,
  )
  const status =
    typeof permission?.status === 'string' ? permission.status : null
  const freshness = report.freshness.niche_discovery
  if (report.coverage === 'personal_and_niche' && findings.length > 0)
    return { label: 'Available', detail: `${freshness ?? 'current'} evidence` }
  if (status === 'unavailable' || status === 'disabled')
    return { label: 'Unavailable', detail: 'No permitted niche evidence' }
  if (freshness === 'stale' || freshness === 'historical')
    return {
      label: 'Historical',
      detail: 'Not current enough for niche trends',
    }
  return { label: 'Unknown', detail: 'No niche findings in this snapshot' }
}

export function suggestionsForReport(report: Report): DashboardSuggestion[] {
  const content = recordValue(report.report)
  const candidates: DashboardSuggestion[] = [
    ...recordList(content?.experiments).map((item) => ({
      kind: 'hypothesis' as const,
      text: stringValue(item.hypothesis, 'Test a declared approach'),
      evidenceStrength: stringValue(item.evidence_strength, 'Unknown'),
      evidenceIds: stringList(item.evidence_ids),
    })),
    ...recordList(content?.opportunities).map((item) => ({
      kind: 'opportunity' as const,
      text: stringValue(item.summary, 'Test this bounded opportunity'),
      evidenceStrength: stringValue(item.evidence_strength, 'Unknown'),
      evidenceIds: stringList(item.evidence_ids),
      metric: stringValue(item.metric, 'not specified'),
      personalEvidenceIds: stringList(item.personal_evidence_ids),
      nicheEvidenceIds: stringList(item.niche_evidence_ids),
    })),
  ]
  const seen = new Set<string>()
  return candidates
    .filter((candidate) => {
      const key = candidate.text.trim().toLocaleLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, 3)
}

export function apiProblemMessage(error: unknown) {
  if (!(error instanceof ApiRequestError))
    return 'The report service could not be reached. Your existing data has not been changed.'
  if (error.status === 401)
    return 'Sign in to view your private creator report.'
  if (error.status === 403)
    return 'This action is not permitted for the current creator session.'
  if (error.status === 409)
    return error.code === 'idempotency_key_reused'
      ? 'This report request key was already used for different input. Try again to create a fresh request.'
      : error.code === 'creator_profile_required'
        ? 'Complete the creator profile before generating a report.'
        : error.message || 'The report request conflicts with existing state.'
  if (error.status === 429)
    return 'The report service is rate-limited. Try again later; no automatic retry was made.'
  if (error.code === 'report_unavailable')
    return 'The latest report is temporarily unavailable.'
  return error.message || 'The report service returned an error.'
}

export function recordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> =>
        Boolean(item && typeof item === 'object'),
      )
    : []
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function stringValue(value: unknown, fallback: string) {
  return typeof value === 'string' && value.trim() ? value : fallback
}

export function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}
