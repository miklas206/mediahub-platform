param([ValidateSet('start','agent','agent-init','bootstrap-token','migrate','admin','test','lint','format','build')][string]$Task = 'start')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$pythonExe = Join-Path (Get-Location) '.venv\Scripts\python.exe'
switch ($Task) {
  'start' { & $pythonExe -m mediahub.cli serve }
  'agent' { & $pythonExe -m agent.main }
  'agent-init' { & $pythonExe -m mediahub.cli agent-init }
  'bootstrap-token' { & $pythonExe -m mediahub.cli bootstrap-token }
  'migrate' { & $pythonExe -m mediahub.cli migrate }
  'admin' { & $pythonExe -m mediahub.cli admin }
  'test' { & $pythonExe -m pytest; if ($LASTEXITCODE -eq 0) { pnpm --dir frontend test } }
  'lint' { & $pythonExe -m ruff check backend agent tests scripts; if ($LASTEXITCODE -eq 0) { pnpm --dir frontend lint; pnpm --dir frontend typecheck } }
  'format' { & $pythonExe -m ruff format backend agent tests scripts; pnpm --dir frontend format }
  'build' { pnpm --dir frontend build; if ($LASTEXITCODE -eq 0) { & $pythonExe -m build } }
}
exit $LASTEXITCODE
