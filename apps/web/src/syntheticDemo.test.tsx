import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  hasSyntheticProvenance,
  SYNTHETIC_DEMO_LABEL,
  SyntheticDemoNotice,
} from './syntheticDemo'

describe('synthetic demo provenance', () => {
  it('recognizes only backend provenance signals', () => {
    expect(hasSyntheticProvenance({ source: 'synthetic_demo' })).toBe(true)
    expect(
      hasSyntheticProvenance({
        source: 'authorized_x_api',
        text: SYNTHETIC_DEMO_LABEL,
      }),
    ).toBe(false)
    expect(hasSyntheticProvenance({ demo: true })).toBe(false)
  })

  it('renders the exact accessible label', () => {
    render(<SyntheticDemoNotice />)
    expect(screen.getByRole('note')).toHaveTextContent(SYNTHETIC_DEMO_LABEL)
  })
})
