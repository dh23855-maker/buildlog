import { useState } from 'react'

import { changeNickname } from '../api/auth.js'
import { useAuth } from '../AuthContext.jsx'
import FormField from '../components/FormField.jsx'
import { NICKNAME_HINT, validateNickname } from '../validation.js'

export default function AccountSettingsPage() {
  const { user, setUser } = useAuth()
  const [nickname, setNickname] = useState(user.nickname)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setMessage('')

    const problem = validateNickname(nickname)
    if (problem) {
      setError(problem)
      return
    }

    setError('')
    setBusy(true)
    try {
      const updated = await changeNickname(nickname)
      setUser(updated)
      setNickname(updated.nickname)
      setMessage('닉네임을 변경했습니다.')
    } catch (e) {
      // 실패하면 입력한 새 닉네임은 그대로 둡니다.
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h1>계정 설정</h1>
      <dl className="info-list">
        <dt>이메일</dt>
        <dd>{user.email}</dd>
        <dt>현재 닉네임</dt>
        <dd data-testid="current-nickname">{user.nickname}</dd>
      </dl>
      <form onSubmit={handleSubmit} noValidate>
        <FormField
          label="새 닉네임"
          type="text"
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          hint={NICKNAME_HINT}
          error={error}
        />
        {message && (
          <p className="form-success" role="status">
            {message}
          </p>
        )}
        <button type="submit" className="button" disabled={busy}>
          변경
        </button>
      </form>
    </section>
  )
}
