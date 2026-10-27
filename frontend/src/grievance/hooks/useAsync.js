import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Run an async function when the component mounts (and when deps change).
 * Returns { data, error, loading, reload, setData }. Late answers from old calls are ignored.
 */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const run = useRef(0)
  const fnRef = useRef(fn)
  fnRef.current = fn

  const load = useCallback(async () => {
    const mine = ++run.current
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const data = await fnRef.current()
      if (mine === run.current) setState({ data, error: null, loading: false })
    } catch (error) {
      if (mine === run.current) setState((s) => ({ data: s.data, error, loading: false }))
    }
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, deps)
  useEffect(() => () => { run.current++ }, [])

  const setData = useCallback((data) => setState((s) => ({ ...s, data })), [])
  return { ...state, reload: load, setData }
}
