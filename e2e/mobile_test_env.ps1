# v1.3 AI 수정본 휴대폰 검수 환경 (이 PC에서 실행, 운영 API·DB·Supabase·OpenAI 미사용)
#
# 준비: 로컬 PostgreSQL이 127.0.0.1:5432에서 실행 중 (postgres 사용자, 비밀번호 없음 또는 -Db로 지정),
#       backend: uv sync, frontend: npm ci
# 실행:  powershell -ExecutionPolicy Bypass -File e2e\mobile_test_env.ps1            (Wi-Fi 주소 자동)
#        powershell -ExecutionPolicy Bypass -File e2e\mobile_test_env.ps1 -Origin https://xxxx.trycloudflare.com
# 휴대폰: 같은 Wi-Fi에서 <Origin>/__test/ 열기
# 처음 한 번 Windows 방화벽이 python의 8020 포트 허용을 물으면 '개인 네트워크' 허용
param(
  [string]$Origin = "",
  [int]$Port = 8020,
  [string]$Db = "postgresql://postgres@127.0.0.1:5432/artmate_mobile",
  [string]$Work = "$PSScriptRoot\..\e2e-out\mobile",
  [switch]$Reset
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\.."
if (-not $Origin) {
  $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
      $_.InterfaceAlias -like "Wi-Fi*" -and $_.IPAddress -notlike "169.254*" } | Select-Object -First 1).IPAddress
  if (-not $ip) { throw "Wi-Fi IPv4 주소를 찾지 못했습니다. -Origin 으로 지정하세요" }
  $Origin = "http://${ip}:$Port"
}
New-Item -ItemType Directory -Force "$Work" | Out-Null
$dist = Join-Path $Work "dist"
$data = Join-Path $Work "storage"
if ($Reset -and (Test-Path $data)) { Remove-Item -Recurse -Force $data }

# 1) 테스트 DB 스키마 (0017까지). -Reset이면 DB를 비우고 다시 만든다 (테스트 DB만)
Push-Location "$root\backend"
$env:ENV_FILE = ""; $env:APP_ENV = "test"; $env:DATABASE_URL = $Db
if ($Reset) { uv run alembic downgrade base }
uv run alembic upgrade head
Remove-Item Env:DATABASE_URL, Env:APP_ENV, Env:ENV_FILE
Pop-Location

# 2) 이 서버 주소로 프론트엔드 빌드 (같은 커밋)
Push-Location "$root\frontend"
$env:VITE_SUPABASE_URL = "$Origin/__sb"; $env:VITE_SUPABASE_ANON_KEY = "mobile-test-anon"; $env:VITE_API_BASE_URL = $Origin
npx vite build --outDir "$dist" --emptyOutDir
Remove-Item Env:VITE_SUPABASE_URL, Env:VITE_SUPABASE_ANON_KEY, Env:VITE_API_BASE_URL
Pop-Location

# 3) 서버 (OpenAI 키를 넘기지 않는다)
Push-Location "$root\backend"
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
Write-Host "휴대폰에서 열기: $Origin/__test/"
uv run python -X utf8 ..\e2e\mobile_test_server.py --origin $Origin --port $Port --db $Db --dist $dist --data $data
Pop-Location
