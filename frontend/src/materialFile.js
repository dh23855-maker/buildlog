// 학습 자료함에 올릴 파일의 조건입니다. 서버에 보내기 전에 화면에서 먼저 알려주기 위한 검사이며,
// 최종 판단은 서버가 합니다. (docs/plan.md 9장)

const MB = 1024 * 1024

export const TITLE_MAX_LENGTH = 100
export const MEMO_MAX_LENGTH = 1000
export const ACCEPT = 'image/png,image/jpeg,video/mp4'

// 확장자 → 종류와 크기 한도. 1MB는 1,048,576바이트로 계산합니다.
const RULES = {
  png: { type: 'image/png', label: 'PNG', limit: 5 * MB },
  jpg: { type: 'image/jpeg', label: 'JPG', limit: 5 * MB },
  jpeg: { type: 'image/jpeg', label: 'JPG', limit: 5 * MB },
  mp4: { type: 'video/mp4', label: 'MP4', limit: 30 * MB },
}

const UNSUPPORTED = 'PNG, JPG, MP4 파일만 올릴 수 있어요.'

function extensionOf(name) {
  const dot = name.lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot + 1).toLowerCase()
}

export function formatSize(bytes) {
  if (bytes < MB) return `${Math.max(1, Math.round(bytes / 1024))}KB`
  return `${(bytes / MB).toFixed(1)}MB`
}

// 문제가 없으면 { ok: true, label }, 있으면 { ok: false, message }를 돌려줍니다.
export function checkMaterialFile(file) {
  const rule = RULES[extensionOf(file.name)]
  if (!rule) return { ok: false, message: UNSUPPORTED }
  // 브라우저가 알려준 형식이 있으면 확장자와 같아야 합니다. (형식이 비어 있는 브라우저도 있어 확장자를 기준으로 합니다.)
  if (file.type && file.type !== rule.type) return { ok: false, message: UNSUPPORTED }
  if (file.size === 0) return { ok: false, message: '비어 있는 파일은 올릴 수 없어요.' }
  if (file.size > rule.limit) {
    return {
      ok: false,
      message: `${rule.label} 파일은 ${rule.limit / MB}MB까지 올릴 수 있어요. (선택한 파일 ${formatSize(file.size)})`,
    }
  }
  return { ok: true, label: rule.label }
}

// ---------- 목록 표시용 ----------

export const KIND_LABELS = { image: '이미지', video: '영상' }
const FORMAT_LABELS = { 'image/png': 'PNG', 'image/jpeg': 'JPG', 'video/mp4': 'MP4' }

export function formatLabel(contentType) {
  return FORMAT_LABELS[contentType] ?? ''
}

// 서버가 UTC로 보낸 시각을 한국 시간 날짜(2026.10.20)로 보여줍니다.
// 시간대 표시가 없는 값은 UTC로 봅니다. (서버는 UTC로 저장합니다)
export function formatDate(iso) {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso)
  const date = new Date(hasZone ? iso : `${iso}Z`)
  if (Number.isNaN(date.getTime())) return ''
  const parts = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const get = (type) => parts.find((p) => p.type === type).value
  return `${get('year')}.${get('month')}.${get('day')}`
}

