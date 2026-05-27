<#
  preflight.ps1 -- Verify every command in DEMO_SCRIPT.md / DEMO.md works
                  BEFORE you hit record. All 6 checks must PASS.

  Usage:
    pwsh scripts/preflight.ps1           # Run all checks
    pwsh scripts/preflight.ps1 -Check 3  # Run a single check by number

  Exit code: 0 if all PASS, 1 otherwise.
#>

[CmdletBinding()]
param(
  [int]$Check = 0  # 0 = all
)

$ErrorActionPreference = 'Continue'
$script:Pass = 0
$script:Fail = 0
$script:FailMessages = @()

# ---------- helpers ----------------------------------------------------------

function Write-Header($n, $title) {
  Write-Host ""
  Write-Host ("=" * 70) -ForegroundColor DarkGray
  Write-Host (" Check {0}: {1}" -f $n, $title) -ForegroundColor Cyan
  Write-Host ("=" * 70) -ForegroundColor DarkGray
}

function Write-Pass($msg) {
  Write-Host ("  [PASS] " + $msg) -ForegroundColor Green
  $script:Pass++
}

function Write-Fail($checkNum, $msg, $remedy) {
  Write-Host ("  [FAIL] " + $msg) -ForegroundColor Red
  Write-Host ("         Fix: " + $remedy) -ForegroundColor Yellow
  $script:Fail++
  $script:FailMessages += "Check $checkNum`: $msg  ->  $remedy"
}

function Should-Run($n) {
  return ($Check -eq 0) -or ($Check -eq $n)
}

# Activate venv + env
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$activate = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $activate) {
  . $activate
} else {
  Write-Host "WARNING: .venv not found at $activate. Assuming p4opt is on PATH." -ForegroundColor Yellow
}
$env:PYTHONIOENCODING = "utf-8"

Write-Host ""
Write-Host "P4CIOptimizer demo pre-flight" -ForegroundColor White -BackgroundColor DarkBlue
Write-Host ("Repo: " + $repoRoot)
Write-Host ("Time: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))

# ---------- Check 1: p4opt select --explain (Python sample) -----------------

if (Should-Run 1) {
  Write-Header 1 "p4opt select --explain on sample_project/src/auth.py"

  $out = & p4opt select --files src/auth.py --project sample_project --explain 2>&1 | Out-String
  Write-Host $out -ForegroundColor DarkGray

  # Rich wraps the long "Why" column across lines and inserts U+2502 vertical bar separators.
  # Strip box-drawing chars (U+2500-U+257F) first, then collapse whitespace.
  # Using \u escapes so the .ps1 stays pure ASCII (PS 5.1 mangles non-ASCII without a BOM).
  $flat = ($out -replace '[\u2500-\u257F]', ' ') -replace '\s+', ' '

  $hasTestAuth   = $flat -match "test_auth\.py"
  $hasPathMatch  = $flat -match "path match"
  $hasHistory    = $flat -match "historical correlation"
  $hasImport     = $flat -match "imports changed module"

  if ($hasTestAuth -and $hasPathMatch -and $hasHistory -and $hasImport) {
    Write-Pass "test_auth.py selected with all 3 signals (path + history + import)"
  } else {
    $missing = @()
    if (-not $hasTestAuth)  { $missing += "test_auth.py not selected" }
    if (-not $hasPathMatch) { $missing += "no 'path match' reason" }
    if (-not $hasHistory)   { $missing += "no 'historical correlation' reason -- need to seed?" }
    if (-not $hasImport)    { $missing += "no 'imports changed module' reason -- import graph broken?" }
    Write-Fail 1 ("Missing: " + ($missing -join '; ')) `
      "Run 'p4opt seed --project sample_project' to populate history; verify src/auth.py imports are intact"
  }
}

# ---------- Check 2: p4opt seed populates the DB ----------------------------

if (Should-Run 2) {
  Write-Header 2 "p4opt seed --project sample_project (populates Test Health history)"

  $out = & p4opt seed --project sample_project 2>&1 | Out-String
  Write-Host $out -ForegroundColor DarkGray

  $db = Join-Path $repoRoot "sample_project\p4opt.db"
  if (Test-Path $db) {
    $sizeKb = [math]::Round((Get-Item $db).Length / 1024, 1)
    if ($sizeKb -gt 5) {
      Write-Pass ("DB present at sample_project\p4opt.db ({0} KB)" -f $sizeKb)
    } else {
      Write-Fail 2 ("DB exists but tiny ({0} KB) -- likely empty" -f $sizeKb) `
        "Re-run with --days 60 if available; check 'p4opt seed --help'"
    }
  } else {
    Write-Fail 2 "sample_project\p4opt.db does not exist after seed" `
      "Check 'p4opt seed' actually ran (look for tracebacks above)"
  }
}

# ---------- Check 3: Java Scenario A -- ReviewNotifier (1 test, 96%) ---------

if (Should-Run 3) {
  Write-Header 3 "Java Scenario A -- ReviewNotifier.java cleanup (expect: 1 test, ~96%)"

  $plugin = Join-Path $repoRoot "p4_plugin_demo"
  if (-not (Test-Path $plugin)) {
    Write-Fail 3 "p4_plugin_demo/ not found" `
      "git clone --depth 100 https://github.com/jenkinsci/p4-plugin.git p4_plugin_demo"
  } else {
    $out = & p4opt ci --vcs git --project p4_plugin_demo `
      --from "b10b3824a~1" --to "b10b3824a" `
      --dry-run --baseline-s 3500 2>&1 | Out-String
    Write-Host $out -ForegroundColor DarkGray

    if ($out -match "Smart subset \(projected\):\s*1 test") {
      if ($out -match "9[5-9]%|100%") {
        Write-Pass "1 test selected; savings >= 95%"
      } else {
        Write-Fail 3 "1 test selected but savings < 95%" `
          "Verify --baseline-s 3500 was passed; check selector output for unexpected matches"
      }
    } else {
      Write-Fail 3 "Expected '1 test files', got something else" `
        "Verify SHA b10b3824a is present in p4_plugin_demo (git -C p4_plugin_demo show b10b3824a)"
    }
  }
}

# ---------- Check 4: Java Scenario B -- PerforceScm (21 of 23) ---------------

if (Should-Run 4) {
  Write-Header 4 "Java Scenario B -- PerforceScm.java change (expect: 21 of 23, ~9%)"

  $plugin = Join-Path $repoRoot "p4_plugin_demo"
  if (-not (Test-Path $plugin)) {
    Write-Fail 4 "p4_plugin_demo/ not found" "(see Check 3 fix)"
  } else {
    $out = & p4opt ci --vcs git --project p4_plugin_demo `
      --from "0ea4b93a4~1" --to "0ea4b93a4" `
      --dry-run --baseline-s 3500 2>&1 | Out-String
    Write-Host $out -ForegroundColor DarkGray

    if ($out -match "Smart subset \(projected\):\s*2[01] test") {
      if ($out -match "\b([0-9]|1[0-5])%") {
        Write-Pass "20-21 tests selected; savings <= 15% (honesty pitch lands)"
      } else {
        Write-Fail 4 "21 tests selected but savings > 15% -- math is off" `
          "Verify --baseline-s 3500 and that 23 total tests are discovered"
      }
    } else {
      Write-Fail 4 "Expected '21 test files' (or 20), got something else" `
        "Verify SHA 0ea4b93a4 is present and PerforceScm.java is central enough"
    }
  }
}

# ---------- Check 5: Streamlit dashboard reachable --------------------------

if (Should-Run 5) {
  Write-Header 5 "Streamlit dashboard prerequisites (streamlit + plotly importable, app.py loads)"

  # Verify the dashboard's Python deps import. The actual launch is a manual demo step;
  # this check just rules out the most common failure: missing deps.
  $probe = & python -c "import streamlit, plotly; import p4opt.dashboard.app; print('OK')" 2>&1 | Out-String
  if ($probe -match "OK") {
    Write-Pass "streamlit + plotly + p4opt.dashboard.app all import cleanly"
    Write-Host "  Note: actual dashboard launch is a manual step (see recording-guide.md Section B)." -ForegroundColor DarkGray
  } else {
    Write-Host $probe -ForegroundColor DarkGray
    Write-Fail 5 "Dashboard imports failed" `
      "Run 'pip install streamlit plotly' or 'pip install -e .[dashboard]'"
  }

  # Bonus: if a dashboard is already running, confirm it
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:8501/_stcore/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    if ($r.StatusCode -eq 200) {
      Write-Host "  Bonus: a dashboard instance is already running on :8501." -ForegroundColor DarkGray
    }
  } catch {
    # not running; that's fine, user starts it manually before recording
  }
}

# ---------- Check 6: GitHub URLs reachable ----------------------------------

if (Should-Run 6) {
  Write-Header 6 "GitHub demo URLs return 200"

  $urls = @(
    @{ Url = "https://github.com/p4chirag/click_demo/pull/1";                                  Label = "Click demo PR" },
    @{ Url = "https://github.com/p4chirag/click_demo/actions/runs/26436674912";                Label = "Workflow run page" }
  )

  foreach ($u in $urls) {
    try {
      $r = Invoke-WebRequest -Uri $u.Url -Method Head -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
      if ($r.StatusCode -eq 200) {
        Write-Pass ("{0} -> 200 OK" -f $u.Label)
      } else {
        Write-Fail 6 ("{0} -> HTTP {1}" -f $u.Label, $r.StatusCode) `
          "Page exists but unexpected status; open manually to inspect"
      }
    } catch {
      Write-Fail 6 ("{0} -> unreachable: {1}" -f $u.Label, $_.Exception.Message) `
        "Check internet; for Section 4 fallback, pre-screenshot the page (see DEMO.md backup plans)"
    }
  }
}

# ---------- Summary ---------------------------------------------------------

Write-Host ""
Write-Host ("=" * 70) -ForegroundColor DarkGray
$summaryColor = if ($script:Fail -gt 0) { 'Red' } else { 'Green' }
Write-Host (" Pre-flight summary: {0} pass, {1} fail" -f $script:Pass, $script:Fail) -ForegroundColor $summaryColor
Write-Host ("=" * 70) -ForegroundColor DarkGray

if ($script:Fail -gt 0) {
  Write-Host ""
  Write-Host "Failures to fix before recording:" -ForegroundColor Yellow
  foreach ($m in $script:FailMessages) {
    Write-Host ("  - " + $m) -ForegroundColor Yellow
  }
  exit 1
}

Write-Host ""
Write-Host "All checks PASS. You are clear to record." -ForegroundColor Green
exit 0
