// 앱 전체 사진 업로드 공통 처리: 실제 파일 내용(앞부분 바이트)으로 형식을 판별하고,
// HEIC·HEIF(아이폰·일부 안드로이드 기본 형식)는 브라우저에서 JPEG로 바꿔 올린다.
// 서버·Storage에는 지금처럼 JPEG·PNG·WEBP만 저장된다 (서버가 실제 이미지 데이터를 다시 검증).
// 휴대폰이 알려 주는 MIME 타입은 비어 있거나 'image/jpg'처럼 틀릴 수 있어 믿지 않는다.

/** 파일 고르기: 모든 사진을 보여 준다 (안드로이드에서 HEIC·형식 표시가 없는 사진도 고를 수 있게) */
export const IMAGE_ACCEPT = 'image/*'

export const IMAGE_FORMATS_LABEL = 'JPG·JPEG·PNG·WEBP·HEIC·HEIF'
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024 // 서버 ARTWORK_MAX_UPLOAD_BYTES와 같음
const MAX_SOURCE_BYTES = 40 * 1024 * 1024 // 변환 전 HEIC 원본 상한 (메모리 보호)
// 브라우저 캔버스 한계(iOS Safari 약 16.7M 픽셀) 안에서 변환. 넘으면 비율을 유지한 채 줄임
const MAX_CANVAS_PIXELS = 16_000_000
const JPEG_QUALITIES = [0.92, 0.85, 0.75] // 10MB를 넘으면 단계적으로 낮춤

const EXTENSION = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'image/webp': 'webp',
}

export const IMAGE_ERRORS = {
  UNSUPPORTED: `${IMAGE_FORMATS_LABEL} 사진만 올릴 수 있어요.`,
  TOO_LARGE: '사진 용량이 너무 커요. 10MB 이하 사진을 골라 주세요.',
  CONVERT_FAILED:
    'HEIC·HEIF 사진을 변환하지 못했어요. 다른 사진을 고르거나 잠시 후 다시 시도해 주세요.',
  EMPTY: '빈 파일이에요. 다른 사진을 골라 주세요.',
  READ_FAILED: '사진 파일을 읽지 못했어요. 다시 골라 주세요.',
}

/** 사진 준비 실패: kind로 원인을 구분 (UNSUPPORTED | TOO_LARGE | CONVERT_FAILED | EMPTY | READ_FAILED) */
export class ImageFileError extends Error {
  constructor(kind) {
    super(kind)
    this.kind = kind
    this.userMessage = IMAGE_ERRORS[kind]
  }
}

const ascii = (bytes, start, end) => String.fromCharCode(...bytes.slice(start, end))

const HEIC_BRANDS = new Set(['heic', 'heix', 'heim', 'heis', 'hevc', 'hevx', 'hevm', 'hevs'])
const HEIF_BRANDS = new Set(['mif1', 'msf1', 'heif'])

/**
 * 파일 앞부분 바이트로 실제 형식 판별 → 'image/jpeg' | 'image/png' | 'image/webp' | 'image/heic'
 * | 'image/heif' | null. 확장자·MIME 선언과 상관없이 내용으로만 본다 (AVIF 등은 null)
 */
export function sniffImageType(bytes) {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return 'image/jpeg'
  }
  const png = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
  if (bytes.length >= 8 && png.every((b, i) => bytes[i] === b)) return 'image/png'
  if (bytes.length >= 12 && ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 12) === 'WEBP') {
    return 'image/webp'
  }
  // ISO BMFF: [크기 4바이트]['ftyp'][주 브랜드][버전][호환 브랜드…]
  if (bytes.length >= 12 && ascii(bytes, 4, 8) === 'ftyp') {
    const boxSize = Math.min(
      ((bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3]) >>> 0,
      bytes.length,
    )
    const brands = [ascii(bytes, 8, 12)]
    for (let i = 16; i + 4 <= boxSize; i += 4) brands.push(ascii(bytes, i, i + 4))
    if (brands.includes('avif') || brands.includes('avis')) return null
    if (brands.some((b) => HEIC_BRANDS.has(b))) return 'image/heic'
    if (brands.some((b) => HEIF_BRANDS.has(b))) return 'image/heif'
  }
  return null
}

/** 저장 형식에 맞는 파일 이름 (대문자 확장자·다른 확장자 정리, 서버의 확장자 검사와 맞춤) */
export function normalizedName(name, type) {
  const base = (name || 'photo').replace(/\.[^./\\]*$/, '') || 'photo'
  return `${base}.${EXTENSION[type]}`
}

async function headBytes(file) {
  try {
    return new Uint8Array(await file.slice(0, 64).arrayBuffer())
  } catch {
    throw new ImageFileError('READ_FAILED')
  }
}

/**
 * 올릴 수 있는 사진 파일로 준비: JPEG·PNG·WEBP는 그대로(형식·이름만 바로잡음),
 * HEIC·HEIF는 JPEG로 변환(비율·회전 방향 유지, 화질 0.92부터). 실패하면 ImageFileError
 */
export async function prepareImageFile(file) {
  if (!file || file.size === 0) throw new ImageFileError('EMPTY')
  const type = sniffImageType(await headBytes(file))
  if (!type) throw new ImageFileError('UNSUPPORTED')

  if (type === 'image/heic' || type === 'image/heif') {
    if (file.size > MAX_SOURCE_BYTES) throw new ImageFileError('TOO_LARGE')
    const jpeg = await convertToJpeg(file)
    return new File([jpeg], normalizedName(file.name, 'image/jpeg'), {
      type: 'image/jpeg',
      lastModified: file.lastModified,
    })
  }

  if (file.size > MAX_IMAGE_BYTES) throw new ImageFileError('TOO_LARGE')
  const name = normalizedName(file.name, type)
  if (file.type === type && file.name === name) return file
  return new File([file], name, { type, lastModified: file.lastModified })
}

/** 여러 장: { files: 준비된 파일, rejected: [{ name, message }] } (실패한 것만 빼고 계속) */
export async function prepareImageFiles(files) {
  const prepared = []
  const rejected = []
  for (const file of files) {
    try {
      prepared.push(await prepareImageFile(file))
    } catch (err) {
      rejected.push({ name: file.name, message: err.userMessage ?? IMAGE_ERRORS.READ_FAILED })
    }
  }
  return { files: prepared, rejected }
}

/** HEIC·HEIF → 이미지(회전 방향 적용됨). Safari는 직접 읽고, 다른 브라우저는 변환기를 그때 불러옴 */
async function decodeHeic(file) {
  try {
    return await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    // Chrome·안드로이드 등: HEIC 디코더(WASM)는 필요할 때만 받아 온다
    const { heicTo } = await import('heic-to/csp')
    return heicTo({ blob: file, type: 'bitmap', options: { imageOrientation: 'from-image' } })
  }
}

async function convertToJpeg(file) {
  let bitmap
  try {
    bitmap = await decodeHeic(file)
  } catch {
    throw new ImageFileError('CONVERT_FAILED')
  }
  try {
    const { width, height } = bitmap
    const scale = Math.min(1, Math.sqrt(MAX_CANVAS_PIXELS / (width * height)))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(width * scale))
    canvas.height = Math.max(1, Math.round(height * scale))
    const ctx = canvas.getContext('2d')
    ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    for (const quality of JPEG_QUALITIES) {
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
      if (!blob) throw new ImageFileError('CONVERT_FAILED')
      if (blob.size <= MAX_IMAGE_BYTES) return blob
    }
    throw new ImageFileError('TOO_LARGE')
  } catch (err) {
    throw err instanceof ImageFileError ? err : new ImageFileError('CONVERT_FAILED')
  } finally {
    bitmap.close?.()
  }
}
