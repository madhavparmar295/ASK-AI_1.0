import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiProvider } from './api/ApiContext'
import { AuthProvider, isStaff, useAuth } from './auth/AuthContext'
import { NotFound, RequireAuth, RequireRole } from './auth/guards'
import { ToastProvider } from './components/Toast'
import { href } from './config'
import GrievanceLayout from './layout/GrievanceLayout'
import NotificationsPage from './pages/NotificationsPage'
import TicketPage from './pages/TicketPage'
import AdminRoutes from './pages/admin/AdminRoutes'
import QueuePage from './pages/staff/QueuePage'
import MyIssuesPage from './pages/student/MyIssuesPage'
import NewIssuePage from './pages/student/NewIssuePage'

function Home() {
  const { me } = useAuth()
  return <Navigate replace to={href(isStaff(me) ? 'queue' : 'issues')} />
}

const STAFF = ['staff', 'officer']

/**
 * All grievance pages, relative to /grievance. Use this inside the chatbot's existing router:
 *     <Route path="/grievance/*" element={<GrievanceRoutes />} />
 */
export function GrievanceRoutes({ api }) {
  return (
    <ApiProvider api={api}>
      <AuthProvider>
        <ToastProvider>
          <GrievanceLayout>
            <RequireAuth>
              <Routes>
                <Route index element={<Home />} />
                <Route path="issues" element={<MyIssuesPage />} />
                <Route path="new" element={<NewIssuePage />} />
                <Route path="issues/:id" element={<TicketPage />} />
                <Route path="notifications" element={<NotificationsPage />} />
                <Route path="queue" element={<RequireRole roles={STAFF}><QueuePage mode="mine" /></RequireRole>} />
                <Route path="team" element={<RequireRole roles={STAFF}><QueuePage mode="team" /></RequireRole>} />
                <Route path="overdue" element={<RequireRole roles={STAFF}><QueuePage mode="overdue" /></RequireRole>} />
                <Route path="admin/*" element={<RequireRole roles={['admin']}><AdminRoutes /></RequireRole>} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </RequireAuth>
          </GrievanceLayout>
        </ToastProvider>
      </AuthProvider>
    </ApiProvider>
  )
}

/** Self-contained version with its own router, for apps that do not use react-router yet. */
export default function GrievanceApp({ api }) {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/grievance/*" element={<GrievanceRoutes api={api} />} />
        <Route path="*" element={<Navigate replace to={href()} />} />
      </Routes>
    </BrowserRouter>
  )
}
