import { useEffect, useState } from 'react'

import { checkHealth } from './api/health.js'

const STATUS_MESSAGES = {
  checking: '서버 연결을 확인하는 중입니다.',
  connected: '서버 연결됨',
  failed: '서버에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.',
}

export default function App() {
  const [status, setStatus] = useState('checking')

  useEffect(() => {
    let ignore = false

    checkHealth()
      .then((ok) => {
        if (!ignore) setStatus(ok ? 'connected' : 'failed')
      })
      .catch(() => {
        if (!ignore) setStatus('failed')
      })

    return () => {
      ignore = true
    }
  }, [])

  return (
    <main className="page">
      <h1 className="page-title">BuildLog</h1>
      <p className="page-subtitle">학습한 내용과 해결한 오류를 기록하는 서비스입니다.</p>
      <p className={`status status-${status}`} role="status">
        {STATUS_MESSAGES[status]}
      </p>
    </main>
  )
}
