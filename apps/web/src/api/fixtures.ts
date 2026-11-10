import type { components } from './generated/schema'

export const healthFixture = { status: 'ok' } satisfies Record<string, string>

export const sessionFixture = {
  authenticated: true,
  csrf_token: 'synthetic-csrf-token',
} satisfies components['schemas']['SessionResponse']

export const errorFixture = {
  error: {
    code: 'authentication_required',
    message: 'A private creator session is required.',
    fields: null,
  },
} satisfies components['schemas']['ErrorResponse']

export const profileFixture = {
  status: 'configured',
  profile: {
    creator_key: '00000000-0000-0000-0000-000000000379',
    revision: 1,
    version: 'creator-goals-v1',
    recorded_at: '2026-11-09T12:00:00Z',
    niche: 'Independent product design',
    intended_audience: 'Early-stage product teams',
    priority_outcomes: ['conversation'],
    preferred_styles: ['personal_story'],
    language: 'en',
  },
} satisfies components['schemas']['CreatorProfileStateResponse']

export const permissionFixture = {
  personal_history: 'granted',
  personal_history_revision: 1,
  recorded_at: '2026-11-09T12:01:00Z',
  x_history_processing: 'blocked',
  niche_discovery: 'unavailable',
  external_synthesis: 'disabled',
} satisfies components['schemas']['DataPermissionResponse']

export const reportFixture = {
  id: '00000000-0000-0000-0000-000000000380',
  creator_key: '00000000-0000-0000-0000-000000000379',
  generated_at: '2026-11-09T12:02:00Z',
  as_of: '2026-11-09T12:02:00Z',
  goals_revision: 1,
  goals_version: 'creator-goals-v1',
  evidence_version: 'creator-report-evidence-v2',
  report_version: 'creator-intelligence-report-v2',
  baseline_version: 'creator-baseline-v1',
  processing_status: 'completed',
  coverage: 'personal_only_partial',
  freshness: { personal_history: 'historical', niche_discovery: 'unavailable' },
  processing_permissions: {
    personal_history: { status: 'blocked_by_source_policy' },
    niche_discovery: { status: 'unavailable', external_requests: 0 },
    external_synthesis: { status: 'disabled', provider_calls: 0 },
  },
  limitations: [
    'Niche discovery is unavailable and was not requested; this endpoint makes no external request.',
    'No available creator-owned canonical history is available yet.',
  ],
  evidence: { sources: [], observations: [], profiles: [] },
  report: {
    state: 'personal_only_partial',
    personal_findings: [],
    niche_findings: [],
    experiments: [],
    opportunities: [],
    personal_cohorts: [],
    content_patterns: [],
    limitations: [],
    synthesis_mode: 'deterministic_fallback',
  },
} satisfies components['schemas']['CreatorReportResponse']

export const latestReportFixture = {
  status: 'available',
  latest_report: reportFixture,
} satisfies components['schemas']['CreatorReportStateResponse']
