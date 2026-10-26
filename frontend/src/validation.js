// 서버(backend/app/schemas/auth.py)와 같은 조건입니다. 입력하는 동안 미리 안내하는 데 씁니다.
// 최종 판단은 항상 서버가 합니다.

export const EMAIL_HINT = '예: name@example.com'
export const PASSWORD_HINT = '8자 이상 64자 이하로 입력해 주세요.'
export const NICKNAME_HINT = '2~20자, 한글·영문·숫자·밑줄(_)만 사용할 수 있습니다.'

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const NICKNAME_PATTERN = /^[0-9A-Za-z_가-힣]{2,20}$/

// 각 함수는 문제가 있으면 안내 문장을, 문제가 없으면 null을 돌려줍니다.
export function validateEmail(value) {
  const email = value.trim()
  if (!email) return '이메일을 입력해 주세요.'
  if (email.length > 254 || !EMAIL_PATTERN.test(email)) return '올바른 이메일 주소를 입력해 주세요.'
  return null
}

export function validatePassword(value) {
  if (!value) return '비밀번호를 입력해 주세요.'
  if (value.length < 8 || value.length > 64) return '비밀번호는 8자 이상 64자 이하로 입력해 주세요.'
  return null
}

export function validateNickname(value) {
  const nickname = value.trim()
  if (!nickname) return '닉네임을 입력해 주세요.'
  if (!NICKNAME_PATTERN.test(nickname)) return '닉네임은 2~20자의 한글, 영문, 숫자, 밑줄(_)만 사용할 수 있습니다.'
  return null
}
