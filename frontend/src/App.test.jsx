import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

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
    const body = options.body ? JSON.parse(options.body) : undefined
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
