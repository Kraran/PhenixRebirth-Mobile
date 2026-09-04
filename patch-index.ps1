$f = Join-Path $PSScriptRoot "build\web\index.html"
if (-not (Test-Path $f)) { $f = "D:\PhenixRebirth-Mobile\build\web\index.html" }
if (-not (Test-Path $f)) { Write-Host "PAS de index.html"; exit 1 }
$c = Get-Content $f -Raw -Encoding UTF8
$c = $c -replace 'ume_block\s*:\s*1','ume_block : 0'
$c = $c -replace '"ume_block"\s*:\s*1','"ume_block": 0'
$c = $c -replace 'ume_block=1','ume_block=0'
$c = $c -replace 'xtermjs"\s*:\s*"1"','xtermjs": "0"'
$c = $c -replace 'xtermjs\s*:\s*"1"','xtermjs : "0"'
$c = $c -replace 'xtermjs\s*:\s*1','xtermjs : 0'
$c = $c -replace '"xtermjs"\s*:\s*1','"xtermjs": 0'
$c = $c -replace 'gui_debug\s*:\s*3','gui_debug : 0'
$c = $c -replace 'data-os="vtx,fs,snd,gui"','data-os="fs,gui"'
$c = $c -replace 'data-os="vtx,fs,gui"','data-os="fs,gui"'
$c = $c -replace '"snd",',''
$c = $c -replace ',"snd"',''
Set-Content $f $c -Encoding UTF8
Write-Host "index.html patche (xterm OFF, snd OFF)"
Select-String -Path $f -Pattern "ume_block|xtermjs|data-os|gui_debug" | Select-Object -First 12
