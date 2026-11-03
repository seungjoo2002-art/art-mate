## 개요
<!-- 이 PR이 무엇을, 왜 바꾸는지 1~3줄 -->

## 관련 이슈 / 버전
- 버전: v0.x
- 이슈: #

## 변경 사항
-

## DB 변경
- [ ] 없음
- [ ] 있음 → Alembic 리비전 포함, `down_revision`이 최신 head인지 확인, `docs/database-design.md` 갱신

## 확인 사항
- [ ] `uv run ruff check . && uv run ruff format --check .` 통과
- [ ] `uv run pytest` 통과 (새 기능에 테스트 추가)
- [ ] 새 환경변수가 있으면 `.env.example` · README 반영
- [ ] 비밀값(.env, 키, 토큰, 실제 DB URL)이 커밋에 없음
- [ ] 보호가 필요한 API에 `CurrentUser` 의존성 적용 / 학원 단위 권한 확인

## 리뷰어에게
<!-- 특히 봐 줬으면 하는 부분, 트레이드오프 -->
