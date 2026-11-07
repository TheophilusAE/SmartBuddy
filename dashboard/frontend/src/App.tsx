import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { LiveProvider } from './live'
import Layout from './components/Layout'
import { Spinner } from './components/ui'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Control from './pages/Control'
import HistoryPage from './pages/History'
import Comfort from './pages/Comfort'
import Evaluation from './pages/Evaluation'

function Gate() {
  const { user, checking } = useAuth()
  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Checking session" />
      </div>
    )
  }
  if (!user) return <Login />
  return (
    <LiveProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="control" element={<Control />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="comfort" element={<Comfort />} />
          <Route path="evaluation" element={<Evaluation />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </LiveProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </BrowserRouter>
  )
}
