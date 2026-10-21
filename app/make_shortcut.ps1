$d = (Get-Location).Path
$desk = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut((Join-Path $desk '3종서류 자동 분할.lnk'))
$s.TargetPath = (Join-Path $d '.venv\Scripts\pythonw.exe')
$s.Arguments = '"' + (Join-Path $d 'app\main.py') + '"'
$s.WorkingDirectory = $d
$s.IconLocation = (Join-Path $env:SystemRoot 'System32\imageres.dll') + ',-68'
$s.Description = '3종서류 자동 분할'
$s.Save()
Write-Host '    바탕화면에 바로가기를 만들었어요.'
