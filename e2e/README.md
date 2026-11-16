# 운영 사이트 실사용 점검 (`prod_smoke.py`)

실제 브라우저(Playwright Chromium)로 운영 사이트에 로그인하고, **그 브라우저 세션 토큰으로 운영 API·Storage를 그대로 호출**한다. Mock이 없으므로 PASS는 운영에서 실제로 동작했다는 뜻이다.

```bash
pip install playwright && python -m playwright install chromium   # 처음 한 번

# PowerShell
$env:ARTMATE_STUDENT_EMAIL="..."; $env:ARTMATE_STUDENT_PASSWORD="..."
$env:ARTMATE_INSTRUCTOR_EMAIL="..."; $env:ARTMATE_INSTRUCTOR_PASSWORD="..."   # 선택

python -X utf8 e2e/prod_smoke.py --out e2e-out                       # 읽기 전용
python -X utf8 e2e/prod_smoke.py --write --out e2e-out               # 테스트 작품 생성→사진→첨삭→삭제
python -X utf8 e2e/prod_smoke.py --write --stt --audio sample.wav    # + 서버 STT 소요 시간 측정
python -X utf8 e2e/prod_smoke.py --write --stt --summary --audio sample.wav   # + AI 요약 (운영에서 켜진 경우)
```

| 모드 | 운영에 남는 것 |
| --- | --- |
| 기본 | 없음 (로그인·조회만) |
| `--write` | 없음 — `[E2E] 운영 점검 …` 작품을 만들고 끝에 삭제 (`--keep`이면 남김) |
| `--stt` | 위와 같음. 녹음 동의는 **앱에서 테스트 계정으로 미리** 해 둬야 한다 (스크립트가 대신 동의하지 않음) |
| `--summary` | 실제 OpenAI 호출 1건 (과금) |

- 테스트 전용 계정만 사용한다. 실제 학생 계정으로 `--write`를 실행하지 않는다.
- 강사 화면은 그 강사가 속한 학원(academy)과 학생 소속이 있어야 학생 작품이 보인다.
- 결과: 콘솔 `[PASS]/[FAIL]/[SKIP]`, `--out` 폴더에 스크린샷과 `results.json`.
