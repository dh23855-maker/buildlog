import { useState } from 'react'
import { Link, Outlet, useNavigate } from 'react-router'

import { logout } from '../api/auth.js'
import { useAuth } from '../AuthContext.jsx'

export default function Layout() {
  const { user, setUser } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleLogout() {
    setError('')
    setBusy(true)
    try {
      await logout()
      setUser(null)
      navigate('/login', { replace: true })
    } catch (e) {
      setError(`로그아웃하지 못했습니다. ${e.message} 다시 시도해 주세요.`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <header className="site-header">
        <Link to="/" className="site-logo">
          BuildLog
        </Link>
        <nav className="site-nav" aria-label="주 메뉴">
          {user ? (
            <>
              <span className="site-user">{user.nickname}</span>
              <Link to="/account">계정 설정</Link>
              <button type="button" className="link-button" onClick={handleLogout} disabled={busy}>
                로그아웃
              </button>
            </>
          ) : (
            <>
              <Link to="/login">로그인</Link>
              <Link to="/signup">회원가입</Link>
            </>
          )}
        </nav>
      </header>
      {error && (
        <p className="form-error site-error" role="alert">
          {error}
        </p>
      )}
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
