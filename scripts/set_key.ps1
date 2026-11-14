# Securely save an API key into .env (the key is never shown on screen).
# Works for Anthropic keys (sk-ant-...) and OpenRouter keys (sk-or-...).
$envPath = Join-Path $PSScriptRoot "..\.env"
$example = Join-Path $PSScriptRoot "..\.env.example"
if (-not (Test-Path $envPath)) { Copy-Item $example $envPath }

$secure = Read-Host "Paste your API key (it stays hidden), then press Enter" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

if ($key.StartsWith("sk-ant-") -and $key.Length -ge 30) { $name = "ANTHROPIC_API_KEY" }
elseif ($key.StartsWith("sk-or-") -and $key.Length -ge 30) { $name = "OPENROUTER_API_KEY" }
else {
    Write-Host "That doesn't look like an API key (expected sk-ant-... or sk-or-...). Nothing saved." -ForegroundColor Red
    exit 1
}

$lines = Get-Content $envPath | Where-Object { $_ -notmatch "^\s*$name\s*=" }
@("$name=$key") + $lines | Set-Content $envPath -Encoding ascii
Write-Host "Saved $name to .env. You can close this tab." -ForegroundColor Green
