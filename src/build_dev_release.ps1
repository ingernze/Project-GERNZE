param(
    [string]$ReleaseDirectory = 'release_current',
    [string]$PythonExecutable = ''
)
$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSCommandPath
$python = $PythonExecutable
if (-not $python) {
    $candidates = @(
        (Join-Path $project '.venv\Scripts\python.exe'),
        (Join-Path $project '.build-venv\Scripts\python.exe')
    )
    $python = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $python) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $python = $command.Source }
    }
}
if (-not $python) { throw 'Specify -PythonExecutable with a compatible Python build environment' }
$icon = Join-Path $project 'assets\icons\hebao.ico'
$idle = Join-Path $project 'assets\pixel\hebao\idle'
$reading = Join-Path $project 'assets\pixel\hebao\reading'
$actions = Join-Path $project 'assets\pixel\hebao\actions'
$ui = Join-Path $project 'assets\ui'
$walk = Join-Path $project 'assets\walk'
$grab = Join-Path $project 'assets\grab'
$entry = Join-Path $project 'deepseek_trial.py'
$release = Join-Path $project $ReleaseDirectory
$work = Join-Path $project 'build\pyinstaller'
$spec = Join-Path $project 'build\spec'

if (-not (Test-Path -LiteralPath $python)) { throw "Build Python missing: $python" }
if (-not (Test-Path -LiteralPath $icon)) { throw "Icon missing: $icon" }
if (-not (Test-Path -LiteralPath $idle)) { throw "Idle assets missing: $idle" }

# Rebuild the bundled native observer using the Windows .NET Framework compiler.
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$observerSource = Join-Path $project 'assets\codex_monitor\QuietCodexMonitor.cs'
$observerExe = Join-Path $project 'assets\codex_monitor\QuietCodexMonitor.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework compiler missing' }
& $compiler /nologo /codepage:65001 /target:winexe /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll "/out:$observerExe" $observerSource
if ($LASTEXITCODE -ne 0) { throw 'Codex metadata observer compilation failed' }

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean', '--onedir', '--windowed',
    '--name=赫宝开发版',
    "--icon=$icon",
    "--add-data=$idle;assets\pixel\hebao\idle",
    "--add-data=$reading;assets\pixel\hebao\reading",
    "--add-data=$actions;assets\pixel\hebao\actions",
    "--add-data=$ui;assets\ui",
    "--add-data=$walk;assets\walk",
    "--add-data=$grab;assets\grab",
    "--add-data=$project\assets\codex_monitor;assets\codex_monitor",
    "--add-data=$project\assets\styles;assets\styles",
    "--add-data=$project\assets\voice;assets\voice",
    "--add-data=$icon;assets\icons",
    "--add-data=$project\workbench\static;workbench\static",
    "--add-data=$project\handoff_status.json;.",
    "--add-data=$project\behavior_config.json;.",
    '--hidden-import=hebao_modules.ui',
    '--hidden-import=hebao_modules._ui_baseline',
    '--hidden-import=hecate_ui',
    '--hidden-import=win32timezone',
    "--distpath=$release",
    "--workpath=$work",
    "--specpath=$spec",
    $entry
)
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
$exe = Join-Path $release '赫宝开发版\赫宝开发版.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "Missing EXE: $exe" }
Write-Output $exe

