import artist from '../../assets/mascot/mascot-artist.webp'
import check from '../../assets/mascot/mascot-check.webp'
import cheer from '../../assets/mascot/mascot-cheer.webp'
import curious from '../../assets/mascot/mascot-curious.webp'
import goal from '../../assets/mascot/mascot-goal.webp'
import good from '../../assets/mascot/mascot-good.webp'
import growth from '../../assets/mascot/mascot-growth.webp'
import happy from '../../assets/mascot/mascot-happy.webp'
import note from '../../assets/mascot/mascot-note.webp'
import practice from '../../assets/mascot/mascot-practice.webp'
import reading from '../../assets/mascot/mascot-reading.webp'
import standing from '../../assets/mascot/mascot-standing.webp'
import teacher from '../../assets/mascot/mascot-teacher.webp'
import worried from '../../assets/mascot/mascot-worried.webp'

/**
 * 고양이 표정·자세
 * standing 기본 · artist 베레모+붓 (그리러 가요) · cheer 주먹 (응원) · check 안경+체크리스트 (분석·확인)
 * teacher 안경 쓰고 이젤 앞에서 설명 (선생님 한마디)
 * goal '다음 목표!' 판을 가리키는 고양이 (성장 리포트 다음 목표)
 * growth 계단 오르기 (성장 리포트, 흰 배경 그림이라 mix-blend-mode: multiply로 씀)
 * practice 책상에서 소묘·연습 체크리스트 (다음 연습) · good '잘하고 있어 ㅎㅎ' 말풍선 (잘하는 점) · reading 잡지 읽기 (커뮤니티)
 * note 메모장에 적기 (글로 남기기) · happy 웃으며 체크 (완료) · curious 책상에서 갸웃 (비어 있음·찾을 수 없음) · worried 책상에서 곤란 (시간 초과·오류)
 */
export const MASCOT_POSES = {
  standing,
  teacher,
  artist,
  cheer,
  check,
  happy,
  goal,
  good,
  growth,
  note,
  practice,
  reading,
  curious,
  worried,
}
