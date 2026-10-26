import { Navigate } from 'react-router'

import { useAuth } from '../AuthContext.jsx'

// 로그인한 사용자만 볼 수 있는 화면을 감쌉니다. 서버도 같은 검사를 따로 합니다.
export function RequireAuth({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <p className="page-message">로그인 상태를 확인하는 중입니다.</p>
  if (!user) return <Navigate to="/login" replace />
  return children
}

// 로그인 전용 화면(로그인·회원가입)입니다. 이미 로그인했다면 홈으로 보냅니다.
export function GuestOnly({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <p className="page-message">로그인 상태를 확인하는 중입니다.</p>
  if (user) return <Navigate to="/" replace />
  return children
}
