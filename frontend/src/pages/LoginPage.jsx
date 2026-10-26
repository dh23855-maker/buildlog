import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { login } from '../api/auth.js'
import { useAuth } from '../AuthContext.jsx'
import FormField from '../components/FormField.jsx'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { setUser } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    if (!email.trim() || !password) {
      setError('이메일과 비밀번호를 입력해 주세요.')
      return
    }

    setError('')
    setBusy(true)
    try {
      const user = await login({ email, password })
      setUser(user)
      navigate('/', { replace: true })
    } catch (e) {
      // 실패하면 이메일은 남기고 비밀번호만 지웁니다.
      setPassword('')
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h1>로그인</h1>
      {location.state?.signedUp && (
        <p className="form-success" role="status">
          회원가입이 완료되었습니다. 로그인해 주세요.
        </p>
      )}
      <form onSubmit={handleSubmit} noValidate>
        <FormField
          label="이메일"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <FormField
          label="비밀번호"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="button" disabled={busy}>
          로그인
        </button>
      </form>
      <p className="card-footer">
        아직 계정이 없나요? <Link to="/signup">회원가입</Link>
      </p>
    </section>
  )
}
