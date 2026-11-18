
$ErrorActionPreference = "Continue"

Write-Host "`n===== TRANSLATE APP - GIT CHECK =====" -ForegroundColor Cyan

function Check($name, $condition) {
    if ($condition) {
        Write-Host "[OK] $name" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] $name" -ForegroundColor Red
    }
}

Check "Git installed" ([bool](Get-Command git -ErrorAction SilentlyContinue))

if (-not (Test-Path ".git")) {
    Write-Host "[ERROR] Not inside Git repository" -ForegroundColor Red
    exit
}

$remote = git remote get-url origin 2>$null
$branch = git branch --show-current
$upstream = git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
$user = git config user.name
$email = git config user.email
$status = git status --porcelain

Check "Correct GitHub repository" ($remote -eq "https://github.com/Kaloqnaladinov/translate_app.git")
Check "Main branch" ($branch -eq "main")
Check "Upstream configured" ($upstream -eq "origin/main")
Check "Git username configured" (![string]::IsNullOrWhiteSpace($user))
Check "Git email configured" (![string]::IsNullOrWhiteSpace($email))
Check "Working tree clean" ($status.Count -eq 0)

Write-Host "`nRepository: $remote"
Write-Host "Branch: $branch"
Write-Host "Upstream: $upstream"
Write-Host "User: $user"
Write-Host "Email: $email"

Write-Host "`n===== END OF CHECK =====" -ForegroundColor Cyan
