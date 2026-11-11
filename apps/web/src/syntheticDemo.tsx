import type { ReactNode } from 'react'

export const SYNTHETIC_DEMO_LABEL =
  'Synthetic demonstration data — not live X evidence'

const SYNTHETIC_KEYS = new Set([
  'assessment',
  'authorization_basis',
  'coverage_note',
  'evidence',
  'latestImport',
  'limitations',
  'monitoring',
  'observations',
  'original_outlook',
  'page',
  'postmortem',
  'publication',
  'provenance',
  'report',
  'response',
  'source',
  'source_label',
  'sources',
  'items',
  'windows',
])

export function hasSyntheticProvenance(value: unknown): boolean {
  if (typeof value === 'string')
    return (
      value === SYNTHETIC_DEMO_LABEL ||
      value === 'synthetic_demo' ||
      value === 'synthetic_demo_fixture'
    )
  if (Array.isArray(value)) return value.some(hasSyntheticProvenance)
  if (!value || typeof value !== 'object') return false
  return Object.entries(value).some(
    ([key, entry]) => SYNTHETIC_KEYS.has(key) && hasSyntheticProvenance(entry),
  )
}

export function SyntheticDemoNotice({ children }: { children?: ReactNode }) {
  return (
    <aside className="synthetic-demo-notice" role="note">
      <strong>{SYNTHETIC_DEMO_LABEL}</strong>
      {children && <span>{children}</span>}
    </aside>
  )
}
