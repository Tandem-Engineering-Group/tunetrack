<#
  TuneTrack - create the Teams/SharePoint data folder tree.

  Run this on the machine where the "Track Tune" Teams library is synced.
  It auto-detects the library folder (the name may differ slightly), creates the
  standard tree, seeds one example run folder with placeholder files, and copies
  the reference docs into 07_Project Docs.

  Usage:
    powershell -ExecutionPolicy Bypass -File tools\setup_teams_folders.ps1
    # or pass paths explicitly:
    powershell -File tools\setup_teams_folders.ps1 -Tgcs "C:\Users\RL.Admin\TGCS" -RepoPath "C:\011 TuneTrack\tunetrack"

  This NEVER touches the PCM and writes no data into the git repo.
#>
param(
  [string]$Tgcs     = "$env:USERPROFILE\TGCS",
  [string]$RepoPath = "C:\011 TuneTrack\tunetrack"
)

Write-Host "Looking for the Track Tune library under: $Tgcs"
if (-not (Test-Path $Tgcs)) {
  Write-Error "TGCS folder not found at '$Tgcs'. Re-run with -Tgcs '<correct path>'."
  exit 1
}

Write-Host "Folders currently under ${Tgcs}:"
Get-ChildItem -Path $Tgcs -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }

$lib = Get-ChildItem -Path $Tgcs -Directory | Where-Object { $_.Name -like 'Track Tune*' } | Select-Object -First 1
if (-not $lib) {
  Write-Error "No 'Track Tune*' folder found under $Tgcs. Confirm the synced library name and pass -Tgcs."
  exit 1
}
$root = $lib.FullName
Write-Host ""
Write-Host "Using library: $root" -ForegroundColor Green

$folders = @(
  "01_Inbox", "02_Runs", "03_Reports", "04_Build and Tuning",
  "05_Maintenance", "06_Season 2026", "07_Project Docs", "08_Archive"
)
foreach ($f in $folders) {
  New-Item -ItemType Directory -Force -Path (Join-Path $root $f) | Out-Null
  Write-Host "  [dir]  $f"
}

# One example run folder so the per-event shape is obvious.
$run = Join-Path $root "02_Runs\2026-07-11_GrandBend"
New-Item -ItemType Directory -Force -Path $run | Out-Null
foreach ($file in @("vcm_log.csv", "timeslip.jpg", "dragy.csv", "kestrel.csv", "tire_track.txt", "video.mp4")) {
  $fp = Join-Path $run $file
  if (-not (Test-Path $fp)) { New-Item -ItemType File -Force -Path $fp | Out-Null }
}
Write-Host "  [run]  02_Runs\2026-07-11_GrandBend  (empty placeholders: vcm_log.csv, timeslip.jpg, dragy.csv, kestrel.csv, tire_track.txt, video.mp4)"

# Copy reference docs into 07_Project Docs (if the repo is present).
$docs = Join-Path $root "07_Project Docs"
foreach ($doc in @("CLAUDE.md", "HANDOFF.md", "TEAMS_DATA_SETUP.md", "README.md")) {
  $src = Join-Path $RepoPath $doc
  if (Test-Path $src) {
    Copy-Item $src -Destination $docs -Force
    Write-Host "  [doc]  copied $doc -> 07_Project Docs"
  }
}

Write-Host ""
Write-Host "Done. Next, in the repo ($RepoPath):" -ForegroundColor Cyan
Write-Host "  1) Copy config.example.yaml to config.yaml"
Write-Host "  2) Set these paths in config.yaml (forward slashes are fine):"
Write-Host "       inbox_dir:   $root/01_Inbox"
Write-Host "       runs_dir:    $root/02_Runs"
Write-Host "       reports_dir: $root/03_Reports"
Write-Host "  3) Drop a VCM CSV in 01_Inbox and run:  python src\ingest.py --inbox"
