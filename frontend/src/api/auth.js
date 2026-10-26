// 서버가 돌려준 오류를 화면에서 쓰기 쉽게 담는 오류입니다.
// message는 사용자에게 보여줄 문장, field는 문제가 된 입력 칸(email, password, nickname)입니다.
export class ApiError extends Error {
  constructor(message, { field = null, status = 0 } = {}) {
    super(message)
    this.field = field
    this.status = status
  }
}

const NETWORK_ERROR_MESSAGE = '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'

async function request(method, url, body) {
  let response
  try {
    response = await fetch(url, {
      method,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(NETWORK_ERROR_MESSAGE)
  }

  if (response.status === 204) {
    return null
  }

  let data = null
  try {
    data = await response.json()
  } catch {
    // 본문이 없거나 JSON이 아닌 경우는 아래에서 일반 안내로 처리합니다.
  }

  if (!response.ok) {
    const message = typeof data?.detail === 'string' ? data.detail : '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'
    throw new ApiError(message, { field: data?.field ?? null, status: response.status })
  }
  return data
}

export function signup({ email, password, nickname }) {
  return request('POST', '/api/auth/signup', { email, password, nickname })
}

export function login({ email, password }) {
  return request('POST', '/api/auth/login', { email, password })
}

export function logout() {
  return request('POST', '/api/auth/logout')
}

// 로그인한 사용자를 돌려줍니다. 로그인하지 않았으면 null입니다.
export async function fetchMe() {
  try {
    return await request('GET', '/api/auth/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null
    }
    throw error
  }
}

export function changeNickname(nickname) {
  return request('PATCH', '/api/account/nickname', { nickname })
}
