"""Launch or stop an isolated native Windows Branchline benchmark instance.

Uses the existing windows-vm SSH connection. Windows GUI processes launched by
SSHD run in session 0, so a temporary interactive task starts the app in Max's
already logged-in desktop. The task is removed as soon as its PID is recorded.
No passwords, firewall rules, persistent tasks, or global environment changes.

The profile owns config/, data/, webview/, app.json, and logs. MCP autostart and
hardware acceleration stay enabled. Stop validates executable, creation time,
and MCP child lineage before terminating any process. The caller separately
owns the SSH local forward for WebView2's loopback debug endpoint.
"""

import argparse
import base64
import json
import re
from pathlib import Path, PureWindowsPath
import subprocess


COMMON = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$params=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PARAMS__')))
$runDirectory=[IO.Path]::GetFullPath($params.profile)
$record=Join-Path $runDirectory 'app.json'
'''

START = r'''
$binary=(Resolve-Path -LiteralPath $params.binary).ProviderPath
foreach($port in @($params.cdp_port,$params.mcp_port)) {
    if(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Benchmark port $port is already in use; stop its owned run first"
    }
}
if(Test-Path $record) {
    $old=Get-Content $record -Raw | ConvertFrom-Json
    if(Get-Process -Id $old.pid -ErrorAction SilentlyContinue) {throw 'Profile already has a live process'}
}
New-Item -ItemType Directory -Force -Path $runDirectory,"$runDirectory\config\branchline","$runDirectory\data","$runDirectory\webview" | Out-Null
$configPath=Join-Path $runDirectory 'config\branchline\config.json'
$config=if(Test-Path $configPath){Get-Content $configPath -Raw | ConvertFrom-Json}else{[pscustomobject]@{}}
$config | Add-Member -NotePropertyName mcp_auto_start -NotePropertyValue $true -Force
$config | Add-Member -NotePropertyName hardware_acceleration -NotePropertyValue $true -Force
$config | Add-Member -NotePropertyName mcp_port -NotePropertyValue $params.mcp_port -Force
[IO.File]::WriteAllText($configPath,($config | ConvertTo-Json -Depth 30))
$params | Add-Member -NotePropertyName binary -NotePropertyValue $binary -Force
$params | Add-Member -NotePropertyName profile -NotePropertyValue $runDirectory -Force
$launchParams=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($params | ConvertTo-Json -Compress)))
$launcher=@'
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$p=ConvertFrom-Json ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__LAUNCH_PARAMS__')))
try {
    $env:XDG_CONFIG_HOME=Join-Path $p.profile 'config'
    $env:LOCALAPPDATA=Join-Path $p.profile 'data'
    $env:WEBVIEW2_USER_DATA_FOLDER=Join-Path $p.profile 'webview'
    $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--remote-debugging-port='+$p.cdp_port
    $env:BRANCHLINE_MCP_PORT=[string]$p.mcp_port
    $process=Start-Process -FilePath $p.binary -ArgumentList ('"'+$p.repo+'"') -WorkingDirectory (Split-Path $p.binary) -PassThru -RedirectStandardOutput (Join-Path $p.profile 'stdout.log') -RedirectStandardError (Join-Path $p.profile 'stderr.log')
    $info=Get-CimInstance Win32_Process -Filter ('ProcessId='+$process.Id)
    if($info.SessionId -eq 0) {Stop-Process -Id $process.Id;throw 'Benchmark GUI launched in noninteractive session 0'}
    $record=@{pid=$process.Id;binary=$p.binary;repo=$p.repo;profile=$p.profile;cdp_port=$p.cdp_port;mcp_port=$p.mcp_port;session=$info.SessionId;created=$info.CreationDate.ToString('o');binary_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $p.binary).Hash.ToLowerInvariant();source_hash=$p.source_hash}
    [IO.File]::WriteAllText((Join-Path $p.profile 'app.json'),($record|ConvertTo-Json -Compress))
} catch {
    [IO.File]::WriteAllText((Join-Path $p.profile 'launcher-error.log'),($_|Out-String))
    exit 1
}
'@
$launcher=$launcher.Replace('__LAUNCH_PARAMS__',$launchParams)
$launchFile=Join-Path $runDirectory 'launch.ps1'
[IO.File]::WriteAllText($launchFile,$launcher)
Remove-Item (Join-Path $runDirectory 'launcher-error.log') -ErrorAction SilentlyContinue
Remove-Item $record -ErrorAction SilentlyContinue
$hash=[Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($runDirectory))
$task='BranchlineBench-'+([BitConverter]::ToString($hash).Replace('-','').Substring(0,12))
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$launchFile+'"')
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$registered=$false
try {
    Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Description 'Temporary isolated Branchline performance benchmark' | Out-Null
    $registered=$true
    Start-ScheduledTask -TaskName $task
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    while([DateTime]::UtcNow -lt $deadline) {
        if(Test-Path (Join-Path $runDirectory 'launcher-error.log')) {throw (Get-Content (Join-Path $runDirectory 'launcher-error.log') -Raw)}
        if(Test-Path $record) {
            try {$result=Get-Content $record -Raw | ConvertFrom-Json} catch {$result=$null}
            if($result -and (Get-Process -Id $result.pid -ErrorAction SilentlyContinue)) {
                $result | ConvertTo-Json -Compress
                return
            }
        }
        Start-Sleep -Milliseconds 100
    }
    throw 'Interactive benchmark launcher did not produce a live app PID in 30 seconds'
} finally {
    if($registered){Unregister-ScheduledTask -TaskName $task -Confirm:$false}
}
'''

STOP = r'''
if(-not (Test-Path $record)){throw 'No owned benchmark app.json record exists'}
$run=Get-Content $record -Raw | ConvertFrom-Json
if($run.profile -ne $runDirectory){throw 'Profile ownership record does not match'}
$process=Get-CimInstance Win32_Process -Filter ('ProcessId='+$run.pid)
if($process) {
    if($process.ExecutablePath -ne $run.binary -or $process.CreationDate.ToString('o') -ne $run.created) {
        throw 'Recorded PID belongs to a different executable or process creation time'
    }
}
# The desktop spawns MCP with only --mcp/--port arguments. The unique port was
# unoccupied before launch; match binary, parent PID, and creation time as well.
$children=@(Get-CimInstance Win32_Process -Filter ('ParentProcessId='+$run.pid) | Where-Object {
    $_.ExecutablePath -eq $run.binary -and
    $_.CreationDate -ge [DateTime]::Parse($run.created) -and
    $_.CommandLine -match '(?:^|\s)--mcp(?:\s|$)' -and
    $_.CommandLine -match ('(?:^|\s)--port\s+'+[regex]::Escape([string]$run.mcp_port)+'(?:\s|$)')
})
$stopped=@()
if($process) {
    $app=Get-Process -Id $run.pid
    if(-not $app.CloseMainWindow() -or -not $app.WaitForExit(3000)) {Stop-Process -Id $run.pid}
    $stopped+=[int]$run.pid
}
foreach($child in $children){Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue;$stopped+=[int]$child.ProcessId}
@{profile=$runDirectory;stopped_pids=$stopped}|ConvertTo-Json -Compress
'''


def remote(host, body, params):
    encoded_params = base64.b64encode(json.dumps(params).encode()).decode()
    script = COMMON.replace('__PARAMS__', encoded_params) + body
    # Feed a temporary script file through the existing Git Bash SSH shell.
    # PowerShell's Console.In reader can wait indefinitely on an SSH pipe;
    # -File also avoids Windows command-line length limits.
    command = ("control=$(mktemp --suffix=.ps1); trap 'rm -f \"$control\"' EXIT; "
               'cat > "$control"; powershell.exe -NoProfile -NonInteractive '
               '-ExecutionPolicy Bypass -File "$(cygpath -w "$control")"')
    result = subprocess.run([
        'ssh', '-F', str(Path.home() / '.ssh/config'),
        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, command,
    ], input=script, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout.lstrip('\ufeff').strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('--host', default='windows-vm')
    parser.add_argument('--profile', required=True, help='Owned absolute Windows-local runtime directory')
    parser.add_argument('--binary', help='Packaged native Windows executable')
    parser.add_argument('--repo', help='Windows path, including a WSL UNC checkout')
    parser.add_argument('--cdp-port', type=int, default=29223)
    parser.add_argument('--mcp-port', type=int, default=28865)
    parser.add_argument('--source-hash', help='SHA-256 source manifest identity of the packaged build')
    args = parser.parse_args()
    if args.source_hash and not re.fullmatch('[0-9a-f]{64}', args.source_hash):
        parser.error('--source-hash must be a lowercase SHA-256 identity')
    profile = PureWindowsPath(args.profile)
    if not profile.is_absolute() or profile.drive.startswith('\\\\'):
        parser.error('--profile must be an absolute Windows-local drive path')
    if args.action == 'start' and (not args.binary or not args.repo):
        parser.error('start requires --binary and --repo')
    if not all(1024 <= port <= 65535 for port in (args.cdp_port, args.mcp_port)):
        parser.error('Use unprivileged valid CDP and MCP ports')
    if args.cdp_port == args.mcp_port:
        parser.error('CDP and MCP ports must differ')
    if args.repo and '"' in args.repo:
        parser.error('A Windows checkout path cannot contain a double quote')
    params = {key: value for key, value in vars(args).items() if key not in {'action', 'host'}}
    print(json.dumps(remote(args.host, START if args.action == 'start' else STOP, params), indent=2))


if __name__ == '__main__':
    main()
