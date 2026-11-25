import { describe, expect, it } from 'vitest'
import {
  IMAGE_ERRORS,
  normalizedName,
  prepareImageFile,
  prepareImageFiles,
  sniffImageType,
} from './imageFile'

const bytes = (...parts) =>
  new Uint8Array(parts.flatMap((p) => (typeof p === 'string' ? [...p].map((c) => c.charCodeAt(0)) : p)))
const u32 = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]
const ftyp = (major, ...compatible) =>
  bytes(u32(16 + 4 * compatible.length), 'ftyp', major, [0, 0, 0, 0], ...compatible)

const JPEG = bytes([0xff, 0xd8, 0xff, 0xe1], 'Exif')
const PNG = bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
const WEBP = bytes('RIFF', [0, 0, 0, 0], 'WEBPVP8 ')
const file = (data, name, type = '') => new File([data], name, { type })

describe('sniffImageType: 실제 내용으로 형식 판별', () => {
  it('JPEG·PNG·WEBP', () => {
    expect(sniffImageType(JPEG)).toBe('image/jpeg')
    expect(sniffImageType(PNG)).toBe('image/png')
    expect(sniffImageType(WEBP)).toBe('image/webp')
  })

  it('HEIC·HEIF (아이폰·갤럭시 브랜드)', () => {
    expect(sniffImageType(ftyp('heic', 'mif1', 'heic'))).toBe('image/heic')
    expect(sniffImageType(ftyp('mif1', 'mif1', 'heic'))).toBe('image/heic')
    expect(sniffImageType(ftyp('heix'))).toBe('image/heic')
    expect(sniffImageType(ftyp('mif1', 'mif1'))).toBe('image/heif')
    expect(sniffImageType(ftyp('heif'))).toBe('image/heif')
  })

  it('지원하지 않는 형식·사진이 아닌 파일은 null', () => {
    expect(sniffImageType(ftyp('avif', 'mif1', 'avif'))).toBeNull()
    expect(sniffImageType(ftyp('mp42', 'isom'))).toBeNull() // 동영상
    expect(sniffImageType(bytes('GIF89a'))).toBeNull()
    expect(sniffImageType(bytes('hello, this is text'))).toBeNull()
    expect(sniffImageType(new Uint8Array())).toBeNull()
  })
})

describe('normalizedName', () => {
  it('대문자·다른 확장자를 저장 형식에 맞춤', () => {
    expect(normalizedName('IMG_0001.JPG', 'image/jpeg')).toBe('IMG_0001.jpg')
    expect(normalizedName('photo.JPEG', 'image/jpeg')).toBe('photo.jpg')
    expect(normalizedName('IMG_1.HEIC', 'image/jpeg')).toBe('IMG_1.jpg')
    expect(normalizedName('scan', 'image/png')).toBe('scan.png')
    expect(normalizedName('', 'image/webp')).toBe('photo.webp')
  })
})

describe('prepareImageFile', () => {
  it('MIME이 비었거나 틀려도 내용으로 판별하고 이름을 바로잡음', async () => {
    const empty = await prepareImageFile(file(JPEG, 'IMG_0001.JPG', ''))
    expect([empty.type, empty.name]).toEqual(['image/jpeg', 'IMG_0001.jpg'])
    const jpg = await prepareImageFile(file(JPEG, 'a.jpeg', 'image/jpg')) // 일부 안드로이드
    expect([jpg.type, jpg.name]).toEqual(['image/jpeg', 'a.jpg'])
    const png = await prepareImageFile(file(PNG, 'B.PNG', 'image/png'))
    expect([png.type, png.name]).toEqual(['image/png', 'B.png'])
    const webp = await prepareImageFile(file(WEBP, 'c.webp', 'application/octet-stream'))
    expect(webp.type).toBe('image/webp')
  })

  it('이미 올바른 파일은 그대로', async () => {
    const original = file(JPEG, 'a.jpg', 'image/jpeg')
    expect(await prepareImageFile(original)).toBe(original)
  })

  it('확장자만 바꾼 파일은 거부', async () => {
    await expect(prepareImageFile(file(bytes('not an image'), 'fake.jpg', 'image/jpeg'))).rejects.toMatchObject({
      kind: 'UNSUPPORTED',
      userMessage: IMAGE_ERRORS.UNSUPPORTED,
    })
  })

  it('빈 파일·너무 큰 파일은 원인별 안내', async () => {
    await expect(prepareImageFile(file(new Uint8Array(), 'a.jpg'))).rejects.toMatchObject({
      kind: 'EMPTY',
    })
    const big = new Uint8Array(10 * 1024 * 1024 + 1)
    big.set([0xff, 0xd8, 0xff])
    await expect(prepareImageFile(file(big, 'big.jpg', 'image/jpeg'))).rejects.toMatchObject({
      kind: 'TOO_LARGE',
      userMessage: IMAGE_ERRORS.TOO_LARGE,
    })
  })

  it('안내 문구에 지원 형식이 모두 있음', () => {
    for (const label of ['JPG', 'JPEG', 'PNG', 'WEBP', 'HEIC', 'HEIF']) {
      expect(IMAGE_ERRORS.UNSUPPORTED).toContain(label)
    }
  })

  it('여러 장: 실패한 것만 빼고 계속', async () => {
    const { files, rejected } = await prepareImageFiles([
      file(JPEG, 'ok.JPG', ''),
      file(bytes('text'), 'bad.png', 'image/png'),
    ])
    expect(files.map((f) => f.name)).toEqual(['ok.jpg'])
    expect(rejected).toEqual([{ name: 'bad.png', message: IMAGE_ERRORS.UNSUPPORTED }])
  })
})
