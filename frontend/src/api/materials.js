import { ApiError } from './auth.js'

const NETWORK_ERROR_MESSAGE = '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
const GENERIC_ERROR_MESSAGE = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.'

// 학습 자료함 요청입니다. 서버가 돌려준 오류는 기존과 같은 ApiError로 바꿉니다.
// body가 FormData(파일 업로드)이면 Content-Type을 직접 지정하지 않습니다. 브라우저가 경계값과 함께 알아서 넣습니다.
async function request(method, url, body) {
  let response
  try {
    response = await fetch(url, { method, body })
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
    const message = typeof data?.detail === 'string' ? data.detail : GENERIC_ERROR_MESSAGE
    throw new ApiError(message, { field: data?.field ?? null, status: response.status })
  }
  return data
}

// { items: [...], counts: { all, image, video } } — 내 자료만 최신순입니다.
export function listMaterials() {
  return request('GET', '/api/materials')
}

// aiSummary: true/false이면 "AI 요약하기" 선택을 함께 보냅니다. undefined(서버에 키가 없는 경우)면 보내지 않습니다.
export function createMaterial({ title, memo, file, aiSummary }) {
  const form = new FormData()
  form.append('title', title)
  form.append('memo', memo)
  form.append('file', file)
  if (aiSummary !== undefined) form.append('ai_summary', aiSummary ? 'true' : 'false')
  return request('POST', '/api/materials', form)
}

// 실패했거나 아직 요약하지 않은 자료의 AI 요약을 (다시) 시작합니다. 바로 돌아오며 결과는 목록을 다시 불러와 확인합니다.
export function analyzeMaterial(id) {
  return request('POST', `/api/materials/${id}/analyze`)
}

export function deleteMaterial(id) {
  return request('DELETE', `/api/materials/${id}`)
}

// 원본 이미지·영상 주소입니다. 로그인한 브라우저(쿠키)에서만 열립니다.
export function fileUrl(id) {
  return `/api/materials/${id}/file`
}
