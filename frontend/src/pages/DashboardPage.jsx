import { Fragment, useState } from 'react'
import { Link } from 'react-router'

import { useAuth } from '../AuthContext.jsx'
import '../styles/dashboard.css'

// Figma 시안의 예시 데이터입니다. (실제 데이터 연결은 이후 단계에서 합니다.)
const SAMPLE = {
  dateLabel: '2026. 10. 20  화요일',
  studyCount: 24,
  errorCount: 2,
  totalTasks: 12,
  doneTasks: 8, // 아래 남은 할 일 4개를 제외하고 이미 끝낸 개수
}

const SAMPLE_STUDIES = [
  { title: 'React 컴포넌트, 이제 조금 알 것 같아요', date: '오늘', summary: '화면을 작은 조각으로 나누고 다시 조합하는 방법을 배웠어요.' },
  { title: 'FastAPI로 첫 API 만들기', date: '어제', summary: 'GET과 POST의 차이를 직접 요청하며 확인했어요.' },
  { title: 'Supabase 연결 성공!', date: '10월 18일', summary: '내가 쓴 기록이 새로고침 후에도 그대로 남아 있어요.' },
]

const SAMPLE_TASKS = [
  'Figma 대시보드 디자인 살펴보기',
  'MCP로 디자인 정보 읽어오기',
  'React 화면으로 구현하기',
  '실제 데이터 연결해보기',
]

// 아직 화면이 없는 메뉴는 이동하지 않고 모양만 보여 줍니다.
const MENU = [
  { icon: '▦', label: '대시보드', to: '/dashboard', active: true },
  { icon: '▤', label: '공부 기록' },
  { icon: '✓', label: '할 일' },
  { icon: '!', label: '오류 기록' },
  { icon: '▣', label: '학습 자료함', to: '/materials' },
  { icon: '↗', label: '공개 기록' },
]

export default function DashboardPage() {
  // 로그인한 사용자의 닉네임입니다. (/dashboard는 RequireAuth 안에 있어 user가 항상 있습니다.)
  const { user } = useAuth()
  const nickname = user.nickname
  const [checked, setChecked] = useState(() => SAMPLE_TASKS.map(() => false))

  // 체크 상태는 이 화면 안에서만 유지됩니다. 새로고침하면 예시 상태로 돌아갑니다.
  function toggleTask(index) {
    setChecked((prev) => prev.map((value, i) => (i === index ? !value : value)))
  }

  const remaining = checked.filter((value) => !value).length
  const done = SAMPLE.doneTasks + (SAMPLE_TASKS.length - remaining)
  const percent = Math.round((done / SAMPLE.totalTasks) * 100)

  const summaryCards = [
    { label: '공부 기록', value: SAMPLE.studyCount, hint: '쌓아온 배움의 순간' },
    { label: '남은 할 일', value: remaining, hint: '하나씩 완료해보세요' },
    { label: '미해결 오류', value: SAMPLE.errorCount, hint: '해결 과정도 소중한 기록이에요' },
  ]

  return (
    <div className="bl-dashboard">
      <aside className="bl-sidebar">
        <Link to="/" className="bl-brand" aria-label="BuildLog 홈">
          <span className="bl-brand-mark">b</span>
          <span className="bl-brand-name">BuildLog</span>
        </Link>
        <p className="bl-workspace-label">MY WORKSPACE</p>

        <nav aria-label="대시보드 메뉴">
          {MENU.map((item) => {
            const content = (
              <>
                <span className="bl-menu-icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </>
            )
            return item.to ? (
              <Link
                key={item.label}
                to={item.to}
                className={`bl-menu-item${item.active ? ' bl-menu-item-active' : ''}`}
                aria-current={item.active ? 'page' : undefined}
              >
                {content}
              </Link>
            ) : (
              <span key={item.label} className="bl-menu-item" aria-disabled="true" title="준비 중입니다">
                {content}
              </span>
            )
          })}
        </nav>

        <div className="bl-sidebar-space" />
        <div className="bl-divider" />
        <div className="bl-account">
          <span className="bl-avatar" aria-hidden="true">
            {nickname.slice(0, 1)}
          </span>
          <div>
            <p className="bl-account-name">{nickname}</p>
            <Link to="/account" className="bl-account-link">
              {'계정 설정  ›'}
            </Link>
          </div>
        </div>
      </aside>

      <main className="bl-main">
        <div className="bl-topbar">
          <p>내 학습 한눈에 보기</p>
          <p className="bl-date">{SAMPLE.dateLabel}</p>
        </div>

        <section className="bl-greeting">
          <div>
            <h1 className="bl-greeting-title">{nickname}님, 차곡차곡 쌓이고 있어요</h1>
            <p className="bl-greeting-sub">오늘의 배움도 기록으로 남겨보세요.</p>
          </div>
          <button type="button" className="bl-new-button" aria-disabled="true" title="준비 중입니다">
            {'+  공부 기록 쓰기'}
          </button>
        </section>

        <section className="bl-summary" aria-label="요약">
          {summaryCards.map((card) => (
            <div key={card.label} className="bl-summary-card">
              <p className="bl-summary-label">{card.label}</p>
              <p className="bl-summary-value">{card.value}</p>
              <p className="bl-summary-hint">{card.hint}</p>
            </div>
          ))}
        </section>

        <div className="bl-content">
          <section className="bl-panel bl-recent" aria-labelledby="bl-recent-title">
            <div className="bl-section-header">
              <h2 id="bl-recent-title" className="bl-section-title">
                최근 공부 기록
              </h2>
              <span className="bl-section-more" aria-disabled="true">
                {'전체 보기  ›'}
              </span>
            </div>
            {SAMPLE_STUDIES.map((study, index) => (
              <Fragment key={study.title}>
                {index > 0 && <div className="bl-divider" />}
                <article className="bl-study">
                  <div className="bl-study-row">
                    <h3 className="bl-study-title">
                      {study.title}
                    </h3>
                    <span className="bl-study-date">{study.date}</span>
                  </div>
                  <p className="bl-study-summary">{study.summary}</p>
                </article>
              </Fragment>
            ))}
          </section>

          <section className="bl-panel" aria-labelledby="bl-tasks-title">
            <div className="bl-tasks-header">
              <h2 id="bl-tasks-title" className="bl-section-title">
                남은 할 일
              </h2>
              <span className="bl-count-badge">{remaining}개</span>
            </div>
            <p className="bl-tasks-sub">작은 완료가 모여 큰 성장이 돼요.</p>
            <ul className="bl-task-list">
              {SAMPLE_TASKS.map((task, index) => (
                <li key={task}>
                  <label className="bl-task">
                    <input
                      type="checkbox"
                      className="bl-task-check"
                      checked={checked[index]}
                      onChange={() => toggleTask(index)}
                    />
                    <span className="bl-task-text">{task}</span>
                  </label>
                </li>
              ))}
            </ul>
            <div className="bl-task-footer" aria-disabled="true">
              {'할 일 관리하기  →'}
            </div>
          </section>
        </div>

        <section className="bl-completion" aria-label="할 일 완료율">
          <div className="bl-completion-copy">
            <p className="bl-completion-title">잘하고 있어요. 벌써 {done}개 완료!</p>
            <p className="bl-completion-sub">
              전체 할 일 {SAMPLE.totalTasks}개 중 {done}개를 마쳤어요.
            </p>
          </div>
          <div className="bl-progress">
            <div className="bl-progress-labels">
              <span>할 일 완료율</span>
              <span className="bl-progress-percent">{percent}%</span>
            </div>
            <div
              className="bl-progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
              aria-label="할 일 완료율"
            >
              <div className="bl-progress-bar" style={{ width: `${percent}%` }} />
            </div>
          </div>
          <p className="bl-completion-count">
            {done} / {SAMPLE.totalTasks}
          </p>
        </section>

        <footer className="bl-footer">
          <span>매일의 작은 기록, 내일의 큰 변화.</span>
          <span>수업용 예시 데이터</span>
        </footer>
      </main>
    </div>
  )
}
