import { http, HttpResponse } from 'msw'
import {
  draftAnalysisFixture,
  evidenceFixture,
  healthFixture,
  latestReportFixture,
  permissionFixture,
  profileFixture,
  sessionFixture,
  baselineFixture,
  historyImportFixture,
  historyPostsFixture,
} from './fixtures'

export const apiHandlers = [
  http.get('*/api/health', () => HttpResponse.json(healthFixture)),
  http.get('*/api/auth/session', () => HttpResponse.json(sessionFixture)),
  http.post('*/api/auth/private/session', () =>
    HttpResponse.json(sessionFixture),
  ),
  http.post('*/api/auth/logout', () => new HttpResponse(null, { status: 204 })),
  http.get('*/api/v1/creators/me/profile', () =>
    HttpResponse.json(profileFixture),
  ),
  http.get('*/api/v1/creators/me/data-permissions', () =>
    HttpResponse.json(permissionFixture),
  ),
  http.get('*/api/v1/creators/me/report/latest', () =>
    HttpResponse.json(latestReportFixture),
  ),
  http.put('*/api/v1/creators/me/profile', () =>
    HttpResponse.json(profileFixture.profile),
  ),
  http.put('*/api/v1/creators/me/data-permissions', () =>
    HttpResponse.json(permissionFixture),
  ),
  http.post('*/api/v1/creators/me/report', () =>
    HttpResponse.json(latestReportFixture.latest_report),
  ),
  http.delete(
    '*/api/v1/creators/me/reports',
    () => new HttpResponse(null, { status: 204 }),
  ),
  http.post('*/api/v1/creators/me/draft-assessments', () =>
    HttpResponse.json(draftAnalysisFixture, { status: 201 }),
  ),
  http.get('*/api/v1/creators/me/draft-assessments/:assessmentId', () =>
    HttpResponse.json(draftAnalysisFixture),
  ),
  http.get('*/api/v1/creators/me/history/evidence', () =>
    HttpResponse.json(evidenceFixture),
  ),
]
