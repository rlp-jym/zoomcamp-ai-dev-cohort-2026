export const show = (v: unknown): string =>
  v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v))
    ? '—'
    : String(v)

export function formatClock(clockSeconds: number | null | undefined): string {
  if (clockSeconds === null || clockSeconds === undefined || Number.isNaN(clockSeconds)) {
    return '—'
  }
  const total = Math.max(0, Math.floor(clockSeconds))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

export function formatGold(gold: number | null | undefined): string {
  if (gold === null || gold === undefined || Number.isNaN(gold)) {
    return '—'
  }
  return `${(gold / 1000).toFixed(1)}k`
}

/** Width ratio for the gold bar only — raw numbers are still shown as text. */
export function goldShare(home: number | null, away: number | null): number | null {
  if (home === null || away === null) {
    return null
  }
  const total = home + away
  if (total <= 0) {
    return null
  }
  return home / total
}
