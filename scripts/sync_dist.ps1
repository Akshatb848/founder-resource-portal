# Copy source static assets to dist/, the only folder the portal API serves.
# Then stamp every script and stylesheet link in the dist pages with a fingerprint of that file's contents
# (?v=<8 hex>), so a changed file always gets a new address and browsers can never keep running an old copy.
$root = Split-Path $PSScriptRoot -Parent
$files = @(
  "index.html", "app.js", "phase1-features.js", "phase1.css", "styles.css",
  "api-integration.js", "app-api-wiring.js", "app-api-engagement.js", "user-journey.js", "analyst.html", "workspace.js", "app-api-alpha.js", "app-api-talent.js", "app-api-onboard.js", "app-api-course.js", "careers.html", "careers.js", "careers.css", "boot.js",
  "company-profile.js", "company-profile.css", "app-api-company.js", "chat.js", "chat.css", "app-api-messages.js"
)
foreach ($f in $files) {
  Copy-Item (Join-Path $root $f) (Join-Path $root "dist\$f") -Force
}

$dist = Join-Path $root "dist"
$sha = [System.Security.Cryptography.SHA256]::Create()
$fingerprint = @{}
foreach ($f in $files | Where-Object { $_ -match '\.(js|css)$' }) {
  # Line endings are normalised first, so Windows (CRLF) and Linux (LF) checkouts give the same fingerprint.
  $text = [IO.File]::ReadAllText((Join-Path $dist $f)).Replace("`r`n", "`n")
  $bytes = [Text.Encoding]::UTF8.GetBytes($text)
  $fingerprint[$f] = -join ($sha.ComputeHash($bytes)[0..3] | ForEach-Object { $_.ToString("x2") })
}
$pattern = '(?<attr>src|href)="(?<file>[A-Za-z0-9_.\-]+\.(js|css))(\?v=[^"]*)?"'
foreach ($page in $files | Where-Object { $_ -match '\.html$' }) {
  $path = Join-Path $dist $page
  $html = [IO.File]::ReadAllText($path)
  $stamped = [regex]::Replace($html, $pattern, {
    param($m)
    $name = $m.Groups["file"].Value
    if ($fingerprint.ContainsKey($name)) { "$($m.Groups['attr'].Value)=""$name`?v=$($fingerprint[$name])""" } else { $m.Value }
  })
  [IO.File]::WriteAllText($path, $stamped, (New-Object System.Text.UTF8Encoding($false)))
}
Write-Host "Synced $($files.Count) files to dist/ (asset links fingerprinted)"
