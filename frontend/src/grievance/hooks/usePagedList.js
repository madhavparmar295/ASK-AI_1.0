import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * A list loaded page by page. fetchPage({ offset, limit }) must return { items, total }.
 * Reloads from the start whenever deps change.
 */
export function usePagedList(fetchPage, deps = [], pageSize = 20) {
  const [state, setState] = useState({ items: [], total: 0, loading: true, loadingMore: false, error: null })
  const run = useRef(0)
  const fetchRef = useRef(fetchPage)
  fetchRef.current = fetchPage

  const load = useCallback(async (offset = 0) => {
    const mine = ++run.current
    setState((s) => ({ ...s, loading: offset === 0, loadingMore: offset > 0, error: null }))
    try {
      const page = await fetchRef.current({ offset, limit: pageSize })
      if (mine !== run.current) return
      setState((s) => ({
        items: offset === 0 ? page.items : [...s.items, ...page.items],
        total: page.total, loading: false, loadingMore: false, error: null,
      }))
    } catch (error) {
      if (mine === run.current) setState((s) => ({ ...s, loading: false, loadingMore: false, error }))
    }
  }, [pageSize])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(0) }, deps)
  useEffect(() => () => { run.current++ }, [])

  return {
    ...state,
    hasMore: state.items.length < state.total,
    reload: () => load(0),
    loadMore: () => load(state.items.length),
    setItems: (fn) => setState((s) => ({ ...s, items: fn(s.items) })),
  }
}
