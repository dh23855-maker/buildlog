import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App.jsx'

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

const NOT_LOGGED_IN = () => jsonResponse({ detail: '로그인이 필요합니다.', field: null }, 401)
const ME = { id: 1, email: 'user@example.com', nickname: '빌드로그' }

// 주소와 방식별로 응답을 정해 두는 가짜 서버입니다. 정해지지 않은 요청은 로그인 필요(401)로 답합니다.
function mockServer(routes = {}) {
  const calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
    const method = options.method ?? 'GET'
    // 파일 업로드(FormData)는 그대로 넘기고, 나머지는 JSON으로 읽습니다.
    const body = options.body instanceof FormData ? options.body : options.body ? JSON.parse(options.body) : undefined
    calls.push({ method, url, body })
    const handler = routes[`${method} ${url}`]
    return handler ? handler(body) : NOT_LOGGED_IN()
  })
  return calls
}

function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('로그인하지 않은 사용자', () => {
  it('홈 주소로 들어가면 로그인 화면으로 이동한다', async () => {
    mockServer({ 'GET /api/auth/me': NOT_LOGGED_IN })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })

  it('계정 설정 주소로 직접 들어가도 로그인 화면으로 이동한다', async () => {
    mockServer({ 'GET /api/auth/me': NOT_LOGGED_IN })
    renderApp('/account')
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })
})

describe('회원가입', () => {
  it('성공하면 가입 안내와 함께 로그인 화면으로 이동한다', async () => {
    const calls = mockServer({
      'GET /api/auth/me': NOT_LOGGED_IN,
      'POST /api/auth/signup': () => jsonResponse(ME, 201),
    })
    const user = userEvent.setup()
    renderApp('/signup')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), 'password123')
    await user.type(screen.getByLabelText('닉네임'), '빌드로그')
    await user.click(screen.getByRole('button', { name: '회원가입' }))

    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
    expect(screen.getByText('회원가입이 완료되었습니다. 로그인해 주세요.')).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/api/auth/signup').body).toEqual({
      email: 'user@example.com',
      password: 'password123',
      nickname: '빌드로그',
    })
  })

  it('비밀번호가 7자면 서버에 보내지 않고 길이 조건을 알려준다', async () => {
    const calls = mockServer({ 'GET /api/auth/me': NOT_LOGGED_IN })
    const user = userEvent.setup()
    renderApp('/signup')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), '1234567')
    await user.type(screen.getByLabelText('닉네임'), '빌드로그')
    await user.click(screen.getByRole('button', { name: '회원가입' }))

    expect(screen.getByText('비밀번호는 8자 이상 64자 이하로 입력해 주세요.')).toBeInTheDocument()
    expect(calls.some((c) => c.url === '/api/auth/signup')).toBe(false)
  })

  it('닉네임에 허용되지 않는 문자가 있으면 안내한다', async () => {
    mockServer({ 'GET /api/auth/me': NOT_LOGGED_IN })
    const user = userEvent.setup()
    renderApp('/signup')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), 'password123')
    await user.type(screen.getByLabelText('닉네임'), '안녕 하세요!')
    await user.click(screen.getByRole('button', { name: '회원가입' }))

    expect(screen.getByText(/닉네임은 2~20자의 한글, 영문, 숫자, 밑줄/)).toBeInTheDocument()
  })

  it('서버가 거절하면 이유를 보여주고 이메일·닉네임은 남기고 비밀번호만 지운다', async () => {
    mockServer({
      'GET /api/auth/me': NOT_LOGGED_IN,
      'POST /api/auth/signup': () =>
        jsonResponse({ detail: '이미 사용 중인 이메일입니다. 다른 이메일을 입력해 주세요.', field: 'email' }, 409),
    })
    const user = userEvent.setup()
    renderApp('/signup')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), 'password123')
    await user.type(screen.getByLabelText('닉네임'), '빌드로그')
    await user.click(screen.getByRole('button', { name: '회원가입' }))

    expect(await screen.findByText('이미 사용 중인 이메일입니다. 다른 이메일을 입력해 주세요.')).toBeInTheDocument()
    expect(screen.getByLabelText('이메일')).toHaveValue('user@example.com')
    expect(screen.getByLabelText('닉네임')).toHaveValue('빌드로그')
    expect(screen.getByLabelText('비밀번호')).toHaveValue('')
  })

  it('서버에 닿지 못해도 이유를 보여주고 비밀번호만 지운다', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      if (url === '/api/auth/me') return NOT_LOGGED_IN()
      throw new TypeError('Failed to fetch')
    })
    const user = userEvent.setup()
    renderApp('/signup')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), 'password123')
    await user.type(screen.getByLabelText('닉네임'), '빌드로그')
    await user.click(screen.getByRole('button', { name: '회원가입' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 연결하지 못했습니다')
    expect(screen.getByLabelText('이메일')).toHaveValue('user@example.com')
    expect(screen.getByLabelText('비밀번호')).toHaveValue('')
  })
})

describe('로그인', () => {
  it('성공하면 내 기록 홈 화면으로 이동한다', async () => {
    mockServer({
      'GET /api/auth/me': NOT_LOGGED_IN,
      'POST /api/auth/login': () => jsonResponse(ME),
    })
    const user = userEvent.setup()
    renderApp('/login')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), 'password123')
    await user.click(screen.getByRole('button', { name: '로그인' }))

    expect(await screen.findByRole('heading', { name: '내 기록' })).toBeInTheDocument()
    expect(screen.getByText('빌드로그님, 환영합니다.')).toBeInTheDocument()
  })

  it('실패하면 맞지 않는다고 알리고 이메일은 남기고 비밀번호만 지운다', async () => {
    mockServer({
      'GET /api/auth/me': NOT_LOGGED_IN,
      'POST /api/auth/login': () =>
        jsonResponse({ detail: '이메일 또는 비밀번호가 맞지 않습니다.', field: null }, 401),
    })
    const user = userEvent.setup()
    renderApp('/login')

    await user.type(await screen.findByLabelText('이메일'), 'user@example.com')
    await user.type(screen.getByLabelText('비밀번호'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: '로그인' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('이메일 또는 비밀번호가 맞지 않습니다.')
    expect(screen.getByLabelText('이메일')).toHaveValue('user@example.com')
    expect(screen.getByLabelText('비밀번호')).toHaveValue('')
  })

  it('이미 로그인한 상태로 로그인 주소에 들어가면 홈으로 이동한다', async () => {
    mockServer({ 'GET /api/auth/me': () => jsonResponse(ME) })
    renderApp('/login')
    expect(await screen.findByRole('heading', { name: '내 기록' })).toBeInTheDocument()
  })
})

describe('로그아웃', () => {
  it('누르면 로그인 화면으로 이동하고 다시 홈에 들어갈 수 없다', async () => {
    let loggedIn = true
    const calls = mockServer({
      'GET /api/auth/me': () => (loggedIn ? jsonResponse(ME) : NOT_LOGGED_IN()),
      'POST /api/auth/logout': () => {
        loggedIn = false
        return new Response(null, { status: 204 })
      },
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/auth/logout')).toBe(true)
    expect(screen.queryByRole('heading', { name: '내 기록' })).not.toBeInTheDocument()
  })

  it('실패하면 이유를 알리고 로그인 상태를 유지해 다시 시도할 수 있다', async () => {
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'POST /api/auth/logout': () => jsonResponse({ detail: '서버 오류', field: null }, 500),
    })
    const user = userEvent.setup()
    renderApp('/')

    await user.click(await screen.findByRole('button', { name: '로그아웃' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('로그아웃하지 못했습니다')
    expect(screen.getByRole('heading', { name: '내 기록' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '로그아웃' })).toBeEnabled()
  })
})

describe('닉네임 변경', () => {
  it('성공하면 바뀐 닉네임이 보인다', async () => {
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'PATCH /api/account/nickname': (body) => jsonResponse({ ...ME, nickname: body.nickname }),
    })
    const user = userEvent.setup()
    renderApp('/account')

    const input = await screen.findByLabelText('새 닉네임')
    await user.clear(input)
    await user.type(input, '새닉네임')
    await user.click(screen.getByRole('button', { name: '변경' }))

    expect(await screen.findByText('닉네임을 변경했습니다.')).toBeInTheDocument()
    expect(screen.getByTestId('current-nickname')).toHaveTextContent('새닉네임')
  })

  it('이미 쓰는 닉네임이면 이유를 알리고 입력한 닉네임을 유지한다', async () => {
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'PATCH /api/account/nickname': () =>
        jsonResponse({ detail: '이미 사용 중인 닉네임입니다. 다른 닉네임을 입력해 주세요.', field: 'nickname' }, 409),
    })
    const user = userEvent.setup()
    renderApp('/account')

    const input = await screen.findByLabelText('새 닉네임')
    await user.clear(input)
    await user.type(input, '남의닉')
    await user.click(screen.getByRole('button', { name: '변경' }))

    expect(await screen.findByText(/이미 사용 중인 닉네임입니다/)).toBeInTheDocument()
    expect(input).toHaveValue('남의닉')
    expect(screen.getByTestId('current-nickname')).toHaveTextContent('빌드로그')
  })

  it('규칙에 맞지 않는 닉네임은 서버에 보내지 않는다', async () => {
    const calls = mockServer({ 'GET /api/auth/me': () => jsonResponse(ME) })
    const user = userEvent.setup()
    renderApp('/account')

    const input = await screen.findByLabelText('새 닉네임')
    await user.clear(input)
    await user.type(input, 'a')
    await user.click(screen.getByRole('button', { name: '변경' }))

    await waitFor(() => expect(screen.getByText(/닉네임은 2~20자/, { selector: '.field-error' })).toBeInTheDocument())
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })
})

describe('대시보드 화면', () => {
  it('로그인하지 않으면 로그인 화면으로 이동한다', async () => {
    mockServer({ 'GET /api/auth/me': NOT_LOGGED_IN })
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })

  it('예시 데이터를 보여 주고, 할 일을 체크하면 숫자가 화면 안에서 바뀐다', async () => {
    mockServer({ 'GET /api/auth/me': () => jsonResponse(ME) })
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { name: '빌드로그님, 차곡차곡 쌓이고 있어요' })).toBeInTheDocument()
    expect(screen.getByText('벌써 8개 완료!', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('67%')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('checkbox', { name: 'MCP로 디자인 정보 읽어오기' }))
    expect(screen.getByText('벌써 9개 완료!', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('3개')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
  })

  it('계정 설정 링크는 기존 계정 설정 주소로 연결된다', async () => {
    mockServer({ 'GET /api/auth/me': () => jsonResponse(ME) })
    renderApp('/dashboard')
    const link = await screen.findByRole('link', { name: /계정 설정/ })
    expect(link).toHaveAttribute('href', '/account')
  })

  it('로그인한 사용자의 닉네임으로 인사말, 아바타 글자, 계정 이름을 보여 준다', async () => {
    mockServer({ 'GET /api/auth/me': () => jsonResponse({ ...ME, nickname: 'minji_7' }) })
    renderApp('/dashboard')
    expect(await screen.findByRole('heading', { name: 'minji_7님, 차곡차곡 쌓이고 있어요' })).toBeInTheDocument()
    expect(screen.getByText('minji_7', { selector: '.bl-account-name' })).toBeInTheDocument()
    expect(document.querySelector('.bl-avatar')).toHaveTextContent('m')
    expect(screen.queryByText('이월', { exact: false })).not.toBeInTheDocument()
  })

  it('계정 설정에서 닉네임을 바꾸면 대시보드에도 바뀐 닉네임이 보인다', async () => {
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'PATCH /api/account/nickname': (body) => jsonResponse({ ...ME, nickname: body.nickname }),
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <App />
        <Link to="/dashboard">대시보드로 돌아가기</Link>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('link', { name: /계정 설정/ }))
    const input = await screen.findByLabelText('새 닉네임')
    await user.clear(input)
    await user.type(input, '새닉네임')
    await user.click(screen.getByRole('button', { name: '변경' }))
    expect(await screen.findByText('닉네임을 변경했습니다.')).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: '대시보드로 돌아가기' }))
    expect(await screen.findByRole('heading', { name: '새닉네임님, 차곡차곡 쌓이고 있어요' })).toBeInTheDocument()
  })
})

// ---------- 학습 자료함 ----------

const MB = 1024 * 1024

// 크기만 흉내 낸 가짜 파일입니다. (실제로 30MB를 만들지 않아도 됩니다.)
function fakeFile(name, type, size) {
  const file = new File(['x'], name, { type })
  Object.defineProperty(file, 'size', { value: size })
  return file
}

const IMAGE_1 = {
  id: 3,
  title: 'REST API 핵심 정리',
  memo: '수업 캡처입니다.',
  kind: 'image',
  original_filename: 'rest.png',
  content_type: 'image/png',
  size_bytes: 1.2 * MB,
  created_at: '2026-10-20T15:30:00+00:00', // 한국 시간으로는 10월 21일
}
const VIDEO_1 = {
  id: 2,
  title: '회원가입 동작 확인',
  memo: null,
  kind: 'video',
  original_filename: 'signup.mp4',
  content_type: 'video/mp4',
  size_bytes: 12.4 * MB,
  created_at: '2026-10-20T01:00:00+00:00',
}
const IMAGE_2 = {
  id: 1,
  title: '데이터베이스 관계 정리',
  memo: null,
  kind: 'image',
  original_filename: 'db.jpg',
  content_type: 'image/jpeg',
  size_bytes: 860 * 1024,
  created_at: '2026-10-19T01:00:00+00:00',
}
const THREE = {
  items: [IMAGE_1, VIDEO_1, IMAGE_2],
  counts: { all: 3, image: 2, video: 1 },
}
const NONE = { items: [], counts: { all: 0, image: 0, video: 0 } }

// 로그인한 상태의 학습 자료함용 가짜 서버입니다.
function materialsServer(list = THREE, extra = {}) {
  return mockServer({
    'GET /api/auth/me': () => jsonResponse(ME),
    'GET /api/materials': () => jsonResponse(list),
    ...extra,
  })
}

async function openMaterials(list = THREE, extra = {}) {
  const calls = materialsServer(list, extra)
  // 파일 선택창의 accept 필터를 거치지 않는 파일도 들어올 수 있으므로 필터 없이 시험합니다.
  const user = userEvent.setup({ applyAccept: false })
  renderApp('/materials')
  await screen.findByRole('heading', { name: '학습 자료함' })
  return { user, calls }
}

describe('학습 자료함 화면', () => {
  it('로그인하지 않으면 로그인 화면으로 이동한다', async () => {
    mockServer({ 'GET /api/auth/me': NOT_LOGGED_IN })
    renderApp('/materials')
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })

  it('서버의 내 자료 목록을 보여 준다', async () => {
    await openMaterials()
    expect(await screen.findByText('REST API 핵심 정리')).toBeInTheDocument()
    expect(screen.getByText('회원가입 동작 확인')).toBeInTheDocument()
    expect(screen.getByText('데이터베이스 관계 정리')).toBeInTheDocument()
    expect(screen.getByText('이미지 · PNG · 1.2MB')).toBeInTheDocument()
    expect(screen.getByText('영상 · MP4 · 12.4MB')).toBeInTheDocument()
    expect(screen.getByText('이미지 · JPG · 860KB')).toBeInTheDocument()
    expect(screen.getByText('수업 캡처입니다.')).toBeInTheDocument()
    // 등록 시각은 한국 시간 날짜로 보여 줍니다.
    expect(screen.getByText('2026.10.21')).toBeInTheDocument()
    expect(screen.getByText('2026.10.19')).toBeInTheDocument()
    // 예시 표시는 더 이상 없습니다.
    expect(screen.queryByText('디자인 확인용 예시')).not.toBeInTheDocument()
    expect(screen.queryByText(/화면 설계용 예시/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전체 3' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '이미지 2' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '영상 1' })).toBeInTheDocument()
  })

  it('원본 보기는 새 탭으로 열리는 원본 주소로 연결된다', async () => {
    await openMaterials()
    const link = await screen.findByRole('link', { name: 'REST API 핵심 정리 원본 보기' })
    expect(link).toHaveAttribute('href', '/api/materials/3/file')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(screen.getByAltText('REST API 핵심 정리 미리보기')).toHaveAttribute('src', '/api/materials/3/file')
    expect(screen.getByAltText('REST API 핵심 정리 미리보기')).toHaveAttribute('loading', 'lazy')
  })

  it('불러오는 동안 안내를 보여 주고, 자료가 없으면 빈 안내를 보여 준다', async () => {
    let finish
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => new Promise((resolve) => (finish = () => resolve(jsonResponse(NONE)))),
    })
    renderApp('/materials')
    expect(await screen.findByText('자료를 불러오는 중이에요.')).toBeInTheDocument()
    expect(screen.queryByText(/아직 등록한 자료가 없어요/)).not.toBeInTheDocument()
    finish()
    expect(await screen.findByText('아직 등록한 자료가 없어요. 첫 자료를 올려보세요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전체 0' })).toBeInTheDocument()
  })

  it('목록을 불러오지 못하면 이유를 알리고 빈 목록처럼 보이지 않으며, 다시 시도할 수 있다', async () => {
    let fail = true
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () =>
        fail ? jsonResponse({ detail: '서버에 문제가 생겼어요.', field: null }, 500) : jsonResponse(THREE),
    })
    const user = userEvent.setup()
    renderApp('/materials')

    expect(await screen.findByRole('alert')).toHaveTextContent('서버에 문제가 생겼어요.')
    expect(screen.queryByText(/아직 등록한 자료가 없어요/)).not.toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByText('REST API 핵심 정리')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('종류 필터로 걸러 내도 숫자는 전체 기준으로 유지된다', async () => {
    const { user } = await openMaterials()
    await screen.findByText('REST API 핵심 정리')

    await user.click(screen.getByRole('button', { name: '영상 1' }))
    expect(screen.getByText('회원가입 동작 확인')).toBeInTheDocument()
    expect(screen.queryByText('REST API 핵심 정리')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '이미지 2' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '이미지 2' }))
    expect(screen.queryByText('회원가입 동작 확인')).not.toBeInTheDocument()
    expect(screen.getByText('데이터베이스 관계 정리')).toBeInTheDocument()
  })

  it('해당 종류의 자료가 없으면 그 종류가 없다고 알린다', async () => {
    const { user } = await openMaterials({ items: [IMAGE_1], counts: { all: 1, image: 1, video: 0 } })
    await screen.findByText('REST API 핵심 정리')
    await user.click(screen.getByRole('button', { name: '영상 0' }))
    expect(screen.getByText('영상 자료가 없어요.')).toBeInTheDocument()
  })

  it('로그인 상태가 끝났으면 로그인 화면으로 이동한다', async () => {
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': NOT_LOGGED_IN,
    })
    renderApp('/materials')
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })

  it('AI 정보가 없는 예전 형태의 응답에서도 정상 동작하고 AI 관련 버튼은 보이지 않는다', async () => {
    await openMaterials() // 목록 응답에 ai_enabled·analysis_status가 없음
    await screen.findByText('REST API 핵심 정리')
    expect(screen.queryByRole('checkbox', { name: 'AI 요약하기' })).not.toBeInTheDocument()
    expect(screen.queryByText('AI 요약 없음')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /AI 요약 만들기|다시 분석/ })).not.toBeInTheDocument()
  })

  it('홈과 대시보드 메뉴에서 학습 자료함으로 들어갈 수 있다', async () => {
    mockServer({ 'GET /api/auth/me': () => jsonResponse(ME) })
    const { unmount } = renderApp('/')
    expect(await screen.findByRole('link', { name: /학습 자료함/ })).toHaveAttribute('href', '/materials')
    unmount()

    renderApp('/dashboard')
    expect(await screen.findByRole('link', { name: /학습 자료함/ })).toHaveAttribute('href', '/materials')
    expect(screen.getByRole('link', { name: /대시보드/ })).toHaveAttribute('href', '/dashboard')
  })
})

describe('학습 자료함 파일 선택', () => {
  async function setup() {
    const { user } = await openMaterials(NONE)
    return { user, input: screen.getByLabelText('자료 파일') }
  }

  it.each([
    ['shot.png', 'image/png', 1 * MB, 'PNG · 1.0MB'],
    ['photo.JPG', 'image/jpeg', 5 * MB, 'JPG · 5.0MB'],
    ['photo.jpeg', 'image/jpeg', 860 * 1024, 'JPG · 860KB'],
    ['demo.mp4', 'video/mp4', 30 * MB, 'MP4 · 30.0MB'],
  ])('%s 파일을 고르면 이름과 크기를 보여 준다', async (name, type, size, summary) => {
    const { user, input } = await setup()
    await user.upload(input, fakeFile(name, type, size))
    expect(screen.getByText(name)).toBeInTheDocument()
    expect(screen.getByText(summary)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다른 파일 선택' })).toBeInTheDocument()
  })

  it.each([
    ['big.png', 'image/png', 5 * MB + 1, 'PNG 파일은 5MB까지'],
    ['big.jpg', 'image/jpeg', 5 * MB + 1, 'JPG 파일은 5MB까지'],
    ['big.mp4', 'video/mp4', 30 * MB + 1, 'MP4 파일은 30MB까지'],
    ['empty.png', 'image/png', 0, '비어 있는 파일'],
    ['anim.gif', 'image/gif', 1000, 'PNG, JPG, MP4 파일만'],
    ['vector.svg', 'image/svg+xml', 1000, 'PNG, JPG, MP4 파일만'],
    ['clip.mov', 'video/quicktime', 1000, 'PNG, JPG, MP4 파일만'],
    ['noext', '', 1000, 'PNG, JPG, MP4 파일만'],
    ['fake.png', 'video/mp4', 1000, 'PNG, JPG, MP4 파일만'], // 확장자와 형식이 다름
  ])('%s 파일은 이유를 알리고 선택하지 않는다', async (name, type, size, message) => {
    const { user, input } = await setup()
    await user.upload(input, fakeFile(name, type, size))
    expect(screen.getByRole('alert')).toHaveTextContent(message)
    expect(screen.queryByText(name)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '파일 선택' })).toBeInTheDocument()
  })

  it('잘못된 파일을 고르면 이전 선택도 비운다', async () => {
    const { user, input } = await setup()
    await user.upload(input, fakeFile('ok.png', 'image/png', MB))
    expect(screen.getByText('ok.png')).toBeInTheDocument()
    await user.upload(input, fakeFile('anim.gif', 'image/gif', 1000))
    expect(screen.queryByText('ok.png')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('선택 취소를 누르면 선택이 지워지고, 올바른 파일을 다시 고르면 오류가 사라진다', async () => {
    const { user, input } = await setup()
    await user.upload(input, fakeFile('ok.png', 'image/png', MB))
    await user.click(screen.getByRole('button', { name: '선택 취소' }))
    expect(screen.queryByText('ok.png')).not.toBeInTheDocument()
    expect(screen.getByText('이미지 또는 영상을 선택하세요')).toBeInTheDocument()

    await user.upload(input, fakeFile('anim.gif', 'image/gif', 1000))
    expect(screen.getByRole('alert')).toBeInTheDocument()
    await user.upload(input, fakeFile('ok.mp4', 'video/mp4', MB))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('ok.mp4')).toBeInTheDocument()
  })

  it('제목과 메모의 글자 수를 알려 주고, 넘으면 이유를 보여 준다', async () => {
    const { user } = await setup()
    expect(screen.getByText('0 / 100자')).toBeInTheDocument()
    expect(screen.getByText('0 / 1,000자')).toBeInTheDocument()

    await user.type(screen.getByLabelText('자료 제목'), '  제목  ')
    expect(screen.getByText('2 / 100자')).toBeInTheDocument() // 앞뒤 공백은 세지 않음

    await user.clear(screen.getByLabelText('자료 제목'))
    await user.click(screen.getByLabelText('자료 제목'))
    await user.paste('가'.repeat(101))
    expect(screen.getByText('제목은 100자까지 쓸 수 있어요. (101자)')).toBeInTheDocument()
    expect(screen.getByLabelText('자료 제목')).toHaveAttribute('aria-invalid', 'true')
  })
})

describe('학습 자료함 업로드', () => {
  const CREATED = { ...IMAGE_1, id: 10, title: '새 자료', memo: '새 메모', created_at: '2026-10-27T01:00:00+00:00' }

  async function fillForm(user, { title = '새 자료', memo = '새 메모', file = fakeFile('new.png', 'image/png', MB) } = {}) {
    if (title) await user.type(screen.getByLabelText('자료 제목'), title)
    if (memo) await user.type(screen.getByLabelText(/메모/), memo)
    if (file) await user.upload(screen.getByLabelText('자료 파일'), file)
  }

  const uploadButton = () => screen.getByRole('button', { name: /자료 업로드|업로드 중/ })

  it('제목·메모·파일을 서버에 보내고, 성공하면 입력을 비우고 목록 맨 위에 보여 준다', async () => {
    const { user, calls } = await openMaterials(
      { items: [VIDEO_1], counts: { all: 1, image: 0, video: 1 } },
      { 'POST /api/materials': () => jsonResponse(CREATED, 201) },
    )
    await screen.findByText('회원가입 동작 확인')
    await fillForm(user)
    await user.click(uploadButton())

    expect(await screen.findByText('자료를 등록했습니다.')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body).toBeInstanceOf(FormData)
    expect(post.body.get('title')).toBe('새 자료')
    expect(post.body.get('memo')).toBe('새 메모')
    expect(post.body.get('file').name).toBe('new.png')

    // 입력과 선택이 비워짐
    expect(screen.getByLabelText('자료 제목')).toHaveValue('')
    expect(screen.getByLabelText(/메모/)).toHaveValue('')
    expect(screen.getByText('이미지 또는 영상을 선택하세요')).toBeInTheDocument()
    // 목록 맨 위에 새 자료, 숫자 갱신
    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(titles).toEqual(['새 자료', '회원가입 동작 확인'])
    expect(screen.getByRole('button', { name: '전체 2' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '이미지 1' })).toBeInTheDocument()
    expect(screen.queryByText(/아직 등록한 자료가 없어요/)).not.toBeInTheDocument()
  })

  it('빈 목록에서 첫 자료를 올리면 빈 안내가 사라지고 자료가 보인다', async () => {
    const { user } = await openMaterials(NONE, { 'POST /api/materials': () => jsonResponse(CREATED, 201) })
    expect(await screen.findByText(/아직 등록한 자료가 없어요/)).toBeInTheDocument()
    await fillForm(user)
    await user.click(uploadButton())
    expect(await screen.findByRole('heading', { level: 3, name: '새 자료' })).toBeInTheDocument()
    expect(screen.queryByText(/아직 등록한 자료가 없어요/)).not.toBeInTheDocument()
  })

  it('앞뒤 공백을 지운 제목을 보내고, 메모를 비워 두어도 된다', async () => {
    const { user, calls } = await openMaterials(NONE, { 'POST /api/materials': () => jsonResponse(CREATED, 201) })
    await screen.findByText(/아직 등록한 자료가 없어요/)
    await fillForm(user, { title: '  공백 제목  ', memo: '' })
    await user.click(uploadButton())
    await screen.findByText('자료를 등록했습니다.')
    const post = calls.find((c) => c.method === 'POST')
    expect(post.body.get('title')).toBe('공백 제목')
    expect(post.body.get('memo')).toBe('')
  })

  it('보내기 전에 제목·파일·글자 수를 확인하고, 문제가 있으면 요청하지 않는다', async () => {
    const { user, calls } = await openMaterials(NONE)
    await screen.findByText(/아직 등록한 자료가 없어요/)

    await user.click(uploadButton())
    expect(screen.getAllByRole('alert').map((a) => a.textContent)).toEqual(['제목을 입력해 주세요.', '파일을 선택해 주세요.'])

    await user.click(screen.getByLabelText('자료 제목'))
    await user.paste('가'.repeat(101))
    await user.click(screen.getByLabelText(/메모/))
    await user.paste('나'.repeat(1001))
    await user.upload(screen.getByLabelText('자료 파일'), fakeFile('a.png', 'image/png', MB))
    await user.click(uploadButton())
    expect(screen.getByText('제목은 100자 이하로 입력해 주세요.')).toBeInTheDocument()
    expect(screen.getByText('메모는 1,000자 이하로 입력해 주세요.')).toBeInTheDocument()

    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it.each([
    ['title', 422, '제목을 입력해 주세요.'],
    ['memo', 422, '메모는 1,000자 이하로 입력해 주세요.'],
    ['file', 413, 'PNG 파일은 5MB까지 올릴 수 있어요.'],
    ['file', 415, 'PNG, JPG, MP4 파일만 올릴 수 있어요.'],
  ])('서버가 %s 오류(%i)를 알리면 그 칸에 이유를 보여 주고 입력을 유지한다', async (field, status, detail) => {
    const { user } = await openMaterials(NONE, {
      'POST /api/materials': () => jsonResponse({ detail, field }, status),
    })
    await screen.findByText(/아직 등록한 자료가 없어요/)
    await fillForm(user)
    await user.click(uploadButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    expect(screen.queryByText('자료를 등록했습니다.')).not.toBeInTheDocument()
    expect(screen.getByLabelText('자료 제목')).toHaveValue('새 자료')
    expect(screen.getByLabelText(/메모/)).toHaveValue('새 메모')
    expect(screen.getByText('new.png')).toBeInTheDocument() // 고른 파일도 그대로
    expect(screen.queryByRole('heading', { level: 3 })).not.toBeInTheDocument() // 목록은 늘지 않음
    expect(uploadButton()).toBeEnabled() // 다시 시도할 수 있음
  })

  it('서버 오류와 연결 실패도 이유를 알리고 입력을 유지한다', async () => {
    let mode = 'server'
    const { user } = await openMaterials(NONE, {
      'POST /api/materials': () => {
        if (mode === 'network') throw new TypeError('Failed to fetch')
        return jsonResponse({ detail: '자료를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.', field: null }, 500)
      },
    })
    await screen.findByText(/아직 등록한 자료가 없어요/)
    await fillForm(user)

    await user.click(uploadButton())
    expect(await screen.findByRole('alert')).toHaveTextContent('자료를 저장하지 못했습니다.')

    mode = 'network'
    await user.click(uploadButton())
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'),
    )
    expect(screen.getByLabelText('자료 제목')).toHaveValue('새 자료')
    expect(screen.getByText('new.png')).toBeInTheDocument()
    expect(screen.queryByText('자료를 등록했습니다.')).not.toBeInTheDocument()
  })

  it('실패한 뒤 다시 시도하면 성공하고 이전 오류가 사라진다', async () => {
    let first = true
    const { user } = await openMaterials(NONE, {
      'POST /api/materials': () => {
        if (first) {
          first = false
          return jsonResponse({ detail: '자료를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.', field: null }, 500)
        }
        return jsonResponse(CREATED, 201)
      },
    })
    await screen.findByText(/아직 등록한 자료가 없어요/)
    await fillForm(user)
    await user.click(uploadButton())
    await screen.findByRole('alert')
    await user.click(uploadButton())
    expect(await screen.findByText('자료를 등록했습니다.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('업로드 중에는 버튼이 막혀 연달아 눌러도 한 번만 보낸다', async () => {
    let finish
    const { user, calls } = await openMaterials(NONE, {
      'POST /api/materials': () => new Promise((resolve) => (finish = () => resolve(jsonResponse(CREATED, 201)))),
    })
    await screen.findByText(/아직 등록한 자료가 없어요/)
    await fillForm(user)

    await user.click(uploadButton())
    expect(await screen.findByRole('button', { name: '업로드 중…' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '업로드 중…' }))
    await user.click(screen.getByRole('button', { name: '업로드 중…' }))
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)

    finish()
    expect(await screen.findByText('자료를 등록했습니다.')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1)
    expect(uploadButton()).toHaveTextContent('자료 업로드')
  })

  it('업로드 중 로그인이 끝났으면 로그인 화면으로 이동한다', async () => {
    const { user } = await openMaterials(NONE, { 'POST /api/materials': NOT_LOGGED_IN })
    await screen.findByText(/아직 등록한 자료가 없어요/)
    await fillForm(user)
    await user.click(uploadButton())
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })
})

describe('학습 자료함 삭제', () => {
  let confirmSpy
  beforeEach(() => {
    confirmSpy = vi.spyOn(window, 'confirm')
  })

  it('확인창에서 동의하면 삭제하고 목록과 숫자에서 바로 사라진다', async () => {
    confirmSpy.mockReturnValue(true)
    const { user, calls } = await openMaterials(THREE, {
      'DELETE /api/materials/2': () => new Response(null, { status: 204 }),
    })
    await user.click(await screen.findByRole('button', { name: '회원가입 동작 확인 삭제' }))

    await waitFor(() => expect(screen.queryByText('회원가입 동작 확인')).not.toBeInTheDocument())
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('회원가입 동작 확인'))
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/materials/2')).toBe(true)
    expect(screen.getByRole('button', { name: '전체 2' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '영상 0' })).toBeInTheDocument()
    expect(screen.getByText('REST API 핵심 정리')).toBeInTheDocument()
  })

  it('확인창에서 취소하면 아무것도 지우지 않는다', async () => {
    confirmSpy.mockReturnValue(false)
    const { user, calls } = await openMaterials()
    await user.click(await screen.findByRole('button', { name: '회원가입 동작 확인 삭제' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    expect(screen.getByText('회원가입 동작 확인')).toBeInTheDocument()
  })

  it('삭제에 실패하면 이유를 알리고 자료를 그대로 둔다', async () => {
    confirmSpy.mockReturnValue(true)
    const { user } = await openMaterials(THREE, {
      'DELETE /api/materials/2': () =>
        jsonResponse({ detail: '자료를 삭제하지 못했습니다. 잠시 후 다시 시도해 주세요.', field: null }, 500),
    })
    await user.click(await screen.findByRole('button', { name: '회원가입 동작 확인 삭제' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('자료를 삭제하지 못했습니다.')
    expect(screen.getByText('회원가입 동작 확인')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전체 3' })).toBeInTheDocument()
  })

  it('이미 지워진 자료면 이유를 알리고 목록을 새로 불러온다', async () => {
    confirmSpy.mockReturnValue(true)
    let lists = 0
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => {
        lists += 1
        return jsonResponse(lists === 1 ? THREE : { items: [IMAGE_1, IMAGE_2], counts: { all: 2, image: 2, video: 0 } })
      },
      'DELETE /api/materials/2': () => jsonResponse({ detail: '자료를 찾을 수 없습니다.', field: null }, 404),
    })
    const user = userEvent.setup()
    renderApp('/materials')
    await user.click(await screen.findByRole('button', { name: '회원가입 동작 확인 삭제' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('자료를 찾을 수 없습니다.')
    await waitFor(() => expect(screen.queryByText('회원가입 동작 확인')).not.toBeInTheDocument())
    expect(lists).toBe(2)
  })

  it('삭제 중에는 다른 삭제 버튼도 막는다', async () => {
    confirmSpy.mockReturnValue(true)
    let finish
    const { user } = await openMaterials(THREE, {
      'DELETE /api/materials/2': () => new Promise((resolve) => (finish = () => resolve(new Response(null, { status: 204 })))),
    })
    await user.click(await screen.findByRole('button', { name: '회원가입 동작 확인 삭제' }))
    expect(await screen.findByText('삭제 중…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'REST API 핵심 정리 삭제' })).toBeDisabled()
    finish()
    await waitFor(() => expect(screen.queryByText('회원가입 동작 확인')).not.toBeInTheDocument())
  })

  it('삭제 중 로그인이 끝났으면 로그인 화면으로 이동한다', async () => {
    confirmSpy.mockReturnValue(true)
    const { user } = await openMaterials(THREE, { 'DELETE /api/materials/2': NOT_LOGGED_IN })
    await user.click(await screen.findByRole('button', { name: '회원가입 동작 확인 삭제' }))
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })
})

// ---------- 학습 자료함 AI 요약 ----------

const SUMMARY = '주제 한 줄\n- 핵심 1\n- 핵심 2'
const AI_DONE = { ...IMAGE_1, id: 20, title: '요약된 자료', analysis_status: 'done', summary: SUMMARY, analysis_message: null }
const AI_PENDING = { ...IMAGE_2, id: 21, title: '요약 중인 자료', analysis_status: 'pending', summary: null, analysis_message: null }
const AI_FAILED = {
  ...VIDEO_1,
  id: 22,
  title: '실패한 자료',
  analysis_status: 'failed',
  summary: null,
  analysis_message: '지금은 요청이 많아요. 잠시 후 다시 시도해 주세요.',
}
const AI_SKIPPED = { ...IMAGE_2, id: 23, title: '요약 없는 자료', analysis_status: 'skipped', summary: null, analysis_message: null }

function aiList(items, aiEnabled = true) {
  const count = (kind) => items.filter((m) => m.kind === kind).length
  return { items, counts: { all: items.length, image: count('image'), video: count('video') }, ai_enabled: aiEnabled }
}

const listCalls = (calls) => calls.filter((c) => c.method === 'GET' && c.url === '/api/materials').length

describe('학습 자료함 AI 요약 (화면)', () => {
  afterEach(() => {
    vi.useRealTimers()
    delete document.hidden
  })

  async function open(list, extra = {}) {
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => jsonResponse(list),
      ...extra,
    })
    const user = userEvent.setup({ applyAccept: false })
    const view = renderApp('/materials')
    await screen.findByRole('heading', { name: '학습 자료함' })
    return { user, calls, unmount: view.unmount }
  }

  async function fillAndUpload(user) {
    await user.type(screen.getByLabelText('자료 제목'), '새 자료')
    await user.upload(screen.getByLabelText('자료 파일'), fakeFile('new.png', 'image/png', MB))
    await user.click(screen.getByRole('button', { name: '자료 업로드' }))
  }

  // ----- 등록 폼 -----

  it('AI를 쓸 수 있으면 "AI 요약하기"가 기본으로 켜져 있고 전송 안내가 보인다', async () => {
    await open(aiList([]))
    const checkbox = await screen.findByRole('checkbox', { name: 'AI 요약하기' })
    expect(checkbox).toBeChecked()
    expect(screen.getByText(/OpenAI로 전송돼요/)).toBeInTheDocument()
    expect(screen.getByText(/학습에 사용하지 않지만/)).toBeInTheDocument()
    expect(screen.getByText(/요약은 나만 볼 수 있어요/)).toBeInTheDocument()
  })

  it('체크박스 선택이 업로드 요청에 담긴다', async () => {
    const created = { ...AI_PENDING, id: 30, title: '새 자료' }
    const { user, calls } = await open(aiList([]), { 'POST /api/materials': () => jsonResponse(created, 201) })
    await screen.findByRole('checkbox', { name: 'AI 요약하기' })
    await fillAndUpload(user)
    await screen.findByText('자료를 등록했습니다.')
    expect(calls.find((c) => c.method === 'POST').body.get('ai_summary')).toBe('true')
  })

  it('체크박스를 끄면 ai_summary=false를 보낸다', async () => {
    const created = { ...AI_SKIPPED, id: 31, title: '새 자료' }
    const { user, calls } = await open(aiList([]), { 'POST /api/materials': () => jsonResponse(created, 201) })
    await user.click(await screen.findByRole('checkbox', { name: 'AI 요약하기' }))
    expect(screen.getByRole('checkbox', { name: 'AI 요약하기' })).not.toBeChecked()
    await fillAndUpload(user)
    await screen.findByText('자료를 등록했습니다.')
    expect(calls.find((c) => c.method === 'POST').body.get('ai_summary')).toBe('false')
  })

  it('AI를 쓸 수 없으면 체크박스 없이 설정 안내만 보이고 요청에도 담지 않는다', async () => {
    const created = { ...AI_SKIPPED, id: 32, title: '새 자료' }
    const { user, calls } = await open(aiList([], false), { 'POST /api/materials': () => jsonResponse(created, 201) })
    expect(await screen.findByText('AI 요약은 서버에 OpenAI 키를 설정하면 사용할 수 있어요.')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'AI 요약하기' })).not.toBeInTheDocument()
    expect(screen.queryByText(/OpenAI로 전송돼요/)).not.toBeInTheDocument()
    await fillAndUpload(user)
    await screen.findByText('자료를 등록했습니다.')
    expect(calls.find((c) => c.method === 'POST').body.has('ai_summary')).toBe(false)
  })

  // ----- 카드 상태 -----

  it('요약 중인 자료에는 진행 안내가 보인다', async () => {
    await open(aiList([AI_PENDING]))
    expect(await screen.findByRole('status', { name: '' })).toHaveTextContent('AI가 요약하는 중…')
  })

  it('요약이 끝난 자료에는 요약문이 줄바꿈 그대로 보인다', async () => {
    await open(aiList([AI_DONE]))
    const summary = await screen.findByText((text) => text.startsWith('주제 한 줄'))
    expect(summary).toHaveTextContent('주제 한 줄 - 핵심 1 - 핵심 2')
    expect(summary.textContent).toBe(SUMMARY) // 줄바꿈 유지
    expect(screen.queryByRole('button', { name: '더 보기' })).not.toBeInTheDocument() // 짧으면 접기 버튼 없음
  })

  it('요약문은 글자로만 보이고 HTML로 해석되지 않는다', async () => {
    const html = '<b>굵게</b> <img src="x" onerror="alert(1)"> <script>alert(2)</script>'
    await open(aiList([{ ...AI_DONE, summary: html }]))
    const shown = await screen.findByText(html)
    expect(shown.textContent).toBe(html)
    expect(document.querySelector('b, script, img[src="x"]')).toBeNull()
  })

  it('긴 요약은 접혀 있다가 "더 보기"로 펼치고 "접기"로 다시 접는다', async () => {
    const long = Array.from({ length: 12 }, (_, i) => `- 항목 ${i + 1}`).join('\n')
    const { user } = await open(aiList([{ ...AI_DONE, summary: long }]))
    const toggle = await screen.findByRole('button', { name: '더 보기' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelector('.bm-summary')).not.toHaveClass('bm-summary-open')

    await user.click(toggle)
    const opened = screen.getByRole('button', { name: '접기' })
    expect(opened).toHaveAttribute('aria-expanded', 'true')
    expect(document.querySelector('.bm-summary')).toHaveClass('bm-summary-open')

    await user.click(opened)
    expect(screen.getByRole('button', { name: '더 보기' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('실패한 자료에는 이유와 "다시 분석"이 보인다', async () => {
    await open(aiList([AI_FAILED]))
    expect(await screen.findByText('지금은 요청이 많아요. 잠시 후 다시 시도해 주세요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '실패한 자료 다시 분석' })).toBeEnabled()
  })

  it('AI가 꺼져 있으면 실패 이유는 보이지만 다시 분석 버튼은 없다', async () => {
    await open(aiList([AI_FAILED], false))
    expect(await screen.findByText('지금은 요청이 많아요. 잠시 후 다시 시도해 주세요.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /다시 분석/ })).not.toBeInTheDocument()
  })

  it('요약이 없는 자료는 AI를 쓸 수 있을 때만 "AI 요약 만들기"가 보인다', async () => {
    const { unmount } = await open(aiList([AI_SKIPPED]))
    expect(await screen.findByText('AI 요약 없음')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '요약 없는 자료 AI 요약 만들기' })).toBeInTheDocument()
    unmount()

    await open(aiList([AI_SKIPPED], false))
    await screen.findByText('요약 없는 자료')
    expect(screen.queryByText('AI 요약 없음')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /AI 요약 만들기/ })).not.toBeInTheDocument()
  })

  // ----- 다시 분석 -----

  it('"다시 분석"을 누르면 요청하고 요약 중으로 바뀐 뒤 완료되면 요약이 보인다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let lists = 0
    const queued = { ...AI_FAILED, analysis_status: 'pending', analysis_message: null }
    const recorded = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => {
        lists += 1
        return jsonResponse(aiList([lists === 1 ? AI_FAILED : { ...AI_FAILED, analysis_status: 'done', summary: SUMMARY, analysis_message: null }]))
      },
      'POST /api/materials/22/analyze': () => jsonResponse(queued, 202),
    })
    const user = userEvent.setup({ applyAccept: false, advanceTimers: vi.advanceTimersByTime })
    renderApp('/materials')
    await user.click(await screen.findByRole('button', { name: '실패한 자료 다시 분석' }))

    expect(await screen.findByText('AI가 요약하는 중…')).toBeInTheDocument()
    expect(screen.queryByText('지금은 요청이 많아요. 잠시 후 다시 시도해 주세요.')).not.toBeInTheDocument()
    expect(recorded.some((c) => c.method === 'POST' && c.url === '/api/materials/22/analyze')).toBe(true)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    expect(await screen.findByText((text) => text.startsWith('주제 한 줄'))).toBeInTheDocument()
  })

  it.each([
    [409, '이미 분석 중이에요.'],
    [503, 'AI 요약을 사용할 수 없어요.'],
    [404, '자료를 찾을 수 없습니다.'],
  ])('다시 분석이 %i로 거절되면 이유를 알린다', async (status, detail) => {
    const { user, calls } = await open(aiList([AI_FAILED]), {
      'POST /api/materials/22/analyze': () => jsonResponse({ detail, field: null }, status),
    })
    await user.click(await screen.findByRole('button', { name: '실패한 자료 다시 분석' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    // 목록이 실제와 다를 수 있는 409·404는 새로 불러온다. 503은 그대로 둔다.
    await waitFor(() => expect(listCalls(calls)).toBe(status === 503 ? 1 : 2))
  })

  it('다시 분석 중 로그인이 끝났으면 로그인 화면으로 이동한다', async () => {
    const { user } = await open(aiList([AI_FAILED]), { 'POST /api/materials/22/analyze': NOT_LOGGED_IN })
    await user.click(await screen.findByRole('button', { name: '실패한 자료 다시 분석' }))
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })

  it('다시 분석 요청 중에는 버튼이 막힌다', async () => {
    let finish
    const { user } = await open(aiList([AI_FAILED, AI_SKIPPED]), {
      'POST /api/materials/22/analyze': () => new Promise((resolve) => (finish = () => resolve(jsonResponse({ ...AI_FAILED, analysis_status: 'pending' }, 202)))),
    })
    await user.click(await screen.findByRole('button', { name: '실패한 자료 다시 분석' }))
    expect(screen.getByRole('button', { name: '요약 없는 자료 AI 요약 만들기' })).toBeDisabled()
    finish()
    await screen.findByText('AI가 요약하는 중…')
  })

  // ----- 자동 새로고침(폴링) -----

  it('요약 중인 자료가 있으면 3초마다 목록을 새로 불러와 완료되면 요약을 보여주고 멈춘다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let lists = 0
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => {
        lists += 1
        return jsonResponse(aiList([lists < 3 ? AI_PENDING : { ...AI_PENDING, analysis_status: 'done', summary: SUMMARY }]))
      },
    })
    renderApp('/materials')
    expect(await screen.findByText('AI가 요약하는 중…')).toBeInTheDocument()
    expect(listCalls(calls)).toBe(1)

    await act(async () => { await vi.advanceTimersByTimeAsync(2900) })
    expect(listCalls(calls)).toBe(1) // 3초가 되기 전에는 요청하지 않는다
    await act(async () => { await vi.advanceTimersByTimeAsync(200) })
    expect(listCalls(calls)).toBe(2)
    expect(screen.getByText('AI가 요약하는 중…')).toBeInTheDocument() // 아직 진행 중

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(await screen.findByText((text) => text.startsWith('주제 한 줄'))).toBeInTheDocument()
    expect(listCalls(calls)).toBe(3)

    await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
    expect(listCalls(calls)).toBe(3) // 진행 중인 자료가 없으니 더 이상 요청하지 않는다
  })

  it('진행 중인 자료가 없으면 처음부터 새로 불러오지 않는다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => jsonResponse(aiList([AI_DONE, AI_FAILED, AI_SKIPPED])),
    })
    renderApp('/materials')
    await screen.findByText('요약된 자료')
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(listCalls(calls)).toBe(1)
  })

  it('화면을 떠나면 자동 새로고침이 멈춘다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => jsonResponse(aiList([AI_PENDING])),
    })
    const { unmount } = renderApp('/materials')
    await screen.findByText('AI가 요약하는 중…')
    unmount()
    const before = listCalls(calls)
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(listCalls(calls)).toBe(before)
  })

  it('탭이 숨겨져 있으면 요청하지 않고, 다시 보이면 이어서 새로 불러온다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => jsonResponse(aiList([AI_PENDING])),
    })
    renderApp('/materials')
    await screen.findByText('AI가 요약하는 중…')
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    await act(async () => { await vi.advanceTimersByTimeAsync(12000) })
    expect(listCalls(calls)).toBe(1) // 숨겨진 동안 요청 없음

    delete document.hidden
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(listCalls(calls)).toBe(2)
  })

  it('5분이 지나도 끝나지 않으면 안내하고 새로고침을 멈춘다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => jsonResponse(aiList([AI_PENDING])),
    })
    renderApp('/materials')
    await screen.findByText('AI가 요약하는 중…')
    for (let i = 0; i < 110; i += 1) {
      await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    }
    expect(await screen.findByText('요약이 오래 걸리고 있어요. 잠시 뒤 새로고침해 주세요.')).toBeInTheDocument()
    const stopped = listCalls(calls)
    expect(stopped).toBeGreaterThan(90)
    expect(stopped).toBeLessThan(105) // 5분(약 100번) 안에서 멈춤
    await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
    expect(listCalls(calls)).toBe(stopped)
  })

  it('자동 새로고침이 실패해도 화면을 오류로 바꾸지 않고 다음에 다시 시도한다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let lists = 0
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => {
        lists += 1
        if (lists === 2) return jsonResponse({ detail: '서버 오류', field: null }, 500)
        return jsonResponse(aiList([lists < 3 ? AI_PENDING : { ...AI_PENDING, analysis_status: 'done', summary: SUMMARY }]))
      },
    })
    renderApp('/materials')
    await screen.findByText('AI가 요약하는 중…')
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) }) // 두 번째 요청이 실패
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('AI가 요약하는 중…')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) }) // 세 번째는 성공
    expect(await screen.findByText((text) => text.startsWith('주제 한 줄'))).toBeInTheDocument()
  })

  it('자동 새로고침 중 로그인이 끝났으면 로그인 화면으로 이동한다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let lists = 0
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => {
        lists += 1
        return lists === 1 ? jsonResponse(aiList([AI_PENDING])) : NOT_LOGGED_IN()
      },
    })
    renderApp('/materials')
    await screen.findByText('AI가 요약하는 중…')
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(await screen.findByRole('heading', { name: '로그인' })).toBeInTheDocument()
  })

  it('방금 올린 자료가 요약 중이면 자동으로 새로고침해 요약을 보여준다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const created = { ...AI_PENDING, id: 40, title: '새 자료' }
    let lists = 0
    mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => {
        lists += 1
        return jsonResponse(aiList(lists === 1 ? [] : [{ ...created, analysis_status: 'done', summary: SUMMARY }]))
      },
      'POST /api/materials': () => jsonResponse(created, 201),
    })
    const user = userEvent.setup({ applyAccept: false, advanceTimers: vi.advanceTimersByTime })
    renderApp('/materials')
    await screen.findByRole('checkbox', { name: 'AI 요약하기' })
    await fillAndUpload(user)
    expect(await screen.findByText('AI가 요약하는 중…')).toBeInTheDocument()

    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(await screen.findByText((text) => text.startsWith('주제 한 줄'))).toBeInTheDocument()
  })

  it('자동 새로고침이 일어나도 등록 폼에 입력 중인 내용과 고른 파일은 그대로다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockServer({
      'GET /api/auth/me': () => jsonResponse(ME),
      'GET /api/materials': () => jsonResponse(aiList([AI_PENDING])),
    })
    const user = userEvent.setup({ applyAccept: false, advanceTimers: vi.advanceTimersByTime })
    renderApp('/materials')
    await screen.findByText('AI가 요약하는 중…')
    await user.type(screen.getByLabelText('자료 제목'), '쓰는 중인 제목')
    await user.upload(screen.getByLabelText('자료 파일'), fakeFile('draft.png', 'image/png', MB))

    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    await act(async () => { await vi.advanceTimersByTimeAsync(3100) })
    expect(listCalls(calls)).toBeGreaterThanOrEqual(3)
    expect(screen.getByLabelText('자료 제목')).toHaveValue('쓰는 중인 제목')
    expect(screen.getByText('draft.png')).toBeInTheDocument()
  })

  // ----- 하단 AI 영역 -----

  it.each([
    [true, 'AI 학습 도우미 · 사용 중', '올린 이미지와 영상을 자동으로 요약해요.'],
    [false, 'AI 학습 도우미 · 설정 필요', '서버에 OpenAI 키를 설정하면 이미지와 영상을 자동으로 요약해요.'],
  ])('하단 AI 영역은 상태(%s)를 보여주고 "연결 예정" 버튼이 없다', async (enabled, title, text) => {
    await open(aiList([], enabled))
    const heading = await screen.findByRole('heading', { name: /AI 학습 도우미/ })
    await waitFor(() => expect(heading.textContent.replace(/\s+/g, ' ')).toBe(title))
    expect(screen.getByText(text)).toBeInTheDocument()
    expect(screen.queryByText('이미지 분석 연결 예정')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /연결 예정/ })).not.toBeInTheDocument()
  })
})
