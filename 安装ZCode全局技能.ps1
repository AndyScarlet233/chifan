$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillSource = Join-Path $repoRoot ".zcode\skills\zlibrary-books\SKILL.md"
$scriptsSource = Join-Path $repoRoot "scripts"
$configSource = Join-Path $repoRoot "config.json"

$skillRoot = Join-Path $HOME ".zcode\skills\zlibrary-books"
$skillScripts = Join-Path $skillRoot "scripts"

New-Item -ItemType Directory -Force -Path $skillScripts | Out-Null

Copy-Item -Force $skillSource (Join-Path $skillRoot "SKILL.md")
Copy-Item -Force (Join-Path $scriptsSource "zlib_agent.py") (Join-Path $skillScripts "zlib_agent.py")
Copy-Item -Force (Join-Path $scriptsSource "zlib_cli.py") (Join-Path $skillScripts "zlib_cli.py")
Copy-Item -Force (Join-Path $scriptsSource "显示下载目录.py") (Join-Path $skillScripts "显示下载目录.py")
Copy-Item -Force $configSource (Join-Path $skillRoot "config.example.json")

$configDest = Join-Path $skillRoot "config.json"
if (-not (Test-Path $configDest)) {
    $cfg = Get-Content -Raw -Encoding UTF8 $configSource | ConvertFrom-Json
    $cfg.library_dir = Join-Path $HOME "Downloads"
    $cfg | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $configDest
    Write-Host "已创建本地配置，默认目录：$($cfg.library_dir)"
} else {
    Write-Host "检测到已有本地配置，已保留：$configDest"
}

Write-Host ""
Write-Host "ZCode 全局技能已安装/更新：$skillRoot"
Write-Host "请打开 ZCode -> 设置 -> 技能 -> 刷新，然后启用 zlibrary-books。"
Write-Host "账号凭据只保存在本机，不要提交或粘贴到聊天中。"
