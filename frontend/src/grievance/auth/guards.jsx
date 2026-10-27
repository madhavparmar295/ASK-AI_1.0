import { Link } from 'react-router-dom'
import { href } from '../config'
import { ErrorBox, Spinner } from '../components/ui'
import { useAuth } from './AuthContext'
import LoginPage from './LoginPage'

export function NotFound() {
  return (
    <div className="py-16 text-center text-white/70">
      <p className="text-lg font-medium text-white">Page not found</p>
      <p className="mt-1 text-sm">This page does not exist, or you do not have access to it.</p>
      <Link to={href()} className="mt-4 inline-block text-purple-300 underline">Go to the start page</Link>
    </div>
  )
}

/** Shows the sign-in page until someone is signed in. */
export function RequireAuth({ children }) {
  const { status, error, refresh } = useAuth()
  if (status === 'loading') return <Spinner label="Checking your session…" />
  if (status === 'error') return <div className="py-10"><ErrorBox error={error} onRetry={refresh} /></div>
  if (status === 'anon') return <LoginPage />
  return children
}

/** Menu hiding is only a courtesy. The server checks every request again. */
export function RequireRole({ roles, children }) {
  const { me } = useAuth()
  return me && roles.includes(me.role) ? children : <NotFound />
}
