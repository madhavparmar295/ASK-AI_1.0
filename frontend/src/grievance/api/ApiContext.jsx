import { createContext, useContext, useMemo } from 'react'
import { createApi } from './endpoints'

const ApiContext = createContext(null)

export function ApiProvider({ api, children }) {
  const value = useMemo(() => api || createApi(), [api])
  return <ApiContext.Provider value={value}>{children}</ApiContext.Provider>
}

export function useApi() {
  const api = useContext(ApiContext)
  if (!api) throw new Error('useApi must be used inside <ApiProvider>')
  return api
}
