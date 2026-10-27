import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'

import { ApiError } from '../api/auth.js'
import { analyzeMaterial, createMaterial, deleteMaterial, fileUrl, listMaterials } from '../api/materials.js'
import { useAuth } from '../AuthContext.jsx'
import {
  ACCEPT,
  KIND_LABELS,
  MEMO_MAX_LENGTH,
  TITLE_MAX_LENGTH,
  checkMaterialFile,
  formatDate,
  formatLabel,
  formatSize,
} from '../materialFile.js'
import '../styles/materials.css'

const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'image', label: '이미지' },
  { key: 'video', label: '영상' },
]

const EMPTY_COUNTS = { all: 0, image: 0, video: 0 }

// AI 요약이 진행 중인 자료가 있는 동안 3초마다 목록을 다시 불러오고, 5분이 지나면 멈춥니다.
const POLL_INTERVAL_MS = 3000
const POLL_MAX_MS = 5 * 60 * 1000
const LONG_SUMMARY_CHARS = 160

const PRIVACY_NOTICE =
  '요약을 위해 이미지(영상은 장면 일부)가 OpenAI로 전송돼요. OpenAI는 API로 받은 데이터를 학습에 사용하지 않지만, 오남용 점검을 위해 최대 30일 보관할 수 있어요. 요약은 나만 볼 수 있어요.'

// 아직 화면이 없는 메뉴는 이동하지 않고 모양만 보여 줍니다.
const MENU = [
  { label: '대시보드', to: '/dashboard' },
  { label: '공부 기록' },
  { label: '할 일' },
  { label: '오류 기록' },
  { label: '학습 자료함', to: '/materials', active: true },
  { label: '공개 기록' },
]

// 이미지는 원본을 작게 보여주고(불러오지 못하면 글자 표시), 영상은 ▶ 표시를 보여줍니다.
function Thumb({ material }) {
  const [failed, setFailed] = useState(false)
  const format = formatLabel(material.content_type)

  if (material.kind === 'image' && !failed) {
    return (
      <div className="bm-thumb bm-thumb-image">
        <img src={fileUrl(material.id)} alt={`${material.title} 미리보기`} loading="lazy" onError={() => setFailed(true)} />
      </div>
    )
  }
  const dark = material.kind === 'video'
  return (
    <div className={`bm-thumb ${dark ? 'bm-thumb-dark' : 'bm-thumb-pale'}`} aria-hidden="true">
      <span className="bm-thumb-main">{dark ? '▶' : format}</span>
      <span className="bm-thumb-sub">{dark ? format : KIND_LABELS.image}</span>
    </div>
  )
}

// 자료 카드 안의 AI 요약 영역입니다. 상태: pending(요약 중) · done(요약) · failed(이유와 다시 분석) · skipped(요약 없음)
function AiBlock({ material, aiEnabled, expanded, onToggle, onAnalyze, busy }) {
  const status = material.analysis_status ?? 'skipped'
  if (status === 'pending') {
    return (
      <p className="bm-ai-status" role="status">
        AI가 요약하는 중…
      </p>
    )
  }
  if (status === 'done' && material.summary) {
    const long = material.summary.length > LONG_SUMMARY_CHARS || material.summary.split('\n').length > 4
    return (
      <div className="bm-summary-box">
        {/* 요약은 글자로만 표시합니다. (HTML로 해석하지 않음) */}
        <p className={`bm-summary${expanded ? ' bm-summary-open' : ''}`}>{material.summary}</p>
        {long && (
          <button type="button" className="bm-text-button bm-summary-toggle" aria-expanded={expanded} onClick={onToggle}>
            {expanded ? '접기' : '더 보기'}
          </button>
        )}
      </div>
    )
  }
  if (status === 'failed') {
    return (
      <div className="bm-ai-failed">
        <p>{material.analysis_message || '요약하지 못했어요.'}</p>
        {aiEnabled && (
          <button type="button" className="bm-text-button" onClick={onAnalyze} disabled={busy} aria-label={`${material.title} 다시 분석`}>
            다시 분석
          </button>
        )}
      </div>
    )
  }
  if (status === 'skipped' && aiEnabled) {
    return (
      <div className="bm-ai-none">
        <span>AI 요약 없음</span>
        <button type="button" className="bm-text-button" onClick={onAnalyze} disabled={busy} aria-label={`${material.title} AI 요약 만들기`}>
          AI 요약 만들기
        </button>
      </div>
    )
  }
  return null
}

function addToCounts(counts, kind, delta) {
  return { ...counts, all: counts.all + delta, [kind]: counts[kind] + delta }
}

export default function MaterialsPage() {
  const { user, setUser } = useAuth()

  // 등록 폼
  const [title, setTitle] = useState('')
  const [memo, setMemo] = useState('')
  const [selected, setSelected] = useState(null) // { file, name, label, size }
  const [errors, setErrors] = useState({}) // title, memo, file, form
  const [notice, setNotice] = useState('')
  const [uploading, setUploading] = useState(false)
  const [aiSummary, setAiSummary] = useState(true) // "AI 요약하기" 체크박스 (기본 켜짐)
  const uploadingRef = useRef(false) // 상태가 바뀌기 전에 연달아 눌러도 한 번만 보내기 위함
  const fileInput = useRef(null)

  // 내 자료 목록
  const [materials, setMaterials] = useState([])
  const [counts, setCounts] = useState(EMPTY_COUNTS)
  const [loadState, setLoadState] = useState('loading') // loading | ready | error
  const [loadError, setLoadError] = useState('')
  const [filter, setFilter] = useState('all')
  const [listMessage, setListMessage] = useState('')
  const [deletingId, setDeletingId] = useState(null)
  // 서버에 OpenAI 키가 있는지. null은 아직 모르는 상태입니다.
  const [aiEnabled, setAiEnabled] = useState(null)
  const [analyzingId, setAnalyzingId] = useState(null)
  const [expanded, setExpanded] = useState({}) // 요약을 펼친 자료 번호
  const [pollTick, setPollTick] = useState(0)
  const [pollExpired, setPollExpired] = useState(false)
  const pollStartedAt = useRef(null)

  // 로그인이 끝났다면(401) 로그인 상태를 비웁니다. 그러면 로그인 화면으로 이동합니다.
  const handledAsLoggedOut = useCallback(
    (error) => {
      if (error instanceof ApiError && error.status === 401) {
        setUser(null)
        return true
      }
      return false
    },
    [setUser],
  )

  const load = useCallback(
    async ({ silent = false, quiet = false } = {}) => {
      if (!silent) setLoadState('loading')
      try {
        const data = await listMaterials()
        setMaterials(data.items)
        setCounts(data.counts)
        setAiEnabled(data.ai_enabled === true)
        setLoadError('')
        setLoadState('ready')
      } catch (error) {
        if (handledAsLoggedOut(error)) return
        if (quiet) return // 자동 새로고침이 실패해도 화면을 오류로 바꾸지 않고 다음 주기에 다시 시도합니다.
        setLoadError(error.message)
        setLoadState('error')
      }
    },
    [handledAsLoggedOut],
  )

  useEffect(() => {
    load()
  }, [load])

  // 진행 중인 요약이 있는 동안만 주기적으로 새로고침합니다.
  const hasPending = materials.some((m) => m.analysis_status === 'pending')
  const restartPolling = useCallback(() => {
    pollStartedAt.current = null
    setPollExpired(false)
    setPollTick((n) => n + 1)
  }, [])

  useEffect(() => {
    if (!hasPending) {
      pollStartedAt.current = null
      setPollExpired(false)
      return undefined
    }
    if (pollStartedAt.current === null) pollStartedAt.current = Date.now()
    if (Date.now() - pollStartedAt.current >= POLL_MAX_MS) {
      setPollExpired(true)
      return undefined
    }
    const timer = setTimeout(async () => {
      if (!document.hidden) await load({ silent: true, quiet: true }) // 탭이 숨겨져 있으면 요청하지 않음
      setPollTick((n) => n + 1)
    }, POLL_INTERVAL_MS)
    return () => clearTimeout(timer) // 화면을 떠나거나 다시 그려질 때 반드시 해제
  }, [hasPending, pollTick, load])

  function handleFileChange(event) {
    const file = event.target.files[0]
    event.target.value = '' // 같은 파일을 다시 골라도 알 수 있게 비웁니다.
    if (!file) return // 파일 선택창을 취소하면 기존 선택을 그대로 둡니다.
    setNotice('')
    const result = checkMaterialFile(file)
    if (result.ok) {
      setSelected({ file, name: file.name, label: result.label, size: file.size })
      setErrors((prev) => ({ ...prev, file: '', form: '' }))
    } else {
      setSelected(null)
      setErrors((prev) => ({ ...prev, file: result.message }))
    }
  }

  function clearSelected() {
    setSelected(null)
    setErrors((prev) => ({ ...prev, file: '' }))
  }

  // 서버에 보내기 전에 화면에서 먼저 확인합니다. 최종 판단은 서버가 합니다.
  function validate() {
    const found = {}
    const trimmedTitle = title.trim()
    if (!trimmedTitle) found.title = '제목을 입력해 주세요.'
    else if (trimmedTitle.length > TITLE_MAX_LENGTH) found.title = `제목은 ${TITLE_MAX_LENGTH}자 이하로 입력해 주세요.`
    if (memo.trim().length > MEMO_MAX_LENGTH) found.memo = `메모는 ${MEMO_MAX_LENGTH.toLocaleString()}자 이하로 입력해 주세요.`
    if (!selected) found.file = errors.file || '파일을 선택해 주세요.'
    return found
  }

  async function handleUpload(event) {
    event.preventDefault()
    if (uploadingRef.current) return
    setNotice('')
    const found = validate()
    setErrors(found)
    if (Object.keys(found).length > 0) return

    uploadingRef.current = true
    setUploading(true)
    try {
      const created = await createMaterial({
        title: title.trim(),
        memo: memo.trim(),
        file: selected.file,
        aiSummary: aiEnabled === true ? aiSummary : undefined,
      })
      // 서버가 돌려준 자료를 목록 맨 위에 바로 넣고 숫자를 맞춥니다.
      setMaterials((prev) => [created, ...prev])
      setCounts((prev) => addToCounts(prev, created.kind, 1))
      setLoadState('ready')
      setTitle('')
      setMemo('')
      setSelected(null)
      setErrors({})
      setNotice('자료를 등록했습니다.')
      if (created.analysis_status === 'pending') restartPolling()
    } catch (error) {
      if (handledAsLoggedOut(error)) return
      // 실패하면 입력한 제목·메모와 고른 파일을 그대로 두고 이유만 알립니다.
      const field = error instanceof ApiError ? error.field : null
      setErrors(['title', 'memo', 'file'].includes(field) ? { [field]: error.message } : { form: error.message })
    } finally {
      uploadingRef.current = false
      setUploading(false)
    }
  }

  async function handleAnalyze(material) {
    if (analyzingId !== null) return
    setListMessage('')
    setAnalyzingId(material.id)
    try {
      const updated = await analyzeMaterial(material.id)
      setMaterials((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
      restartPolling()
    } catch (error) {
      if (handledAsLoggedOut(error)) return
      setListMessage(error.message)
      // 이미 분석 중이거나 완료되었거나 지워진 자료라면 목록이 실제와 다르다는 뜻이므로 새로 불러옵니다.
      if (error instanceof ApiError && (error.status === 409 || error.status === 404)) load({ silent: true })
    } finally {
      setAnalyzingId(null)
    }
  }

  async function handleDelete(material) {
    if (deletingId !== null) return
    if (!window.confirm(`'${material.title}' 자료를 삭제할까요? 삭제하면 되돌릴 수 없어요.`)) return
    setListMessage('')
    setNotice('')
    setDeletingId(material.id)
    try {
      await deleteMaterial(material.id)
      setMaterials((prev) => prev.filter((m) => m.id !== material.id))
      setCounts((prev) => addToCounts(prev, material.kind, -1))
    } catch (error) {
      if (handledAsLoggedOut(error)) return
      setListMessage(error.message)
      // 이미 지워진 자료라면 목록이 실제와 다르다는 뜻이므로 새로 불러옵니다.
      if (error instanceof ApiError && error.status === 404) load({ silent: true })
    } finally {
      setDeletingId(null)
    }
  }

  const visible = filter === 'all' ? materials : materials.filter((m) => m.kind === filter)
  const titleLength = title.trim().length
  const memoLength = memo.trim().length

  return (
    <div className="bl-materials">
      <aside className="bm-sidebar">
        <Link to="/" className="bm-brand" aria-label="BuildLog 홈">
          {'b  BuildLog'}
        </Link>
        <p className="bm-workspace-label">MY WORKSPACE</p>

        <nav className="bm-menu" aria-label="학습 자료함 메뉴">
          {MENU.map((item) =>
            item.to ? (
              <Link
                key={item.label}
                to={item.to}
                className={`bm-menu-item${item.active ? ' bm-menu-item-active' : ''}`}
                aria-current={item.active ? 'page' : undefined}
              >
                {item.label}
              </Link>
            ) : (
              <span key={item.label} className="bm-menu-item" aria-disabled="true" title="준비 중입니다">
                {item.label}
              </span>
            ),
          )}
        </nav>

        <div className="bm-note">
          <p className="bm-note-title">나만의 학습 공간</p>
          <p className="bm-note-text">
            올린 자료는
            <br />
            나에게만 보여요.
          </p>
        </div>

        <div className="bm-sidebar-space" />
        <Link to="/account" className="bm-account">
          {user.nickname}님{'  ·  '}내 계정
        </Link>
      </aside>

      <main className="bm-main">
        <header className="bm-heading">
          <p className="bm-eyebrow">MY LEARNING LIBRARY</p>
          <h1 className="bm-title">학습 자료함</h1>
          <p className="bm-subtitle">캡처부터 실습 영상까지, 배운 순간을 한곳에 모아보세요.</p>
        </header>

        <div className="bm-grid">
          <form className="bm-panel bm-upload" aria-labelledby="bm-upload-title" onSubmit={handleUpload} noValidate>
            <h2 id="bm-upload-title" className="bm-section-title">
              새 자료 등록
            </h2>
            <p className="bm-muted-13">기억하고 싶은 자료를 남겨보세요.</p>

            <div className="bm-field">
              <label htmlFor="bm-material-title" className="bm-label">
                자료 제목
              </label>
              <input
                id="bm-material-title"
                className="bm-input"
                type="text"
                placeholder="예: REST API 수업 정리"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                aria-describedby="bm-title-count"
                aria-invalid={titleLength > TITLE_MAX_LENGTH || Boolean(errors.title)}
                disabled={uploading}
              />
              <p id="bm-title-count" className={`bm-count-hint${titleLength > TITLE_MAX_LENGTH ? ' bm-count-over' : ''}`}>
                {titleLength > TITLE_MAX_LENGTH
                  ? `제목은 ${TITLE_MAX_LENGTH}자까지 쓸 수 있어요. (${titleLength}자)`
                  : `${titleLength} / ${TITLE_MAX_LENGTH}자`}
              </p>
              {errors.title && (
                <p className="bm-field-error" role="alert">
                  {errors.title}
                </p>
              )}
            </div>

            <div className="bm-field">
              <label htmlFor="bm-material-memo" className="bm-label">
                {'메모  ·  선택'}
              </label>
              <textarea
                id="bm-material-memo"
                className="bm-input bm-textarea"
                placeholder="어떤 내용인지 간단히 적어주세요."
                value={memo}
                onChange={(e) => setMemo(e.target.value)}
                aria-describedby="bm-memo-count"
                aria-invalid={memoLength > MEMO_MAX_LENGTH || Boolean(errors.memo)}
                disabled={uploading}
              />
              <p id="bm-memo-count" className={`bm-count-hint${memoLength > MEMO_MAX_LENGTH ? ' bm-count-over' : ''}`}>
                {memoLength > MEMO_MAX_LENGTH
                  ? `메모는 ${MEMO_MAX_LENGTH.toLocaleString()}자까지 쓸 수 있어요. (${memoLength.toLocaleString()}자)`
                  : `${memoLength.toLocaleString()} / ${MEMO_MAX_LENGTH.toLocaleString()}자`}
              </p>
              {errors.memo && (
                <p className="bm-field-error" role="alert">
                  {errors.memo}
                </p>
              )}
            </div>

            <div className="bm-file-area">
              <span className="bm-file-arrow" aria-hidden="true">
                ↑
              </span>
              {selected ? (
                <>
                  <p className="bm-file-title bm-file-name" title={selected.name}>
                    {selected.name}
                  </p>
                  <p className="bm-file-hint">
                    {selected.label} · {formatSize(selected.size)}
                  </p>
                </>
              ) : (
                <>
                  <p className="bm-file-title">이미지 또는 영상을 선택하세요</p>
                  <p className="bm-file-hint">{'PNG · JPG  5MB / MP4  30MB'}</p>
                </>
              )}
              <input
                ref={fileInput}
                type="file"
                className="bm-file-input"
                accept={ACCEPT}
                aria-label="자료 파일"
                tabIndex={-1}
                onChange={handleFileChange}
              />
              <div className="bm-file-actions">
                <button
                  type="button"
                  className="bm-button bm-button-small"
                  onClick={() => fileInput.current.click()}
                  disabled={uploading}
                >
                  {selected ? '다른 파일 선택' : '파일 선택'}
                </button>
                {selected && (
                  <button type="button" className="bm-text-button bm-clear" onClick={clearSelected} disabled={uploading}>
                    선택 취소
                  </button>
                )}
              </div>
            </div>
            {errors.file && (
              <p className="bm-file-error" role="alert">
                {errors.file}
              </p>
            )}

            {aiEnabled === true && (
              <div className="bm-ai-option">
                <label className="bm-check">
                  <input type="checkbox" checked={aiSummary} onChange={(e) => setAiSummary(e.target.checked)} disabled={uploading} />
                  <span>AI 요약하기</span>
                </label>
                <p className="bm-muted-11">{PRIVACY_NOTICE}</p>
              </div>
            )}
            {aiEnabled === false && (
              <p className="bm-muted-11">AI 요약은 서버에 OpenAI 키를 설정하면 사용할 수 있어요.</p>
            )}

            <p className="bm-muted-11">자료당 파일 1개 · 나만 볼 수 있어요</p>
            <button type="submit" className="bm-button bm-button-wide" disabled={uploading} aria-busy={uploading}>
              {uploading ? '업로드 중…' : '자료 업로드'}
            </button>
            {errors.form && (
              <p className="bm-file-error" role="alert">
                {errors.form}
              </p>
            )}
            {notice && (
              <p className="bm-notice" role="status">
                {notice}
              </p>
            )}
            <p className="bm-muted-11">파일 선택 후 ‘자료 업로드’를 눌러 저장하세요.</p>
          </form>

          <section className="bm-library" aria-labelledby="bm-library-title">
            <div className="bm-library-header">
              <h2 id="bm-library-title" className="bm-section-title">
                내 자료
              </h2>
              <span className="bm-count" aria-label={`자료 ${counts.all}개`}>
                {counts.all}
              </span>
            </div>

            <div className="bm-filters" role="group" aria-label="자료 종류 필터">
              {FILTERS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`bm-filter${filter === item.key ? ' bm-filter-active' : ''}`}
                  aria-pressed={filter === item.key}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label} {counts[item.key]}
                </button>
              ))}
            </div>

            {listMessage && (
              <p className="bm-list-error" role="alert">
                {listMessage}
              </p>
            )}

            {pollExpired && (
              <p className="bm-muted-11" role="status">
                요약이 오래 걸리고 있어요. 잠시 뒤 새로고침해 주세요.
              </p>
            )}

            {loadState === 'loading' && <p className="bm-list-state">자료를 불러오는 중이에요.</p>}

            {loadState === 'error' && (
              <div className="bm-list-state bm-list-state-error" role="alert">
                <p>{loadError}</p>
                <button type="button" className="bm-button bm-button-small" onClick={() => load()}>
                  다시 시도
                </button>
              </div>
            )}

            {loadState === 'ready' && visible.length === 0 && (
              <p className="bm-list-state">
                {counts.all === 0 ? '아직 등록한 자료가 없어요. 첫 자료를 올려보세요.' : `${KIND_LABELS[filter]} 자료가 없어요.`}
              </p>
            )}

            {loadState === 'ready' && visible.length > 0 && (
              <ul className="bm-list">
                {visible.map((material) => (
                  <li key={material.id} className="bm-card">
                    <Thumb material={material} />
                    <div className="bm-info">
                      <h3 className="bm-card-title">{material.title}</h3>
                      <p className="bm-card-meta">
                        {KIND_LABELS[material.kind]} · {formatLabel(material.content_type)} · {formatSize(material.size_bytes)}
                      </p>
                      {material.memo && <p className="bm-card-memo">{material.memo}</p>}
                      <div aria-live="polite">
                        <AiBlock
                          material={material}
                          aiEnabled={aiEnabled === true}
                          expanded={Boolean(expanded[material.id])}
                          onToggle={() => setExpanded((prev) => ({ ...prev, [material.id]: !prev[material.id] }))}
                          onAnalyze={() => handleAnalyze(material)}
                          busy={analyzingId !== null}
                        />
                      </div>
                      <p className="bm-card-actions">
                        <span>{formatDate(material.created_at)}</span>
                        <span aria-hidden="true">·</span>
                        <a
                          className="bm-text-button"
                          href={fileUrl(material.id)}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`${material.title} 원본 보기`}
                        >
                          원본 보기
                        </a>
                        <span aria-hidden="true">·</span>
                        <button
                          type="button"
                          className="bm-text-button"
                          onClick={() => handleDelete(material)}
                          disabled={deletingId !== null}
                          aria-label={`${material.title} 삭제`}
                        >
                          {deletingId === material.id ? '삭제 중…' : '삭제'}
                        </button>
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <p className="bm-help">차곡차곡 쌓인 자료가 나만의 복습 노트가 됩니다.</p>
          </section>
        </div>

        <section className="bm-ai" aria-labelledby="bm-ai-title">
          <div className="bm-ai-copy">
            <h2 id="bm-ai-title" className="bm-ai-title">
              {aiEnabled === true && 'AI 학습 도우미   ·   사용 중'}
              {aiEnabled === false && 'AI 학습 도우미   ·   설정 필요'}
              {aiEnabled === null && 'AI 학습 도우미'}
            </h2>
            <p className="bm-ai-text">
              {aiEnabled === true && '올린 이미지와 영상을 자동으로 요약해요.'}
              {aiEnabled === false && '서버에 OpenAI 키를 설정하면 이미지와 영상을 자동으로 요약해요.'}
              {aiEnabled === null && '상태를 확인하는 중이에요.'}
            </p>
            {aiEnabled === false && (
              <p className="bm-muted-11">키를 설정하기 전에도 자료 등록, 원본 보기, 삭제는 그대로 쓸 수 있어요.</p>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}
