// 서버가 켜져 있는지 확인합니다. 응답이 정상이면 true를 돌려줍니다.
export async function checkHealth() {
  const response = await fetch('/api/health')
  if (!response.ok) {
    return false
  }
  const data = await response.json()
  return data.status === 'ok'
}
