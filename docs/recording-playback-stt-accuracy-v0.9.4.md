# v0.9.4 녹음 재생 무음·STT 정확도 — 조사·수정·모델 비교

> 작성: 2026-11-12 · 브랜치 `fix/recording-playback-stt-accuracy` (main = PR #49 병합 후)
> 관련: [stt-stability-v0.9.3.md](stt-stability-v0.9.3.md), [browser-stt-v0.9.2.md](browser-stt-v0.9.2.md)

## 1. 녹음 재생 오류 조사

### 1.1 확인한 것 (근거)

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| 녹음 코드 경로 (PC Chrome) | **정상** — 앱과 같은 설정(형식 우선순위, 64kbps, 1초 청크)으로 6초 녹음: `audio/webm;codecs=opus`, 45,545바이트, 청크 6개, 디코딩 6.0초·48kHz·mono, **RMS −15.9dBFS, 피크 1.03, 소리 구간 75%**, `<audio>` 재생 진행 확인 | headless Chrome 157 + 가짜 마이크에 한국어 TTS 음성 입력 |
| 마이크 설정 | echoCancellation·noiseSuppression·autoGainControl 모두 켜짐 (브라우저 기본값) | `track.getSettings()` |
| WebM 길이 정보 | `<audio>.duration`이 없음(Infinity) — MediaRecorder WebM의 알려진 특성. 앱은 저장된 `duration_ms`를 쓰므로 재생에는 영향 없음 | 위 측정 |
| 업로드 원본 vs 저장 파일 | 서버가 업로드 완료 시 Storage에서 파일을 다시 받아 헤더(형식)를 검사하고 SHA-256을 저장 → 저장 파일 = 업로드 원본. 헤더가 맞지 않으면 저장 거부 | `RecordingService.complete_upload`, `inspect_audio` |
| 재생 실패 표시 | **없었음** — `<audio>` 오류는 URL 한 번 재발급 후 조용히 끝나고, `play()` 실패도 표시하지 않음 → 사용자에게는 "소리가 안 남"으로만 보임 | `RecordingPlayer.jsx` (수정 전) |
| 무음 녹음 감지 | **없었음** — 마이크에서 소리가 들어오지 않아도 그대로 저장·변환 | `useAudioRecorder.js` (수정 전) |

### 1.2 확인하지 못한 것 (실제 원인 확정에 필요)

- **실제로 소리가 안 나는 녹음 파일**과 그 녹음을 만든 기기·브라우저 — 운영 Storage의 학생 녹음은 개인정보라 열어 보지 않았다.
- Android Chrome·iPhone Safari 실기기의 녹음·재생.
- iPhone Safari에서 Chrome이 만든 WebM(Opus) 재생 가능 여부 (OS 버전별 차이 가능).

→ PC 녹음 경로가 정상이므로 **원인은 실제 기기의 마이크 입력(다른 앱 점유·가림·권한·선택된 장치) 또는 기기별 형식 호환일 가능성이 크다.** 이번 수정으로 앱이 원인을 화면에 보여 준다 (아래). 문제 녹음 1개를 받으면 `/tools/stt-bench`(기기 안에서만 처리)로 신호를 바로 확인할 수 있다.

### 1.3 수정

- **녹음 중 마이크 입력 감시**: Web Audio로 레벨만 읽음(녹음 내용 변경 없음). 4초 넘게 소리가 없으면 "마이크 소리가 들어오지 않아요" 경고. iOS에서 오디오 처리가 정지 상태면 측정하지 않음(오경보 방지).
- **저장 전 신호 검사**: 녹음 = 실시간 통계, 파일 = 디코딩(5분 이하).
  - 거의 무음: 경고 + "저장하고 AI로 정리하기" 숨김 (녹음만 저장 가능, 환각 대본을 만들지 않음)
  - 소리 작음: "휴대폰을 가까이" 안내
- **재생 오류 표시**: 새 URL로도 실패하면 이유(네트워크/파일 손상/이 브라우저에서 재생 불가 형식 + 형식 이름)를 표시, `play()` 거부도 표시.
- **iPhone·Mac Safari는 mp4(AAC)로 녹음** (Safari 기본 형식, 다른 브라우저에서도 재생 가능). Chrome·Android·iOS Chrome은 기존대로 WebM(Opus).
- 기존 녹음은 삭제·덮어쓰기 하지 않음.

## 2. STT 정확도

### 2.1 원인 분석

| 원인 | 설명 | 조치 |
| --- | --- | --- |
| **녹음 신호가 없거나 약함** | Whisper는 무음·잡음에서 "시청해 주셔서 감사합니다" 같은 문장을 만들어 낸다. 재생 무음 문제와 같은 녹음이라면 대본이 엉망인 것이 당연하다 | 무음 경고·무음 녹음 변환 안 함 (§1.3) |
| **브라우저 STT에 무음 제거가 없음** | 서버 faster-whisper는 `vad_filter=True`인데 브라우저는 모든 구간을 Whisper에 넣었다 | 거의 무음인 구간은 건너뜀 (`skippedChunks`로 기록) + 알려진 환각 문구 제거 |
| 모델 크기 (base) | TTS 기준 CER 3~6%(v0.9.3 실측), "명암→명함" 같은 용어 오류. 실제 교실 녹음(거리·잡음·여러 사람)은 더 나쁠 것 | 더 큰 모델 비교 (§3) |
| 28초 구간 분할 | 겹침 없이 가장 조용한 100ms에서 자름. 단위 테스트로 빈틈·겹침 없음 확인 | 이번 PR에서 변경 없음. 실제 녹음으로 경계 누락 여부 확인 필요 |
| 16kHz 변환 | 브라우저 OfflineAudioContext 리샘플(표준) | 문제 근거 없음 |

**모델 교체로 해결 가능한 문제와 녹음 품질 문제는 다르다**: 신호가 없거나 아주 약한 녹음은 어떤 모델도 맞게 받아쓸 수 없다. 먼저 신호 검사로 녹음 품질 문제를 걸러 내고, 정상 녹음에서의 오류율로 모델을 고른다.

### 2.2 실측 / 미측정

- 실측 (TTS 음성, PC Chrome, 브라우저 Whisper base WASM — v0.9.3): 19.7초 CER 3.1%, 40.7초 5.6%, 61.7초 4.4%.
- **미측정**: 실제 한국어 첨삭 녹음 전부, 서버 faster-whisper small(이 PC 메모리 부족·모델 미캐시로 실행 안 함), Groq·OpenAI(승인 전 호출 금지).

## 3. 모델 비교 도구

- 브라우저 Whisper base: `/tools/stt-bench` — 파일 + 정답 대본을 넣으면 신호 진단, CER, 미술 용어 정확도, 단계별 시간 (기기 밖으로 보내지 않음).
- 서버·외부: `backend/scripts/stt_compare.py`
  ```bash
  cd backend && uv sync --extra stt
  # 정답 대본: 녹음 파일 옆 <파일이름>.txt
  uv run python -m scripts.stt_compare lesson1.m4a --engines local-small
  # 외부: 녹음 당사자 동의 + 운영자 승인 후에만
  GROQ_API_KEY=… OPENAI_API_KEY=… uv run python -m scripts.stt_compare lesson1.m4a \
    --engines local-small,groq-large-v3,groq-large-v3-turbo,openai-transcribe --allow-external
  ```
  `--allow-external`과 키가 둘 다 없으면 외부 엔진은 호출하지 않고 `skipped`로 표시한다 (테스트로 확인). 두 도구의 CER·용어 기준은 같다 (`sttMetrics.js` / `app/services/stt_metrics.py`).

### 3.1 비교표 (측정값이 없는 칸은 공개 자료 기준이며 확인 필요)

| 모델 | 정확도 | 처리 위치·속도 | 5분 녹음 | 비용 | 개인정보 |
| --- | --- | --- | --- | --- | --- |
| 브라우저 Whisper base | TTS CER 3~6% (실측). 실제 녹음 미측정 | 기기. PC WASM 약 1배속 (실측) | 휴대폰에서 수 분 | 0 | 기기 밖으로 안 나감 |
| 서버 faster-whisper small | base보다 좋을 것으로 예상, 미측정 | GitHub Actions(무료), 시작 지연 있음 | 대기열에 따라 다름 | 0 | GitHub 러너에서 처리 |
| Groq Whisper Large V3 | 미측정 (Whisper 중 가장 큰 다국어 모델) | 외부 API, 공개 자료상 매우 빠름 | 파일 1회 요청 | 시간당 약 $0.111 | **외부 전송**, 무료 등급 한도·데이터 조건 확인 필요 |
| Groq Whisper Large V3 Turbo | 미측정 (large-v3 경량판, 대체로 조금 낮음) | 〃 더 빠름 | 〃 | 시간당 약 $0.04 | 〃 |
| OpenAI gpt-4o-transcribe | 미측정 | 외부 API | 〃 | 분당 약 $0.006 (시간당 $0.36) | **외부 전송**, API 데이터 처리 조건 확인 필요 |

### 3.2 예상 운영 비용 (가정: 월 5분 녹음 1,000건 = 약 83시간)

| 모델 | 월 비용 (공개 가격 기준) |
| --- | --- |
| 브라우저 base / 서버 small | 0원 |
| Groq Large V3 Turbo | 약 $3.3 |
| Groq Large V3 | 약 $9.3 |
| OpenAI gpt-4o-transcribe | 약 $30 |

Groq 무료 등급은 공개 자료상 하루 2,000건·시간당 음성 7,200초 수준이라 위 사용량을 감당할 수 있어 보이나, 수치가 출처마다 다르고 무료 등급의 데이터 처리 조건을 확인해야 한다.

### 3.3 추천

1. **지금(승인 없이)**: 이번 PR의 녹음 신호 검사·무음 구간 건너뛰기·환각 제거 적용 → 실제 녹음 2~3개(20초·1분·5분)로 브라우저 base와 서버 small을 비교 도구로 측정.
2. **정확도 우선 추천 후보: Groq Whisper Large V3** (비용이 낮고 큰 모델) — 단, 실제 녹음 비교로 확인하고, 아래가 갖춰진 뒤에만:
   - 녹음 음성의 외부 전송에 대한 동의서·개인정보 처리방침 갱신 (현재 동의는 Gemini 텍스트 요약용)
   - 키는 백엔드(Worker)에만, 실패 시 기존 경로(브라우저/서버 small)로 대체, 원본·작업 상태 보존
3. 외부 API는 승인 전까지 운영 서비스에 적용하지 않는다 (이번 PR에도 적용하지 않음).
