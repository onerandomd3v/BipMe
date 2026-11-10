import { describe, expect, it } from 'vitest'
import { ApiRequestError } from './api/client'
import { latestReportFixture } from './api/fixtures'
import {
  apiProblemMessage,
  dashboardLoadState,
  recordList,
  reportCoverageLabel,
  reportIsStale,
  suggestionsForReport,
} from './dashboardModel'

describe('Creator Intelligence dashboard states', () => {
  it('keeps onboarding and import states separate from an available report', () => {
    expect(dashboardLoadState('not_configured', null)).toBe('onboarding')
    expect(
      dashboardLoadState('configured', {
        status: 'awaiting_import',
        latest_report: null,
      }),
    ).toBe('awaiting-import')
    expect(dashboardLoadState('configured', latestReportFixture)).toBe('report')
  })

  it('labels partial reports and historical evidence honestly', () => {
    expect(reportCoverageLabel('personal_only_partial')).toBe(
      'Personal-only partial report',
    )
    expect(reportIsStale(latestReportFixture.latest_report!)).toBe(true)
  })

  it('maps authentication, rate-limit and validation failures to user states', () => {
    expect(
      apiProblemMessage(
        new ApiRequestError({
          code: 'authentication_required',
          message: 'Sign in',
          status: 401,
        }),
      ),
    ).toContain('Sign in')
    expect(
      apiProblemMessage(
        new ApiRequestError({
          code: 'rate_limited',
          message: 'Slow down',
          status: 429,
        }),
      ),
    ).toContain('rate-limited')
  })

  it('rejects non-record evidence values before rendering', () => {
    expect(
      recordList([{ source_id: 'source-1' }, 'private text', null]),
    ).toEqual([{ source_id: 'source-1' }])
  })

  it('maps conflict codes and caps deduplicated suggestions', () => {
    expect(
      apiProblemMessage(
        new ApiRequestError({
          code: 'idempotency_key_reused',
          message: 'Conflict',
          status: 409,
        }),
      ),
    ).toContain('different input')
    const report = {
      ...latestReportFixture.latest_report!,
      report: {
        experiments: [
          { hypothesis: 'Same idea' },
          { hypothesis: 'Same idea' },
          { hypothesis: 'Second idea' },
        ],
        opportunities: [{ summary: 'Third idea' }, { summary: 'Fourth idea' }],
      },
    }
    expect(suggestionsForReport(report)).toHaveLength(3)
  })
})
