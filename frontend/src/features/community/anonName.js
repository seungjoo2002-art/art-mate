/**
 * 익명 작성자 별명: "그림그리는고양이"처럼 꾸밈말 + 고양이.
 * 게시물 id로 고르므로 같은 글은 늘 같은 별명 (서버에는 '익명 학생'으로만 옴)
 */
const ADJECTIVES = [
  '그림그리는',
  '붓을든',
  '스케치하는',
  '색칠하는',
  '연필깎는',
  '물감묻은',
  '밤샘하는',
  '팔레트든',
  '명암넣는',
  '구도잡는',
]

export function anonName(seed) {
  let h = 0
  for (const ch of String(seed)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return `${ADJECTIVES[h % ADJECTIVES.length]}고양이`
}

/** 화면에 보일 작성자 이름: 익명이면 고양이 별명 */
export const authorName = (post) =>
  post.author?.is_anonymous ? anonName(post.id) : (post.author?.display_name ?? '')
