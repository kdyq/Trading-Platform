param(
    [switch]$Install,
    [switch]$Postgres
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$venvPython = 'D:\python\virtual\fastapi-env\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "固定 Python 环境不存在：$venvPython"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "检查命令失败，退出码：$LASTEXITCODE"
    }
}

if ($Install) {
    Push-Location $backendPath
    try {
        Invoke-Checked { & $venvPython -m pip install --disable-pip-version-check -r requirements-dev.txt }
    }
    finally {
        Pop-Location
    }

    Push-Location $frontendPath
    try {
        Invoke-Checked { pnpm install --frozen-lockfile }
    }
    finally {
        Pop-Location
    }
}

Push-Location $backendPath
try {
    Invoke-Checked { & $venvPython -m ruff format --check . }
    Invoke-Checked { & $venvPython -m ruff check . }
    Invoke-Checked { & $venvPython -m mypy app tests }
    Invoke-Checked { & $venvPython -m pytest }
}
finally {
    Pop-Location
}

if ($Postgres) {
    Push-Location $backendPath
    try {
        Invoke-Checked { & $venvPython 'scripts/postgres_gate.py' }
    }
    finally {
        Pop-Location
    }
}

Push-Location $frontendPath
try {
    Invoke-Checked { pnpm typecheck }
    Invoke-Checked { pnpm lint }
    Invoke-Checked { pnpm format:check }
    Invoke-Checked { pnpm test }
    Invoke-Checked { pnpm build }
}
finally {
    Pop-Location
}
