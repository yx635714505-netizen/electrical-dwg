param([switch]$SubmitOnly)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$configPath = Join-Path $root "config.local.json"
if (!(Test-Path -LiteralPath $configPath)) { $configPath = Join-Path $root "config.json" }
$config=Get-Content -LiteralPath $configPath -Raw|ConvertFrom-Json
$targetWorkers=[math]::Min([int]$config.maxWorkers,5)
$existing=(& "$root\pool.ps1" -Action status|ConvertFrom-Json)
if(@($existing.jobs|Where-Object {$_.status -in @('queued','running','stopping','blocked')}).Count){throw 'Run diagnostics only when production jobs are finished'}
$utf8=New-Object Text.UTF8Encoding($false)
$package="$root\tests\native-smoke"
New-Item -ItemType Directory -Path "$package\input","$package\scripts" -Force|Out-Null
Copy-Item -LiteralPath (Join-Path $root "../assets/front-directory-notes.dwg") -Destination "$package\input\native.dwg" -Force
[IO.File]::WriteAllText("$package\job.json",(@{isolationContract=1;validationReport='output/validation.json';expectedOutputs=@('output/native-copy.dwg');purpose='Infrastructure native concurrency test, not project delivery'}|ConvertTo-Json),$utf8)
[IO.File]::WriteAllText("$package\scripts\command.scr","CADPOOLSMOKE`r`n",$utf8)
$ids=@()
for($i=1;$i -le 5;$i++){
 if($i -eq 4){[IO.File]::WriteAllText("$package\scripts\command.scr","CADPOOLFAIL`r`n",$utf8)}else{[IO.File]::WriteAllText("$package\scripts\command.scr","CADPOOLSMOKE`r`n",$utf8)}
 $j=(& "$root\pool.ps1" -Action submit -Package $package -Name "Isolation smoke $i"|ConvertFrom-Json);$ids+=$j.id
}
$rejected=$false
try{& "$root\pool.ps1" -Action submit -Package $package -Name 'Must reject sixth'}catch{if($_.Exception.Message -like 'Queue full*'){$rejected=$true}else{throw}}
if(!$rejected){throw 'Capacity test failed: sixth job accepted'}
[IO.File]::WriteAllText("$root\tests\last-run.json",(@{ids=$ids;sixthRejected=$rejected;submittedUtc=[datetime]::UtcNow.ToString('o')}|ConvertTo-Json),$utf8)
& "$root\pool.ps1" -Action start
if($SubmitOnly){return}
$max=0;$sawQueue=$false;$snapshots=@();$until=[datetime]::UtcNow.AddMinutes(8)
do{
 $state=(& "$root\pool.ps1" -Action status|ConvertFrom-Json)
 $jobs=@($state.jobs|Where-Object {$_.id -in $ids});$active=@($jobs|Where-Object {$_.status -in @('running','stopping','blocked')}).Count
 $queued=@($jobs|Where-Object status -eq 'queued').Count
 $max=[math]::Max($max,$active);if($active -eq $targetWorkers -and $queued -eq (5-$targetWorkers)){$sawQueue=$true}
 if($active -gt $targetWorkers){throw 'Worker cap violated'}
 $snapshots+=@{utc=[datetime]::UtcNow.ToString('o');active=$active;queued=$queued}
 if(@($jobs|Where-Object {$_.status -in @('queued','running','stopping','blocked')}).Count -eq 0){break}
 Start-Sleep -Seconds 2
}while([datetime]::UtcNow -lt $until)
$ok=@($jobs|Where-Object status -eq 'succeeded').Count -eq 4 -and @($jobs|Where-Object status -eq 'failed').Count -eq 1
$processes=@($jobs|ForEach-Object {Get-Content -LiteralPath ($_.root+'\control\process.json') -Raw|ConvertFrom-Json})
$ready=@($jobs|ForEach-Object {Get-Content -LiteralPath ($_.root+'\control\ready.json') -Raw|ConvertFrom-Json})
$isolated=@($processes.pid|Select-Object -Unique).Count -eq 5 -and @($ready.temp|Select-Object -Unique).Count -eq 5 -and @($ready.profile|Select-Object -Unique).Count -eq $targetWorkers
$report=@{passed=($ok -and $isolated -and $max -eq $targetWorkers -and $sawQueue -and $rejected);sixthRejected=$rejected;maxActive=$max;sawConfiguredConcurrency=$sawQueue;isolatedProcessesAndTemp=$isolated;outcomes=@($jobs|Select-Object id,status,message);snapshots=$snapshots}
[IO.File]::WriteAllText("$root\tests\verification.json",($report|ConvertTo-Json -Depth 12),$utf8)
$report|Select-Object passed,sixthRejected,maxActive,sawConfiguredConcurrency,isolatedProcessesAndTemp,outcomes|ConvertTo-Json -Depth 4
if(!$report.passed){throw 'Integration tests failed; inspect tests/verification.json and job logs'}
