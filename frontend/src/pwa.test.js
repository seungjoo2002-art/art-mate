import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// PWA 홈 화면 추가 설정 (public/manifest.webmanifest, index.html). 빌드하면 public이 그대로 복사된다
const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '..')
const read = (path) => readFileSync(resolve(root, path))
const pngSize = (path) => {
  const b = read(path)
  expect(b.toString('ascii', 1, 4)).toBe('PNG')
  return `${b.readUInt32BE(16)}x${b.readUInt32BE(20)}`
}

describe('PWA manifest', () => {
  const manifest = JSON.parse(read('public/manifest.webmanifest').toString('utf8'))

  it('앱 이름·시작 경로·standalone', () => {
    expect(manifest).toMatchObject({
      name: 'ART MATE',
      short_name: 'ART MATE',
      start_url: '/',
      scope: '/',
      display: 'standalone',
    })
  })

  it('Android 192·512 아이콘과 maskable 아이콘이 실제 크기로 있다', () => {
    const icons = manifest.icons.map((i) => [i.sizes, i.purpose])
    expect(icons).toEqual(
      expect.arrayContaining([
        ['192x192', 'any'],
        ['512x512', 'any'],
        ['512x512', 'maskable'],
      ]),
    )
    for (const icon of manifest.icons) {
      expect(icon.src).toMatch(/\?v=\d+$/) // 아이콘 교체 시 캐시 갱신용
      expect(pngSize(`public${icon.src.split('?')[0]}`)).toBe(icon.sizes)
    }
  })

  it('index.html이 manifest·iOS 아이콘을 연결한다', () => {
    const html = read('index.html').toString('utf8')
    expect(html).toContain('<link rel="manifest" href="/manifest.webmanifest" />')
    expect(html).toContain('<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png?v=')
    expect(pngSize('public/icons/apple-touch-icon.png')).toBe('180x180')
    for (const size of [32, 48]) {
      expect(html).toContain(`href="/icons/favicon-${size}.png?v=`)
      expect(pngSize(`public/icons/favicon-${size}.png`)).toBe(`${size}x${size}`)
    }
    expect(html).toContain('viewport-fit=cover') // 노치·홈 바 safe-area
  })

  it('서비스 워커를 등록하지 않는다 (API 응답·인증 토큰을 캐시하지 않음)', () => {
    const main = read('src/main.jsx').toString('utf8')
    expect(main).not.toMatch(/serviceWorker/)
  })
})
