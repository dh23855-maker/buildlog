import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import { signup } from '../api/auth.js'
import FormField from '../components/FormField.jsx'
import {
  EMAIL_HINT,
  NICKNAME_HINT,
  PASSWORD_HINT,
  validateEmail,
  validateNickname,
  validatePassword,
} from '../validation.js'

const FIELDS = ['email', 'password', 'nickname']

export default function SignupPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()

    const found = {
      email: validateEmail(email),
      password: validatePassword(password),
      nickname: validateNickname(nickname),
    }
    if (found.email || found.password || found.nickname) {
      setErrors(found)
      return
    }

    setErrors({})
    setBusy(true)
    try {
      await signup({ email, password, nickname })
      navigate('/login', { state: { signedUp: true } })
    } catch (error) {
      // 실패하면 이메일과 닉네임은 남기고 비밀번호만 지웁니다.
      setPassword('')
      setErrors({ [FIELDS.includes(error.field) ? error.field : 'form']: error.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h1>회원가입</h1>
      <form onSubmit={handleSubmit} noValidate>
        <FormField
          label="이메일"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          hint={EMAIL_HINT}
          error={errors.email}
        />
        <FormField
          label="비밀번호"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={PASSWORD_HINT}
          error={errors.password}
        />
        <FormField
          label="닉네임"
          type="text"
          autoComplete="nickname"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          hint={NICKNAME_HINT}
          error={errors.nickname}
        />
        {errors.form && (
          <p className="form-error" role="alert">
            {errors.form}
          </p>
        )}
        <button type="submit" className="button" disabled={busy}>
          회원가입
        </button>
      </form>
      <p className="card-footer">
        이미 계정이 있나요? <Link to="/login">로그인</Link>
      </p>
    </section>
  )
}
