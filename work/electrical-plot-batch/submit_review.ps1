[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Package,
    [Parameter(Mandatory)] [string] $Name,
    [Parameter(Mandatory)] [AllowEmptyCollection()] [int[]] $WeakFloors,
    [Parameter(Mandatory)] [string] $MountWidths,
    [int[]] $CameraFloors = @(1),
    [string] $Calibration = (Join-Path $PSScriptRoot 'socket-template-cache.json'),
    [switch] $CheckOnly
)

$ErrorActionPreference = 'Stop'
$packagePath = (Resolve-Path -LiteralPath $Package).Path
$python = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if ($env:ELECTRICAL_PYTHON) { $python = $env:ELECTRICAL_PYTHON }
elseif (!(Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
$script = Join-Path $PSScriptRoot 'review_preflight.py'
$design = Join-Path $packagePath 'input/build.json'
$arguments = @('-B', '-X', 'utf8', $script, 'package', $design, '--weak-floors') + $WeakFloors
$arguments += @('--mount-widths', $MountWidths, '--cache', $Calibration, '--camera-floors') + $CameraFloors
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw '请按以上清单集中修正，再提交当前任务包。' }
if ($CheckOnly) { return }

$workspace = Split-Path (Split-Path $PSScriptRoot)
& (Join-Path $workspace 'cad_pool/pool.ps1') -Action submit -Package $packagePath -Name $Name
