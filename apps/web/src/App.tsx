import { useEffect, useState } from 'react'

interface ApiHealth {
  status: string
}

export function App() {
  const [health, setHealth] = useState('Checking API...')

  useEffect(() => {
    fetch('/api/health')
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`API returned ${response.status}`)
        }
        return (await response.json()) as ApiHealth
      })
      .then((result) => setHealth(result.status === 'ok' ? 'Connected' : 'Unavailable'))
      .catch(() => setHealth('API unavailable'))
  }, [])

  return (
    <main className="shell">
      <p className="eyebrow">BipMe / Development</p>
      <h1>Creator intelligence, grounded in your own data.</h1>
      <p>
        Initial foundation: creator-specific baselines, historical comparables,
        and evidence-backed distribution outlooks.
      </p>
      <p className="status">
        API status: <strong>{health}</strong>
      </p>
      <p className="footnote">X sign-in and intelligence features are not implemented yet.</p>
    </main>
  )
}
