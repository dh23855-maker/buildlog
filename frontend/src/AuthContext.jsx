import { createContext, useContext, useEffect, useState } from 'react'

import { fetchMe } from './api/auth.js'

const AuthContext = createContext(null)

// 로그인한 사용자 정보를 앱 전체에 알려줍니다. user가 null이면 로그인하지 않은 상태입니다.
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let ignore = false

    fetchMe()
      .then((me) => {
        if (!ignore) setUser(me)
      })
      .catch(() => {
        // 서버에 닿지 못하면 로그인 상태를 알 수 없으므로 로그인하지 않은 것으로 봅니다.
      })
      .finally(() => {
        if (!ignore) setLoading(false)
      })

    return () => {
      ignore = true
    }
  }, [])

  return <AuthContext.Provider value={{ user, setUser, loading }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth는 AuthProvider 안에서만 쓸 수 있습니다.')
  }
  return value
}
