import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import App from './App.jsx'

function mockFetch(implementation) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(implementation)
}

describe('App', () => {
  it('서버가 정상 응답하면 "서버 연결됨"을 보여준다', async () => {
    mockFetch(async () => new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))

    render(<App />)

    expect(await screen.findByText('서버 연결됨')).toBeInTheDocument()
    expect(globalThis.fetch).toHaveBeenCalledWith('/api/health')
  })

  it('서버가 오류로 응답하면 연결 실패 안내를 보여준다', async () => {
    mockFetch(async () => new Response('', { status: 500 }))

    render(<App />)

    expect(await screen.findByText(/서버에 연결하지 못했습니다/)).toBeInTheDocument()
  })

  it('서버에 닿지 못하면 연결 실패 안내를 보여준다', async () => {
    mockFetch(async () => {
      throw new TypeError('Failed to fetch')
    })

    render(<App />)

    expect(await screen.findByText(/서버에 연결하지 못했습니다/)).toBeInTheDocument()
  })
})
