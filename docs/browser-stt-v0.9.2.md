# v0.9.2 브라우저(기기) 음성 인식 — 설계·운영

> 작성: 2026-11-11 · 브랜치 `feature/v0.9.2-browser-stt`
> 관련: [stt-worker-github-actions.md](stt-worker-github-actions.md) (서버 처리, 대체 경로), [frontend-integration-v0.9.md](frontend-integration-v0.9.md) §3.2

목표: 40초 내외 한국어 첨삭 녹음을 학생 기기에서 바로 글로 바꿔 60초 안에 결과를 보여 준다. 월 STT 비용 0원 유지.
기존 faster-whisper + GitHub Actions 처리는 그대로 두고 **실패·미지원 시 대체 경로**로 쓴다. DB 변경 없음.

## 1. 흐름

```text
녹음 종료(또는 파일 선택)
 └ 기기 음성 인식 시작 (Web Worker, Transformers.js Whisper, 한국어 고정)   ← 저장 버튼을 누르기 전부터
     ├ 모델 준비: 처음 한 번 다운로드(진행률 표시) → 브라우저 Cache Storage에 저장
     └ 변환 → 구간(타임스탬프)별 문장
"저장하고 AI로 정리하기"
 ├ 녹음 업로드 (기존 Storage 정책 그대로)
 ├ 기기 변환이 끝날 때까지 최대 120초 대기
 ├ 성공 → POST …/transcript/browser {segments, device, model_name, auto_summarize}
 │        (대기 중인 서버 전사 작업은 취소, AI 동의가 있으면 요약 작업 생성)
 └ 실패·미지원·시간 초과·"서버에서 처리하기" → 기존 POST …/transcription (GitHub Actions)
이후: 전사 확인·수정(PUT …/transcript, 원본 보존) → AI 요약(Gemini) → 검토·확정 (기존과 같음)
```

작품 화면의 녹음 카드 "AI로 피드백 정리하기"도 같은 방식: 새 Signed URL로 음성을 받아 기기에서 변환 → 실패하면 서버 처리.

## 2. 모델·장치

| 조건 | 장치 | 모델 (onnx-community) | 정밀도 | 첫 다운로드 |
| --- | --- | --- | --- | --- |
| WebGPU 있음 (기본) | webgpu | whisper-base | 인코더 fp32 (shader-f16이면 fp16) + 디코더 q4 | 약 165~206MB |
| WebGPU 없음 | wasm | whisper-base | int8 (q8) | 약 77MB |
| `deviceMemory` ≤ 2GB | 위와 같음 | whisper-tiny | 〃 | 41~120MB |
| 사용자가 "정확하게" 선택 | 〃 | whisper-small | 〃 | 249~586MB |
| 사용자가 "사용 안 함" 선택 / Worker·WASM·오디오 디코딩 불가 | — | 서버 처리 | — | — |

- 라이브러리: `@huggingface/transformers` 4.3.2 (정확한 버전 고정), ONNX Runtime Web. 실행 파일(WASM)은 `cdn.jsdelivr.net`에서 받는다 (빌드 결과물에도 26.8MB 사본이 생기지만 실측에서는 CDN을 사용).
- 설정은 녹음 화면의 "기기 음성 인식" 선택(자동/빠르게/기본/정확하게/사용 안 함)이며 `localStorage`에 저장한다.
- 반복 환각(같은 문장 반복)·빈 결과는 실패로 보고 서버 처리로 넘긴다.

## 3. 개인정보

- 음성과 변환된 글은 기기 안에서만 처리된다. 실측(Chrome, 첫 실행) 결과 외부 요청은 `huggingface.co`·`us.aws.cdn.hf.co`(모델 파일)와 `cdn.jsdelivr.net`(ONNX Runtime) **GET 요청뿐**이었고 POST·분석·텔레메트리 요청은 없었다.
- 저장은 기존처럼 인증된 API로만: 학생 본인 녹음·녹음 동의 확인, 다른 사람 녹음 404.

## 4. 백엔드 API (추가)

`POST /api/v1/artworks/{artwork_id}/recordings/{recording_id}/transcript/browser` (학생 본인)

```json
{ "device": "webgpu", "model_name": "onnx-community/whisper-base", "language": "ko",
  "segments": [ { "start_ms": 0, "end_ms": 3500, "text": "구도는 안정적이야." } ],
  "processing_ms": 2100, "auto_summarize": true }
// → 201 { "transcript": TranscriptRead(origin: "BROWSER", engine: "browser-webgpu"), "summary_job": JobRead | null }
```

- 검증: 구간 1~2000개, 시작 시각 순, end ≥ start, 녹음 길이+5초 이내, 문장 1~1000자, 전체 길이 제한, 한국어만.
- 오류: 이미 전사됨 409 `TRANSCRIPTION_ALREADY_DONE`, 녹음 동의 없음 409 `RECORDING_CONSENT_REQUIRED`, 검증 실패 422, 다른 사람 녹음 404, 강사 계정 403.
- 전사 응답(`TranscriptMeta`/`TranscriptRead`)에 `origin` 추가: `SERVER` / `BROWSER` / `EDITED`. 저장 위치는 기존 `feedback_transcripts` (`engine = browser-webgpu|browser-wasm`, `model_name`).

### 중복 전사 방지 (GitHub Actions와)

- 저장 시 녹음 행 → 진행 중 전사 작업 순으로 잠그고, 전사가 없을 때만 저장하며 대기·진행 중 서버 작업을 `CANCELLED`(`BROWSER_TRANSCRIBED`)로 바꾼다.
- Worker는 결과를 저장하기 직전에 작업 행을 다시 잠그고 RUNNING인지 확인하므로, 취소된 작업의 결과는 버려진다. Worker가 먼저 저장했으면 브라우저 저장은 409 → 프론트는 요약만 요청한다.
- 테스트: `tests/db/test_browser_transcript.py` (두 순서의 경쟁 모두).

## 5. 성능 측정

측정 페이지: `/tools/stt-bench` (로그인 불필요, 파일을 기기 안에서만 변환). 휴대폰에서 이 페이지를 열어 직접 측정할 수 있다.
### 5.1 실측 (2026-11-11, 개발 PC: Windows, 4코어, 8GB, Chrome headless, 단일 스레드 WASM)

음성: Windows 한국어 TTS(Heami)로 만든 미술 첨삭 문장 20.9초·39.2초·60.9초 — **실제 학원 녹음이 아님**.
'전체' = 디코딩 + 모델 로드 + 변환 (저장 API 왕복 제외). 정확도 = 정답 대본 대비 글자 오류율(CER, 공백·문장부호 제외).

| 설정 | 상황 | 음성 | 모델 로드 | 변환 | 전체 | CER | Chrome 메모리(최대) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WebGPU base | 첫 실행(다운로드) | 20.9초 | 39.4초 | 19.3초 | **59.1초** | 4.4% | 2.2GB |
| WebGPU base | 모델 로드됨 | 39.2초 | 0 | 17.1초 | **17.2초** | 2.7% | 2.2GB |
| WebGPU base | 모델 로드됨 | 60.9초 | 0 | 29.4초 | **29.5초** | 5.9% | 2.3GB |
| WebGPU base | 브라우저 재시작(캐시) | 39.2초 | 8.8초 | 27.0초 | **36.5초** | 2.7% | 2.6GB |
| WASM base | 첫 실행(다운로드) | 20.9초 | 21.0초 | 11.2초 | **32.5초** | 2.9% | 1.2GB |
| WASM base | 모델 로드됨 | 39.2초 | 0 | 26.9초 | **27.1초** | 4.1% | 1.1GB |
| WASM base | 모델 로드됨 | 60.9초 | 0 | 44.8초 | **45.0초** | 7.7% | 1.1GB |
| WASM base | 브라우저 재시작(캐시) | 39.2초 | 9.1초 | 31.2초 | **41.0초** | 4.1% | 1.3GB |
| WASM tiny | 첫 실행(다운로드) | 20.9초 | 11.7초 | 8.6초 | **20.7초** | 16.2% | 1.1GB |
| WASM tiny | 모델 로드됨 | 39.2초 | 0 | 16.8초 | **17.0초** | 12.9% | 1.1GB |
| WASM tiny | 모델 로드됨 | 60.9초 | 0 | 22.8초 | **22.9초** | 18.6% | 1.1GB |
| WASM tiny | 브라우저 재시작(캐시) | 39.2초 | 4.7초 | 18.3초 | **23.3초** | 12.9% | 1.1GB |

- 측정한 12회 모두 60초 이내 (WebGPU 첫 실행 20초 음성은 59.1초로 경계). 다운로드 시간은 이 PC의 유선 인터넷 기준이며, 40초 음성의 **첫 실행**(다운로드 포함)은 측정하지 않았다 — WebGPU base는 다운로드만 39초라 60초를 넘을 가능성이 크다.
- 미술 용어(구도·소실점·투시·반사광·하이라이트·질감·채도·명도·원근감 등): base는 대부분 맞힘, '명암'을 '명함'으로 반복 오인식(서버 faster-whisper small도 같음) → 전사 수정 단계 필요. tiny는 오류가 많아(CER 13~19%) 기본값으로 쓰지 않는다.
- headless Chrome의 WebGPU는 어댑터 정보가 비어 있어 실제 GPU 사용 여부를 확인하지 못했다. 이 PC에서는 WebGPU가 WASM보다 변환은 빠르지만 첫 다운로드가 크다.
- 메모리는 테스트 Chrome 프로세스 전체의 작업 집합(Working Set) 최대값이다.

### 5.2 미측정

PC 실제 GPU(창 모드), **모바일 Chrome**, **iPhone Safari**, 저사양 기기, 모바일 데이터 환경 다운로드, 실제 학원 녹음 정확도, 브라우저 전사 → 저장 API → 요약까지의 실제 화면 흐름(로그인 상태). 휴대폰에서는 배포 후 `/tools/stt-bench`로 측정한다.

## 6. 한계

- 첫 사용 시 모델 다운로드(77MB~)가 필요하다. 모바일 데이터 환경에서는 오래 걸릴 수 있어 진행률과 "서버에서 처리하기"를 함께 보여 준다.
- 교차 출처 격리(COOP/COEP)를 켜지 않아 WASM은 단일 스레드로 동작한다 (Supabase Storage 이미지 등과 충돌 위험 때문에 이번에는 켜지 않음).
- 브라우저 탭이 백그라운드로 가거나 메모리가 부족하면 기기 변환이 중단될 수 있다 → 서버 처리로 대체.
- 기기 전사 결과는 학생 기기에서 만든 값이므로 서버 전사와 같은 검토·수정 단계를 거친다 (`origin`으로 구분).
