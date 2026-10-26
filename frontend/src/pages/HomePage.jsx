import { useAuth } from '../AuthContext.jsx'

export default function HomePage() {
  const { user } = useAuth()

  return (
    <section>
      <h1 className="page-title">내 기록</h1>
      <p className="page-subtitle">{user.nickname}님, 환영합니다.</p>
      <p className="status">공부 기록, 할 일, 오류 기록은 다음 단계에서 추가됩니다.</p>
    </section>
  )
}
