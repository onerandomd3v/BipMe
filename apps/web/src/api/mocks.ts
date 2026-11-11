import { http, HttpResponse } from 'msw'
import {
  draftAssessmentFixture,
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
  publicationLinkFixture,
  postmortemFixture,
  monitoringFixture,
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
  http.get('*/api/v1/creators/me/draft-assessments/:assessmentId', () =>
    HttpResponse.json(draftAssessmentFixture),
  ),
  http.get(
    '*/api/v1/creators/me/draft-assessments/:assessmentId/publication',
    () => HttpResponse.json(publicationLinkFixture),
  ),
  http.post(
    '*/api/v1/creators/me/draft-assessments/:assessmentId/publication',
    () => HttpResponse.json(publicationLinkFixture, { status: 201 }),
  ),
  http.get(
    '*/api/v1/creators/me/draft-assessments/:assessmentId/postmortem',
    () => HttpResponse.json(postmortemFixture),
  ),
  http.get(
    '*/api/v1/creators/me/draft-assessments/:assessmentId/monitoring',
    () => HttpResponse.json(monitoringFixture),
  ),
  http.get('*/api/v1/creators/me/history/imports', () =>
    HttpResponse.json(historyImportFixture),
  ),
  http.get('*/api/v1/creators/me/history/posts', () =>
    HttpResponse.json(historyPostsFixture),
  ),
  http.get('*/api/v1/creators/me/baseline', () =>
    HttpResponse.json(baselineFixture),
  ),
  http.get('*/api/v1/creators/me/history/evidence', () =>
    HttpResponse.json(evidenceFixture),
  ),
  http.post('*/api/v1/creators/me/draft-assessments', () =>
    HttpResponse.json(draftAnalysisFixture, { status: 201 }),
  ),
  http.get('*/api/v1/creators/me/draft-assessments/:assessmentId', () =>
    HttpResponse.json(draftAnalysisFixture),
  ),
]
