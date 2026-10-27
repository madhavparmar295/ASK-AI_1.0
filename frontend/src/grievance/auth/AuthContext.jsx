import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useApi } from '../api/ApiContext'

const AuthContext = createContext(null)

export const isStaff = (me) => !!me && (me.role === 'staff' || me.role === 'officer')

/**
 * Knows who is signed in. status: 'loading' | 'authed' | 'anon' | 'error'.
 * The server session is a cookie; this only mirrors the answer of GET /me.
 */
export function AuthProvider({ children }) {
  const api = useApi()
  const [state, setState] = useState({ status: 'loading', me: null, error: null })

  const refresh = useCallback(async () => {
    try {
      setState({ status: 'authed', me: await api.me(), error: null })
    } catch (e) {
      setState(e.status === 401 ? { status: 'anon', me: null, error: null } : { status: 'error', me: null, error: e })
    }
  }, [api])

  useEffect(() => {
    // Any later 401 means the session ended: show the sign-in page again.
    api.client?.setOnUnauthorized?.(() => setState({ status: 'anon', me: null, error: null }))
    refresh()
  }, [api, refresh])

  const loginWithGoogle = useCallback(async (credential) => {
    const me = await api.googleLogin(credential)
    setState({ status: 'authed', me, error: null })
  }, [api])

  const loginDev = useCallback(async (email) => {
    const me = await api.devLogin(email)
    setState({ status: 'authed', me, error: null })
  }, [api])

  const logout = useCallback(async () => {
    try { await api.logout() } catch { /* the cookie may already be gone */ }
    setState({ status: 'anon', me: null, error: null })
  }, [api])

  const value = useMemo(() => ({ ...state, refresh, loginWithGoogle, loginDev, logout }), [state, refresh, loginWithGoogle, loginDev, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
