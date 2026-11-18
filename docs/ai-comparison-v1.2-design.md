# AI 비교 첨삭 설계 (v1.1 기반 → v1.2 구현)

v1.1은 **데이터 기반만** 만든다: 원본 제시물 사진, 시험 조건, 표현 의도를 저장하고 AI에 보낼 입력 구조를 고정한다.
v1.1에는 다음이 없다.

- 실제 AI 호출
- 가짜 분석 결과나 점수
- ArtCLIP, OpenCV, 세그멘테이션, RAG

## 1. v1.1에서 저장하는 것

| 데이터 | 위치 | 비고 |
| --- | --- | --- |
| 원본 제시물 사진 (0~N장, 기본 최대 5) | `artwork_reference_photos` | 작품 사진(`artwork_photos`)과 분리된 테이블이다. 그래서 진행률, 대표 사진, 공유, 성장 분석에 섞이지 않는다 |
| 사진 파일 | Storage `artworks` 버킷 `{owner}/{artwork}/ref-{id}.{ext}` | 기존 작품 사진 경로는 바꾸지 않는다. 접근 권한은 아래 설명 참고 |
| 시험 주제, 실기 유형, 제시물, 시험 시간 | 기존 `artworks` 컬럼 재사용 | `topic`, `practical_type`, `exam_materials`, `time_limit_minutes` |
| 화지 규격, 추가 시험 조건 | `artworks.paper_size`, `artworks.exam_conditions` | 선택 입력. 기존 작품은 NULL |
| 자유 메모 | 기존 `artworks.description` | |
| 표현 방식 (다중 선택) | `artworks.expression_methods varchar[]` | 7개 값만 허용(CHECK 제약). 기본값 `{}` |
| 표현 의도 설명 | `artworks.expression_intent` | 1000자 이내 |

표현 방식 코드는 다음 7개다.

- `SCALE` 확대·축소
- `ROTATE` 회전·기울이기
- `REPEAT` 반복·중첩
- `CUT` 절단·분해
- `DISTORT` 형태 과장·왜곡
- `REARRANGE` 재배치
- `OTHER` 기타

Storage 접근은 migration 0016이 DB 함수 `artmate_private.can_access_artwork_object`를 확장해서 처리한다. `ref-` 경로는 소유 학생만 읽고 쓸 수 있고, 삭제된 사진은 읽을 수 없다. Supabase Storage 정책 자체는 바꾸지 않는다.

## 2. AI 입력 구조: `ComparisonInput` (`comparison-input-v1`)

`GET /api/v1/artworks/{id}/comparison-input`로 미리 볼 수 있다. 본인 작품만 조회되고 AI는 호출하지 않는다.
코드는 `app/schemas/comparison.py`와 `app/services/comparison_input.py`(순수 함수)에 있다.

```text
ComparisonInput
├─ schema_version: "comparison-input-v1"
├─ artwork_id, title
├─ exam: topic, practical_type, work_category, exam_materials, time_limit_minutes,
│        paper_size, exam_conditions, memo
├─ intent: status(PROVIDED | NOT_PROVIDED), methods[], method_labels[], text, rule
├─ references[]: photo_id, role=REFERENCE, width, height, uploaded_at
├─ stages[]: stage_id, name, position, photos[] (role=ARTWORK, 올린 순서, is_representative)
└─ readiness: ready, missing[REFERENCE_PHOTO | ARTWORK_PHOTO]
```

- 이미지는 **id로만 참조**한다. Storage 경로나 URL은 입력에 넣지 않는다. v1.2 작업자가 호출 직전에 짧은 만료의 Signed URL이나 바이트로 바꾼다.
- 업로드가 끝난 사진(ACTIVE)만 포함한다. 단계는 작품의 단계 순서대로, 사진은 올린 순서대로 넣는다.
- `readiness.ready`가 false면 v1.2는 비교 첨삭을 시작하지 않고, 학생에게 빠진 사진을 안내한다.

## 3. 표현 의도 규칙 (AI가 의도를 짐작하지 않음)

| 상황 | 상태 | AI에 함께 보내는 규칙 |
| --- | --- | --- |
| 표현 방식이나 설명 중 하나라도 입력함 | `PROVIDED` | 밝힌 의도와 일치하는 변형은 형태 오류로 판단하지 않는다. 의도가 화면에서 충분히 전달되는지는 평가할 수 있다 |
| 둘 다 비어 있음(공백만 있는 경우 포함) | `NOT_PROVIDED` | 원본과 다른 점을 의도된 변형으로도, 형태 오류로도 단정하지 않는다. 판단이 갈리면 '추가 확인이 필요한 사항'으로 남긴다 |

규칙 문장은 코드 상수(`INTENT_PROVIDED_RULE`, `INTENT_NOT_PROVIDED_RULE`)로 고정했다. v1.2 프롬프트는 이 상수를 그대로 쓴다.

## 4. v1.2 출력 설계: `ComparisonResultDraft`

이 스키마는 **설계 전용**이다. v1.1에서는 응답하지도 저장하지도 않는다. v1.2에서 Structured Outputs 스키마의 기준으로 쓴다.

```text
ComparisonResultDraft
├─ input_version: "comparison-input-v1"
├─ stage_id (어느 단계 사진을 비교했는지, 없으면 작품 전체)
├─ findings[]
│   ├─ aspect: COMPOSITION | FORM | PROPORTION | VALUE | COLOR | TEXTURE | PERSPECTIVE | FINISH
│   ├─ observation (보이는 사실)
│   ├─ kind: STRENGTH | IMPROVEMENT_CANDIDATE | NEUTRAL
│   ├─ rationale, suggestion
│   ├─ related_intent (학생이 밝힌 의도와의 관계)
│   ├─ uncertainty: LOW | MEDIUM | HIGH
│   └─ evidence[] (photo_id, role, 설명)
├─ needs_confirmation[] (의도 확인이 필요한 사항)
└─ image_quality_notes[] (사진이 흐림, 잘림, 반사 등으로 판단이 어려운 경우)
```

- **점수 필드가 없다.** 합격 예측, 등급, 순위도 만들지 않는다. 기존 피드백(v0.9.9 태그)과 같은 "관찰 → 근거 → 제안" 형식을 쓴다.
- 개선점은 `IMPROVEMENT_CANDIDATE`, 즉 "후보"로만 표시한다. 최종 판단은 학생과 강사(오프라인)가 한다.
- 모든 판단에는 근거 사진(`evidence`)과 불확실성을 붙인다.

## 5. v1.2 구현 시 할 일 (v1.1 범위 밖)

1. **Claude Vision 호출 작업자**
   - 기존 AI 작업 큐(`ai_jobs`)에 비교 첨삭 작업 유형을 추가한다.
   - 기존 AI 처리 동의, 연령 정책, 학생 본인 요청 원칙을 따른다.
2. **이미지 전달**
   - ACTIVE 사진만, 긴 변을 줄여서 보낸다.
   - 위치 정보 등 메타데이터는 제거하고 보낸다. 원본 파일은 외부 서비스에 저장하지 않는다.
3. **결과 저장**
   - `ComparisonResultDraft`를 검증한 뒤 저장한다. 실패하면 재시도하고, 그래도 안 되면 학생에게 실패를 알린다.
   - 결과 화면은 v1.1의 원본 ↔ 작품 비교 화면 아래에 둔다.
4. **확장 지점**: 나중에 ArtCLIP 유사도, OpenCV 구도/명암 측정, 세그멘테이션, RAG(기출·우수작)를 붙인다면 아래처럼 연결한다.
   - 결과는 `ComparisonFinding.evidence`에 보조 근거로 넣는다.
   - 계산값은 `ComparisonInput`의 새 선택 필드로 넣고, 그때 `schema_version`을 올린다.
   - **v1.1과 v1.2 초기 범위에는 넣지 않는다.**
