import { useEffect, useRef } from 'react'

/** Call fn every `ms` while enabled and the browser tab is visible. */
export function useInterval(fn, ms, enabled = true) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (!enabled) return undefined
    const id = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState !== 'hidden') ref.current()
    }, ms)
    return () => clearInterval(id)
  }, [ms, enabled])
}
