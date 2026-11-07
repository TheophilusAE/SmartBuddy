import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setCsrfToken, setUnauthorizedHandler } from './api'
import type { Role } from './types'

interface User {
  username: string
  role: Role
}

interface AuthState {
  user: User | null
  checking: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

interface SessionResponse {
  user: User
  csrf_token: string
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setCsrfToken(null)
      setUser(null)
    })
    api<SessionResponse>('/auth/me')
      .then((s) => {
        setCsrfToken(s.csrf_token)
        setUser(s.user)
      })
      .catch(() => setUser(null))
      .finally(() => setChecking(false))
    return () => setUnauthorizedHandler(null)
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const s = await api<SessionResponse>('/auth/login', { method: 'POST', body: { username, password } })
    setCsrfToken(s.csrf_token)
    setUser(s.user)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api('/auth/logout', { method: 'POST' })
    } finally {
      setCsrfToken(null)
      setUser(null)
    }
  }, [])

  const value = useMemo(() => ({ user, checking, login, logout }), [user, checking, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}
