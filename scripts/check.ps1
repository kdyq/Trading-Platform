param(
    [switch]$Install,
    [string]$Python = 'D:\python\virtual\fastapi-env\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendPath = Join-Path $projectRoot 'backend'
$frontendPath = Join-Path $projectRoot 'frontend'
$venvPython = $Python

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Python 环境不存在：$venvPython；请使用 -Python 指定环境路径。"
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
    Invoke-Checked { & $venvPython -m mypy app }
}
finally {
    Pop-Location
}

Push-Location $frontendPath
try {
    Invoke-Checked { pnpm typecheck }
    Invoke-Checked { pnpm lint }
    Invoke-Checked { pnpm format:check }
    Invoke-Checked { pnpm build }
}
finally {
    Pop-Location
}
