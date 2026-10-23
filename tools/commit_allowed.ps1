param([string]$Message='GERNZE 1.1.1: desktop memory review, sync fixes and opening version')
$ErrorActionPreference='Stop'
# Decode Git's UTF-8 paths consistently in Windows PowerShell and PowerShell.
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Console]::OutputEncoding
$projectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$manifest=Get-Content -LiteralPath (Join-Path $projectRoot 'source-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$allowed=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach($entry in $manifest.files){[void]$allowed.Add($entry)}
$gitDirectory=(& git rev-parse --absolute-git-dir).Trim()
if($LASTEXITCODE -ne 0){throw 'Current directory is not the project repository'}
$tracked=(& git -c core.quotepath=false ls-files) 
$remove=@($tracked | Where-Object { -not $allowed.Contains($_) })
$addSpec=Join-Path $gitDirectory 'gernze-allowlist-pathspec'
$removeSpec=Join-Path $gitDirectory 'gernze-excluded-pathspec'
try{
 [IO.File]::WriteAllText($addSpec,($manifest.files -join [char]0)+[char]0,[Text.UTF8Encoding]::new($false))
 if($remove.Count -gt 0){
  [IO.File]::WriteAllText($removeSpec,($remove -join [char]0)+[char]0,[Text.UTF8Encoding]::new($false))
  & git --literal-pathspecs rm --cached --ignore-unmatch "--pathspec-from-file=$removeSpec" --pathspec-file-nul
  if($LASTEXITCODE -ne 0){throw 'Could not remove excluded index entries; files on disk were retained'}
 }
 & git --literal-pathspecs add "--pathspec-from-file=$addSpec" --pathspec-file-nul
 if($LASTEXITCODE -ne 0){throw 'Could not stage source allowlist'}
 & git commit -m $Message
 if($LASTEXITCODE -ne 0){throw 'Commit did not finish; not pushed'}
 $remotes=@(& git remote)
 if($remotes -contains 'origin'){$remote='origin'}elseif($remotes.Count -eq 1){$remote=$remotes[0]}else{throw 'Select the intended Git remote before pushing'}
 & git push -u $remote HEAD
 if($LASTEXITCODE -ne 0){throw 'Push did not finish; local commit remains'}
}finally{
 Remove-Item -LiteralPath $addSpec,$removeSpec -ErrorAction SilentlyContinue
}
