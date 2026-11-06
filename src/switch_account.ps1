# Local credential transactions only. No remote session revocation.
# All dry runs are read-only. All target matches are exact.
param(
    [string]$To,
    [switch]$Snapshot,
    [switch]$Park,
    [switch]$List,
    [switch]$DryRun,
    [switch]$RestoreProjects,
    [string]$AuthFile = (Join-Path $env:USERPROFILE '.codex\auth.json'),
    [Parameter(Mandatory=$true)]
    [string]$SnapshotDir,
    [string]$AppAumid = 'OpenAI.Codex_2p2nqsd0c76g0!App'
)
$ErrorActionPreference = 'Stop'
$DataDir = Join-Path $SnapshotDir 'recovery'
$Utf8 = New-Object Text.UTF8Encoding($false)

function Assert-SafePath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        try {
            $attributes = [IO.File]::GetAttributes($cursor)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Credential path contains a link or reparse point'
            }
            if (($attributes -band [IO.FileAttributes]::Directory) -eq 0 -and
                (Get-Item -LiteralPath $cursor -Force).LinkType -eq 'HardLink') {
                throw 'Credential path has multiple hard links'
            }
        } catch [IO.FileNotFoundException] { } catch [IO.DirectoryNotFoundException] { }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}
function Protect-Path([string]$Path) {
    Assert-SafePath $Path
    $item = Get-Item -LiteralPath $Path -Force
    $acl = if ($item.PSIsContainer) { New-Object Security.AccessControl.DirectorySecurity }
           else { New-Object Security.AccessControl.FileSecurity }
    $acl.SetAccessRuleProtection($true, $false)
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $principals = @($user, (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')),
                    (New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach ($principal in $principals) {
        if ($item.PSIsContainer) {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        } else {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'Allow')
        }
        $acl.AddAccessRule($rule)
    }
    # Direct .NET calls do not depend on inherited PSModulePath. The helper is
    # deliberately run by Windows PowerShell 5.1 even when its parent is PS7.
    if ($item.PSIsContainer) { [IO.Directory]::SetAccessControl($Path, $acl) }
    else { [IO.File]::SetAccessControl($Path, $acl) }
}
function Decode-CredentialBytes([byte[]]$Bytes) {
    try { $document = $Utf8.GetString($Bytes).TrimStart([char]0xFEFF) | ConvertFrom-Json }
    catch { throw 'Invalid credential document' }
    if ($document.PSObject.Properties.Name -contains 'chatgptnx_credential') {
        if ($document.chatgptnx_credential -ne 1 -or $document.protection -ne 'dpapi-current-user') {
            throw 'Unsupported credential protection format'
        }
        Add-Type -AssemblyName System.Security
        try {
            $encrypted = [Convert]::FromBase64String([string]$document.data)
            $plain = [Security.Cryptography.ProtectedData]::Unprotect($encrypted,
                $Utf8.GetBytes('ChatGPTnx credentials v1'), [Security.Cryptography.DataProtectionScope]::CurrentUser)
            return ,$plain
        } catch { throw 'Cannot decrypt credential for this Windows user' }
    }
    return ,$Bytes
}
function Read-CredentialBytes([string]$Path) {
    Assert-SafePath $Path
    return ,(Decode-CredentialBytes ([IO.File]::ReadAllBytes($Path)))
}
function Atomic-WriteBytes([byte[]]$Bytes, [string]$ToPath) {
    Assert-SafePath $ToPath
    $dir = Split-Path -Parent $ToPath
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    # Only the portable store's directories get private directory ACLs. Never
    # change the official application's home directory or its other files.
    if ([IO.Path]::GetFullPath($ToPath).StartsWith([IO.Path]::GetFullPath($SnapshotDir).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Protect-Path $dir
    }
    $tmp = Join-Path $dir ('.nx-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        # Set permissions while the file is empty, before plaintext auth bytes.
        $stream = [IO.File]::Open($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Dispose()
        Protect-Path $tmp
        $stream = [IO.File]::Open($tmp, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($tmp)) -cne [Convert]::ToBase64String($Bytes)) {
            throw 'Credential file verification failed'
        }
        $delays = @(0, 10, 20, 40, 80, 160)
        for ($attempt = 0; $attempt -lt $delays.Count; $attempt++) {
            if ($delays[$attempt]) { Start-Sleep -Milliseconds $delays[$attempt] }
            Assert-SafePath $ToPath
            try {
                if (Test-Path -LiteralPath $ToPath) {
                    Protect-Path $ToPath
                    [IO.File]::Replace($tmp, $ToPath, [NullString]::Value)
                } else { [IO.File]::Move($tmp, $ToPath) }
                break
            } catch [IO.IOException] {
                $code = $_.Exception.GetBaseException().HResult -band 0xffff
                if ($attempt -eq $delays.Count - 1 -or $code -notin @(5, 32, 33)) { throw }
            } catch [UnauthorizedAccessException] {
                if ($attempt -eq $delays.Count - 1) { throw }
            }
        }
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}
function Write-ProtectedCredential([byte[]]$Bytes, [string]$ToPath) {
    Add-Type -AssemblyName System.Security
    try {
        $cipher = [Security.Cryptography.ProtectedData]::Protect($Bytes,
            $Utf8.GetBytes('ChatGPTnx credentials v1'), [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $envelope = @{chatgptnx_credential=1; protection='dpapi-current-user'; data=[Convert]::ToBase64String($cipher)} | ConvertTo-Json -Compress
        $encoded = $Utf8.GetBytes($envelope)
        $decoded = Decode-CredentialBytes $encoded
        if ([Convert]::ToBase64String($decoded) -cne [Convert]::ToBase64String($Bytes)) { throw 'Verification failed' }
    } catch { throw 'Credential encryption verification failed' }
    Atomic-WriteBytes $encoded $ToPath
}
function Read-Identity([string]$Path) {
    $j = $Utf8.GetString((Read-CredentialBytes $Path)).TrimStart([char]0xFEFF) | ConvertFrom-Json
    $raw = $j.tokens.id_token
    if (-not $raw) { throw 'id_token missing; no changes made' }
    $parts = $raw.Split('.')
    if ($parts.Length -lt 2) { throw 'invalid credential format' }
    $p = $parts[1].Replace('-', '+').Replace('_', '/')
    switch ($p.Length % 4) { 2 { $p += '==' } 3 { $p += '=' } }
    $claim = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p)) | ConvertFrom-Json
    $email = [string]$claim.email
    if ($email -notmatch '^[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+$') { throw 'unsafe or missing email' }
    $account = $j.tokens.account_id
    if (-not $account) { $account = $j.account_id }
    if (-not $account) { $account = $claim.'https://api.openai.com/auth'.chatgpt_account_id }
    if (-not $account) { throw 'account id missing' }
    $user = [string]$claim.'https://api.openai.com/auth'.chatgpt_user_id
    if (-not $user) { $user = [string]$claim.'https://api.openai.com/auth'.user_id }
    $owner = $null
    if ($user) {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $owner = ([BitConverter]::ToString($hash.ComputeHash($Utf8.GetBytes(
            (@($user, [string]$account) | ConvertTo-Json -Compress))))).Replace('-', '').ToLowerInvariant() }
        finally { $hash.Dispose() }
    }
    [pscustomobject]@{ Email=$email; AccountId=$account; RendererOwner=$owner }
}

function State-Map($Value) {
    $map = @{}
    if ($Value -is [Collections.IDictionary]) {
        foreach ($key in $Value.Keys) { $map[$key] = $Value[$key] }
    } elseif ($Value -is [pscustomobject]) {
        foreach ($property in $Value.PSObject.Properties) { $map[$property.Name] = $property.Value }
    }
    return $map
}
function Local-Workspace($Globals, $Atoms) {
    # Only this Windows computer's Codex projects and their local assignments.
    # Cloud conversations, remote hosts, prompts, plugins and account preferences
    # are deliberately outside this transfer.
    $g = State-Map $Globals
    $projects = @{}
    $local = State-Map $g['local-projects']
    foreach ($id in $local.Keys) {
        $project = $local[$id]
        $roots = @($project.rootPaths)
        if ($project.id -cne $id -or -not $roots.Count -or
            @($roots | Where-Object { $_ -isnot [string] -or $_ -notmatch '^(?:[A-Za-z]:[\\/]|\\\\\?\\[A-Za-z]:\\)' }).Count) { continue }
        $projects[$id] = $project
    }
    if (-not $projects.Count) { return $null }
    $result = @{'local-projects' = $projects}
    $assignments = @{}
    $members = State-Map $g['thread-project-membership-host-ids']
    $original = State-Map $g['thread-project-assignments']
    foreach ($id in $original.Keys) {
        $entry = $original[$id]
        if ($entry.projectKind -eq 'local' -and $projects.ContainsKey([string]$entry.projectId) -and
            (-not $members.ContainsKey($id) -or $members[$id] -eq 'local')) { $assignments[$id] = $entry }
    }
    $result['thread-project-assignments'] = $assignments
    $result['thread-project-membership-host-ids'] = @{}
    foreach ($id in $assignments.Keys) { $result['thread-project-membership-host-ids'][$id] = 'local' }
    foreach ($key in @('project-order', 'pinned-project-ids')) {
        if ($g.ContainsKey($key)) { $result[$key] = @($g[$key] | Where-Object { $projects.ContainsKey([string]$_) }) }
    }
    if ($g['selected-project'].projectKind -eq 'local' -and
        $projects.ContainsKey([string]$g['selected-project'].projectId)) { $result['selected-project'] = $g['selected-project'] }
    foreach ($key in @('app-server-project-id-by-legacy-project-id-by-host', 'app-server-projects-migration-by-host')) {
        $hosts = State-Map $g[$key]
        $result[$key] = @{}
        foreach ($hostKey in $hosts.Keys) {
            if ($hostKey -notlike 'local:*') { continue }
            if ($key -eq 'app-server-project-id-by-legacy-project-id-by-host') {
                $ids = State-Map $hosts[$hostKey]; $kept = @{}
                foreach ($id in $ids.Keys) { if ($projects.ContainsKey($id)) { $kept[$id] = $ids[$id] } }
                $result[$key][$hostKey] = $kept
            } else {
                $migration = State-Map $hosts[$hostKey]
                $migration['threadAssignmentsMigrated'] = $false
                $migration['threadAssignmentsReadMigrated'] = $false
                $migration['pendingThreadAssignmentIds'] = @($assignments.Keys)
                $result[$key][$hostKey] = $migration
            }
        }
    }
    $atomsOut = @{}
    $a = State-Map $Atoms
    foreach ($id in $projects.Keys) {
        $key = 'sidebar-project-expanded-v1-codex:' + $id
        if ($a.ContainsKey($key)) { $atomsOut[$key] = $a[$key] }
    }
    if ($a.ContainsKey('flat-project-sidebar-preferences-v1')) {
        $atomsOut['flat-project-sidebar-preferences-v1'] = $a['flat-project-sidebar-preferences-v1']
    }
    return @{ globals=$result; atoms=$atomsOut }
}
function Merge-WorkspaceMap($Destination, $Source, [string]$Key) {
    $dest = State-Map $Destination; $src = State-Map $Source
    foreach ($id in $src.Keys) {
        if (-not $dest.ContainsKey($id)) { $dest[$id] = $src[$id]; continue }
        if ($Key -eq 'local-projects') {
            if ((@($dest[$id].rootPaths) | ConvertTo-Json -Compress) -cne
                (@($src[$id].rootPaths) | ConvertTo-Json -Compress)) { throw 'Local project roots conflict; no workspace changes made' }
        } elseif ($Key -eq 'thread-project-assignments') {
            if ($dest[$id].projectKind -ne 'local' -or $dest[$id].projectId -cne $src[$id].projectId) {
                throw 'Local task project assignments conflict; no workspace changes made'
            }
        } elseif ($Key -eq 'app-server-project-id-by-legacy-project-id-by-host') {
            $dest[$id] = Merge-WorkspaceMap $dest[$id] $src[$id] 'project-id-map'
        } elseif ($Key -eq 'project-id-map' -and $dest[$id] -cne $src[$id]) {
            throw 'Local server project identities conflict; no workspace changes made'
        }
    }
    return $dest
}
function Workspace-ProjectIdentity($Workspace) {
    # Folder identity is separate from membership: later snapshots can contain
    # additional local threads without describing a different workspace.
    $parts = @()
    foreach ($id in ($Workspace.globals['local-projects'].Keys | Sort-Object)) {
        $parts += @('project', $id, @($Workspace.globals['local-projects'][$id].rootPaths)) | ConvertTo-Json -Depth 20 -Compress
    }
    return ($parts -join "`n")
}
function Workspace-Update($Document, [string]$TargetOwner) {
    $doc = State-Map $Document
    $scope = State-Map $doc['electron-account-renderer-state-v1']
    if (-not $scope.Count) { return $null } # Older desktop versions keep their existing behavior.
    if (($null -ne $scope['owner'] -and ($scope['owner'] -isnot [string] -or $scope['owner'] -notmatch '^[a-f0-9]{64}$')) -or
        -not $scope.ContainsKey('inactive')) { throw 'Unsupported desktop account state; no workspace changes made' }
    if ($TargetOwner -notmatch '^[a-f0-9]{64}$') { throw 'Desktop account identity unavailable; no workspace changes made' }
    $inactive = State-Map $scope['inactive']
    $source = Local-Workspace $doc $doc['electron-persisted-atom-state']
    if (-not $source) {
        $candidates = @()
        foreach ($entry in $inactive.Values) {
            $found = Local-Workspace $entry.globals $entry.atoms
            if ($found) { $candidates += ,$found }
        }
        if (-not $candidates.Count) { return $null }
        # Prefer the most complete snapshot, then combine compatible memberships.
        # A normal new conversation must not make the previous account ambiguous.
        $source = @($candidates | Sort-Object { $_.globals['thread-project-assignments'].Count } -Descending)[0]
        $identity = Workspace-ProjectIdentity $source
        foreach ($candidate in $candidates) {
            if ((Workspace-ProjectIdentity $candidate) -cne $identity) {
                throw 'Multiple inactive local project layouts; select the original account before switching'
            }
            foreach ($key in @('thread-project-assignments', 'thread-project-membership-host-ids',
                                'app-server-project-id-by-legacy-project-id-by-host')) {
                $source.globals[$key] = Merge-WorkspaceMap $source.globals[$key] $candidate.globals[$key] $key
            }
        }
    }
    $active = $scope['owner'] -ceq $TargetOwner
    $target = if ($active) { @{globals=(State-Map $doc); atoms=(State-Map $doc['electron-persisted-atom-state'])} }
              else { $saved = $inactive[$TargetOwner]; @{globals=(State-Map $saved.globals); atoms=(State-Map $saved.atoms)} }
    $before = $target | ConvertTo-Json -Depth 100 -Compress
    $assignmentCount = (State-Map $target.globals['thread-project-assignments']).Count
    foreach ($key in $source.globals.Keys) {
        if ($key -in @('project-order', 'pinned-project-ids')) {
            $target.globals[$key] = @(@($target.globals[$key]) + @($source.globals[$key]) | Where-Object { $null -ne $_ } | Select-Object -Unique)
        } elseif ($key -eq 'selected-project') {
            if (-not $target.globals[$key]) { $target.globals[$key] = $source.globals[$key] }
        } elseif ($key -eq 'app-server-projects-migration-by-host') {
            # The desktop, rather than NX, commits thread metadata migration.
            $target.globals[$key] = Merge-WorkspaceMap $target.globals[$key] $source.globals[$key] $key
        } else {
            $target.globals[$key] = Merge-WorkspaceMap $target.globals[$key] $source.globals[$key] $key
        }
    }
    foreach ($key in $source.atoms.Keys) {
        if (-not $target.atoms.ContainsKey($key)) { $target.atoms[$key] = $source.atoms[$key] }
    }
    if ((State-Map $target.globals['thread-project-assignments']).Count -gt $assignmentCount) {
        $key = 'app-server-projects-migration-by-host'
        $migrations = State-Map $target.globals[$key]
        foreach ($hostKey in @($migrations.Keys)) {
            if ($hostKey -notlike 'local:*') { continue }
            $migration = State-Map $migrations[$hostKey]
            $migration['threadAssignmentsMigrated'] = $false
            $migration['threadAssignmentsReadMigrated'] = $false
            $migration['pendingThreadAssignmentIds'] = @(@($migration['pendingThreadAssignmentIds']) + @($source.globals['thread-project-assignments'].Keys) | Where-Object { $null -ne $_ } | Select-Object -Unique)
            $migrations[$hostKey] = $migration
        }
        $target.globals[$key] = $migrations
    }
    if (($target | ConvertTo-Json -Depth 100 -Compress) -ceq $before) { return $null }
    if ($active) {
        foreach ($key in $source.globals.Keys) { $doc[$key] = $target.globals[$key] }
        $doc['electron-persisted-atom-state'] = $target.atoms
    } else {
        $inactive[$TargetOwner] = $target
        $scope['inactive'] = $inactive
        $doc['electron-account-renderer-state-v1'] = $scope
    }
    return $doc
}
function Assert-WorkspaceTransfer([string]$Credential) {
    $path = Join-Path (Split-Path -Parent $AuthFile) '.codex-global-state.json'
    if (-not (Test-Path -LiteralPath $path)) { return }
    Assert-SafePath $path
    $doc = $Utf8.GetString([IO.File]::ReadAllBytes($path)).TrimStart([char]0xFEFF) | ConvertFrom-Json
    $null = Workspace-Update $doc (Read-Identity $Credential).RendererOwner
}
function Replace-WorkspaceBytes([byte[]]$Bytes, [string]$Path, [byte[]]$Expected) {
    Assert-SafePath $Path
    if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($Path)) -cne [Convert]::ToBase64String($Expected)) {
        throw 'Desktop state changed concurrently; no workspace changes made'
    }
    $tmp = Join-Path ([IO.Path]::GetDirectoryName($Path)) ('.nx-workspace-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $stream = [IO.File]::Open($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Dispose()
        [IO.File]::SetAccessControl($tmp, [IO.File]::GetAccessControl($Path))
        $stream = [IO.File]::Open($tmp, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        Assert-SafePath $Path
        if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($Path)) -cne [Convert]::ToBase64String($Expected)) { throw 'Desktop state changed concurrently' }
        [IO.File]::Replace($tmp, $Path, [NullString]::Value)
    } finally { if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force } }
}
function Preserve-LocalWorkspace([string]$Credential, [string]$RecoveryPath) {
    $path = Join-Path (Split-Path -Parent $AuthFile) '.codex-global-state.json'
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    Assert-SafePath $path
    $original = [IO.File]::ReadAllBytes($path)
    $doc = $Utf8.GetString($original).TrimStart([char]0xFEFF) | ConvertFrom-Json
    $updated = Workspace-Update $doc (Read-Identity $Credential).RendererOwner
    if (-not $updated) { return $null }
    $bytes = $Utf8.GetBytes(($updated | ConvertTo-Json -Depth 100 -Compress))
    Write-ProtectedCredential $original $RecoveryPath
    Replace-WorkspaceBytes $bytes $path $original
    return @{Path=$path; Backup=$RecoveryPath}
}
function Atomic-Copy([string]$From, [string]$ToPath) {
    Atomic-WriteBytes (Read-CredentialBytes $From) $ToPath
}
function Save-Snapshot {
    $who = Read-Identity $AuthFile
    Write-ProtectedCredential (Read-CredentialBytes $AuthFile) (Join-Path $SnapshotDir ($who.Email + '.json'))
    $who
}
function Session-AppProcesses {
    # Other Windows sessions may belong to another signed-in user.
    $session = (Get-Process -Id $PID).SessionId
    @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue |
        Where-Object { $_.SessionId -eq $session })
}
function Stop-App {
    # Stop only the packaged desktop processes.  Do not explicitly kill codex
    # workers: one of them may own the task whose UI is being restarted.
    @(Session-AppProcesses) | Stop-Process -Force
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    while (@(Session-AppProcesses).Count -gt 0) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'ChatGPT did not stop in time' }
        Start-Sleep -Milliseconds 150
    }
}
function Wait-AppWindow([int]$TimeoutSeconds = 25) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $window = @(Session-AppProcesses |
                    Where-Object { $_.MainWindowHandle -ne 0 -and $_.Responding } |
                    Select-Object -First 1)
        if ($window.Count -gt 0) { return }
        Start-Sleep -Milliseconds 250
    }
    throw 'ChatGPT window did not appear after launch'
}
function Start-App {
    # Resolve the real AUMID from Start Apps so other install channels work;
    # the packaged default stays as a fallback for locked-down machines.
    $aumid = $AppAumid
    try {
        $entry = @(Get-StartApps -ErrorAction Stop | Where-Object { $_.Name -eq 'ChatGPT' } | Select-Object -First 1)
        if ($entry.Count -gt 0 -and $entry[0].AppID) { $aumid = [string]$entry[0].AppID }
    } catch { }
    $neutralDir = if ($env:WINDIR) { $env:WINDIR } else { $env:SystemRoot }
    # Explorer is the application broker: ChatGPT neither inherits this helper's
    # lifetime nor keeps the ChatGPTnx project directory as its working directory.
    Start-Process -FilePath explorer.exe -ArgumentList ('shell:AppsFolder\' + $aumid) `
        -WorkingDirectory $neutralDir -ErrorAction Stop
    Wait-AppWindow
}
function Resolve-Target([string]$Name) {
    if ($Name -notmatch '^[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+$') { throw 'invalid target' }
    $path = Join-Path $SnapshotDir ($Name + '.json')
    if (-not (Test-Path -LiteralPath $path)) { throw 'snapshot not found' }
    $id = Read-Identity $path
    if ($id.Email -ine $Name) { throw 'target email does not match snapshot' }
    $path
}

if ($RestoreProjects -and ($To -or $Snapshot -or $Park -or $List)) { throw 'RestoreProjects cannot be combined with an account operation' }
if ($List -or (-not $To -and -not $Snapshot -and -not $Park -and -not $RestoreProjects)) {
    if (Test-Path -LiteralPath $AuthFile) { (Read-Identity $AuthFile).Email }
    Get-ChildItem -LiteralPath $SnapshotDir -Filter '*.json' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.BaseName }
    exit 0
}
$target = $null
if ($To) { $target = Resolve-Target $To }
if ($RestoreProjects) { $target = $AuthFile; $null = Read-Identity $target }
if ($DryRun) {
    Write-Output 'Dry run: validated arguments; no files, processes, or credentials changed.'
    exit 0
}
# Fail a genuine layout conflict while the current account and desktop are intact.
# Preserve-LocalWorkspace repeats this check after exit to cover concurrent changes.
if ($To -or $RestoreProjects) { Assert-WorkspaceTransfer $target }
Assert-SafePath $SnapshotDir
Assert-SafePath $AuthFile
[IO.Directory]::CreateDirectory($SnapshotDir) | Out-Null
Protect-Path $SnapshotDir
$lockPath = Join-Path $SnapshotDir '.credentials.lock'
Assert-SafePath $lockPath
try { $storeLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
catch { throw 'Credential store is busy; retry after the current operation finishes' }
try {
if ($Snapshot) { $null = Save-Snapshot; Write-Output 'Snapshot saved.'; exit 0 }

# Recovery copies stay encrypted and are never automatically deleted.
Assert-SafePath $DataDir
[IO.Directory]::CreateDirectory($DataDir) | Out-Null
Protect-Path $DataDir
$backup = Join-Path $DataDir ('auth-recovery-' + [guid]::NewGuid().ToString('N') + '.json')
$hadAuth = Test-Path -LiteralPath $AuthFile
$authChanged = $false
$appStopped = $false
$launchAttempted = $false
$workspaceTransaction = $null
try {
    if ($hadAuth) {
        $null = Read-Identity $AuthFile  # refuse destructive operations if unreadable
        if (-not $RestoreProjects) { Write-ProtectedCredential (Read-CredentialBytes $AuthFile) $backup }
    }
    Stop-App
    $appStopped = $true
    # Refresh snapshot only after the desktop process has stopped writing.
    if (Test-Path -LiteralPath $AuthFile) {
        if ($RestoreProjects) { $null = Read-Identity $AuthFile }
        else {
            $null = Save-Snapshot
            Write-ProtectedCredential (Read-CredentialBytes $AuthFile) $backup
        }
        $hadAuth = $true
    }
    if ($Park) {
        if (Test-Path -LiteralPath $AuthFile) {
            Assert-SafePath $AuthFile
            Remove-Item -LiteralPath $AuthFile -Force
            $authChanged = $true
        }
    } elseif (-not $RestoreProjects) {
        Atomic-Copy $target $AuthFile
        $authChanged = $true
        $actual = Read-Identity $AuthFile
        $wanted = Read-Identity $target
        if ($actual.AccountId -ne $wanted.AccountId -or $actual.Email -ine $wanted.Email) {
            throw 'identity verification failed'
        }
    }
    if (-not $Park) {
        $workspaceTransaction = Preserve-LocalWorkspace $target (Join-Path $DataDir 'desktop-workspace-recovery.json')
    }
    $launchAttempted = $true
    Start-App
} catch {
    $failure = $_
    try {
        if ($authChanged -or $workspaceTransaction) {
            # A failed stop must never be swallowed: a running desktop could
            # have renewed its token, making a backup stale at this moment.
            Stop-App
            if ($workspaceTransaction) {
                $stateNow = [IO.File]::ReadAllBytes($workspaceTransaction.Path)
                Replace-WorkspaceBytes (Read-CredentialBytes $workspaceTransaction.Backup) $workspaceTransaction.Path $stateNow
            }
            if ($authChanged -and $hadAuth -and (Test-Path -LiteralPath $backup)) {
                Atomic-Copy $backup $AuthFile
            } elseif ($authChanged -and -not $hadAuth) {
                Assert-SafePath $AuthFile
                if (Test-Path -LiteralPath $AuthFile) { Remove-Item -LiteralPath $AuthFile -Force }
            } elseif ($authChanged) { throw 'Recovery credential missing' }
            Start-App
        } elseif ($appStopped -and -not $launchAttempted) {
            # Snapshot/encryption failed before auth mutation; restart with the
            # untouched original bytes, without any rollback write.
            Start-App
        }
    } catch {
        Write-Error 'Rollback incomplete. Keep snapshots/recovery/auth-recovery-*.json private for manual recovery.' -ErrorAction Continue
    }
    throw $failure
}
Write-Output 'Local credential operation completed; application launch requested.'
} finally { $storeLock.Dispose() }
