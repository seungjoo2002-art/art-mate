# ART MATE

미술 입시생을 위한 **AI 기반 미술 실기 학습·성장 관리 플랫폼**입니다.
학생의 작품 사진과 강사 첨삭 음성을 기록하고, AI가 피드백을 정리해 작품별 학습 이력을 쌓은 뒤
개인 성장 리포트·맞춤 과제·참고작 추천으로 이어지는 것을 목표로 합니다.

> 2026-11 기획 변경: 학원 운영 관리(출석·오늘 할 일·질문 콜·시험 타이머)는 서비스 범위에서 제외했습니다.
> 변경 내역은 [docs/v0.5.1-planning-changes.md](docs/v0.5.1-planning-changes.md)를 보세요.

## 구성

| 폴더 | 내용 |
| --- | --- |
| [backend/](backend/README.md) | FastAPI + Supabase(PostgreSQL·Auth·Storage) API 서버 |
| [frontend/](frontend/README.md) | Vite + React 웹 앱 |
| [docs/](docs/) | 아키텍처, DB 설계, 프론트 연동 가이드, 개발 가이드 |

## 구현 현황 (v0.6)

| 기능 | 상태 |
| --- | --- |
| 회원가입·로그인(Supabase Auth), 프로필·실기 유형 | ✅ |
| 학원·반·담당 강사·과제 (작품 접근 권한의 기반) | ✅ |
| 작품 생성, 단계별(스케치·중간·완성) 사진 업로드 | ✅ |
| 작품 분류(실기 유형 × 작업 목적)·필터, 작품 완료 | ✅ |
| 강사 첨삭 음성 녹음 저장·녹음 동의, 작품별 녹음 수 | ✅ |
| 첨삭 녹음 전사(STT)·AI 요약·약점 분류·강사 검토·승인 | ✅ v0.6 |
| 개인 성장 리포트·반복 약점 분석·맞춤 과제 | ⏳ v0.7 |
| AI 참고작 추천 (F-15, 신규 정의·미구현)·커뮤니티 연동 | ⏳ v0.8 |
| AI 직접 작품 분석·실기 튜터 | 이후 |
| 입시 합격 가능성 예측 | 장기 |

## 로드맵

1. **피드백 기록** — 작품 사진과 강사 첨삭 음성을 기록하고, AI가 피드백을 요약·분류해 작품별 학습 이력을 누적합니다. (v0.5.1 ~ v0.6)
2. **AI 개인 맞춤형 성장 코치** — 누적된 작품·첨삭 기록으로 성장 리포트와 맞춤 연습 과제를 제공하고, 약점과 유사한 문제를 잘 해결한 참고작을 추천합니다(F-15). (v0.7 ~ v0.8)
3. **AI 전문 실기 튜터** — 강사 기록 없이도 AI가 작품 사진을 직접 분석해 피드백과 과제를 제공합니다.
4. **입시 합격률 예측** — 실기 평가·학업 성적·지원 대학·합격 결과를 연결해 대학별 지원 전략을 제안합니다.

커뮤니티 기능은 유지합니다.

## 문서

- [backend/README.md](backend/README.md) — 설치·실행·테스트·마이그레이션
- [docs/architecture.md](docs/architecture.md) — 구조와 AI 연동 계획
- [docs/database-design.md](docs/database-design.md) — 테이블 설계
- [docs/ai-feedback-v0.6.md](docs/ai-feedback-v0.6.md) — AI 첨삭 구조·비용·개인정보
- [docs/frontend-integration-v0.6.md](docs/frontend-integration-v0.6.md) — 최신 프론트 연동 (v0.6)
- [docs/frontend-integration-v0.5.1.md](docs/frontend-integration-v0.5.1.md) — v0.5.1 변경
- [docs/supabase-dev-verification.md](docs/supabase-dev-verification.md) — 개발 DB·Storage 검증 절차
- [docs/development-guide.md](docs/development-guide.md) — 협업 규칙
