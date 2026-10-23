param(
    [string]$ReleaseDirectory = 'release_current',
    [string]$PythonExecutable = '',
    [string]$ModuleCatalog = '',
    [string]$ApplicationName = '莉宝',
    [ValidateSet('public','private')][string]$BuildMode = 'public'
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
$icon = Join-Path $project 'assets\icons\libao.ico'
$idle = Join-Path $project 'assets\pixel\libao\idle'
$reading = Join-Path $project 'assets\pixel\libao\reading'
$actions = Join-Path $project 'assets\pixel\libao\actions'
$ui = Join-Path $project 'assets\ui'
$walk = Join-Path $project 'assets\walk'
$grab = Join-Path $project 'assets\grab'
$entry = Join-Path $project 'desktop_main.py'
$dataStage = Join-Path $project ("build\generated-" + $BuildMode)
$persona = Join-Path $dataStage 'companion_persona.md'
$release = if ([IO.Path]::IsPathRooted($ReleaseDirectory)) { $ReleaseDirectory } else { Join-Path $project $ReleaseDirectory }
$work = Join-Path $project 'build\pyinstaller'
$spec = Join-Path $project 'build\spec'
if (-not $ModuleCatalog) { $ModuleCatalog = Join-Path $project 'module_catalog.json' }
if (-not (Test-Path -LiteralPath $ModuleCatalog)) { throw 'Build matching modules first, then specify -ModuleCatalog' }
$publicSeed = Join-Path $project 'build\public_empty\handoff_status.json'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $publicSeed) | Out-Null
[System.IO.File]::WriteAllText($publicSeed, '{"id":"public_empty_v1","records":[]}', [System.Text.UTF8Encoding]::new($false))

if (-not (Test-Path -LiteralPath $python)) { throw "Build Python missing: $python" }
if (-not (Test-Path -LiteralPath $icon)) { throw "Icon missing: $icon" }
if (-not (Test-Path -LiteralPath $idle)) { throw "Idle assets missing: $idle" }
if (-not (Test-Path -LiteralPath (Join-Path $project 'assets\voice\manifest.json'))) { throw 'Core fixed recordings missing' }

# Rebuild the bundled native observer using the Windows .NET Framework compiler.
$compiler = 'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$observerSource = Join-Path $project 'assets\codex_monitor\QuietCodexMonitor.cs'
$observerExe = Join-Path $project 'assets\codex_monitor\QuietCodexMonitor.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework compiler missing' }
& $compiler /nologo /codepage:65001 /target:winexe /optimize+ /reference:System.Windows.Forms.dll /reference:System.Drawing.dll "/out:$observerExe" $observerSource
if ($LASTEXITCODE -ne 0) { throw 'Codex metadata observer compilation failed' }

& $python (Join-Path $project '..\mobile\tools\build-core.py') --mode $BuildMode --output $dataStage
if ($LASTEXITCODE -ne 0) { throw 'Core data build failed' }

$arguments = @(
    '-m', 'PyInstaller',
    '--noconfirm', '--clean', '--onedir', '--windowed',
    "--name=$ApplicationName",
    '--exclude-module=libao_modules.handoff',
    '--exclude-module=libao_modules.daily_study',
    '--exclude-module=libao_modules.prompts',
    "--icon=$icon",
    "--add-data=$idle;assets\pixel\libao\idle",
    "--add-data=$reading;assets\pixel\libao\reading",
    "--add-data=$actions;assets\pixel\libao\actions",
    "--add-data=$ui;assets\ui",
    "--add-data=$walk;assets\walk",
    "--add-data=$grab;assets\grab",
    "--add-data=$project\assets\codex_monitor;assets\codex_monitor",
    "--add-data=$project\assets\styles;assets\styles",
    "--add-data=$project\assets\voice;assets\voice",

    "--add-data=$icon;assets\icons",
    "--add-data=$project\workbench\static;workbench\static",
    "--add-data=$persona;workbench",
    "--add-data=$dataStage\companion_core_memory.json;workbench",
    "--add-data=$project\workbench\chat-protocol.json;workbench",
    "--add-data=$publicSeed;.",
    "--add-data=$ModuleCatalog;.",
    "--add-data=$project\behavior_config.json;.",
    '--hidden-import=libao_modules.ui',
    '--hidden-import=libao_modules._ui_baseline',
    '--hidden-import=ui_theme',
    '--hidden-import=module_package_self_test',
    '--hidden-import=module_adoption_self_test',
    '--hidden-import=foot_front_self_test',
    '--hidden-import=long_soak_self_test',
    '--hidden-import=activity_timing_self_test',
    '--hidden-import=sleep_v11_self_test',
    '--hidden-import=win32timezone',
    "--distpath=$release",
    "--workpath=$work",
    "--specpath=$spec",
    $entry
)
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
$exe = Join-Path $release "$ApplicationName\$ApplicationName.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "Missing EXE: $exe" }
Write-Output $exe

