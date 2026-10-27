import { useEffect, useRef, useState } from 'react'
import { LogIn } from 'lucide-react'
import { useApi } from '../api/ApiContext'
import { Alert, Button, Card, inputClass } from '../components/ui'
import { GOOGLE_CLIENT_ID } from '../config'
import { useAuth } from './AuthContext'

function loadGoogleScript() {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve()
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = resolve
    s.onerror = reject
    document.head.appendChild(s)
  })
}

/** Google sign-in for college accounts. In development, also a picker of test users. */
export default function LoginPage() {
  const api = useApi()
  const { loginWithGoogle, loginDev } = useAuth()
  const buttonBox = useRef(null)
  const [error, setError] = useState(null)
  const [devUsers, setDevUsers] = useState([])
  const [devEmail, setDevEmail] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.devUsers().then((list) => { setDevUsers(list); setDevEmail(list[0]?.email || '') }).catch(() => {})   // 404 in production
  }, [api])

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) return undefined
    let cancelled = false
    loadGoogleScript().then(() => {
      if (cancelled || !buttonBox.current) return
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (response) => {
          setError(null)
          try { await loginWithGoogle(response.credential) } catch (e) { setError(e) }
        },
      })
      window.google.accounts.id.renderButton(buttonBox.current, { theme: 'filled_black', size: 'large', text: 'signin_with', shape: 'pill' })
    }).catch(() => setError(new Error('Could not load Google sign-in. Check your connection.')))
    return () => { cancelled = true }
  }, [loginWithGoogle])

  async function devSubmit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try { await loginDev(devEmail) } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <div className="mx-auto max-w-md space-y-4 py-10">
      <Card className="space-y-4 text-center">
        <LogIn className="mx-auto h-8 w-8 text-purple-300" aria-hidden="true" />
        <h1 className="text-xl font-semibold text-white">Sign in to the grievance system</h1>
        <p className="text-sm text-white/60">Use your college Google account.</p>
        {GOOGLE_CLIENT_ID
          ? <div ref={buttonBox} className="flex justify-center" data-testid="google-button" />
          : devUsers.length === 0 && <Alert tone="warn">Sign-in is not configured yet. Ask the admin office.</Alert>}
        {error && <Alert tone="error">{error.message}</Alert>}
      </Card>

      {devUsers.length > 0 && (
        <Card className="space-y-3">
          <p className="text-sm font-medium text-amber-200">Development only: sign in as a test user</p>
          <form onSubmit={devSubmit} className="flex gap-2">
            <select aria-label="Test user" value={devEmail} onChange={(e) => setDevEmail(e.target.value)} className={inputClass} style={{ colorScheme: 'dark' }}>
              {devUsers.map((u) => <option key={u.email} value={u.email}>{u.name} ({u.role})</option>)}
            </select>
            <Button type="submit" loading={busy}>Sign in</Button>
          </form>
        </Card>
      )}
    </div>
  )
}
