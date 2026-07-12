param(
    [string]$Url = $env:AGENT_BUS_URL,
    [string]$Token = $env:AGENT_BUS_TOKEN,
    [string]$Agent = $(if ($env:AGENT_BUS_AGENT) { $env:AGENT_BUS_AGENT } else { "coder" }),
    [string]$OnTaskNew = 'powershell -NoProfile -Command "Write-Output Agent Bus received {payload.task_id}"',
    [int]$PollSeconds = 2,
    [string]$Workdir,
    [switch]$Once
)

$ErrorActionPreference = "Stop"

if (-not $Url) { throw "AGENT_BUS_URL or -Url is required" }
if (-not $Token) { throw "AGENT_BUS_TOKEN or -Token is required" }

# -Workdir is a local static config: the path is never taken from a remote
# payload. If payload.repo / payload.workdir routing is added later, it must be
# resolved through a local whitelist map, never by trusting a remote absolute
# path directly.
if ($Workdir) {
    if (-not (Test-Path -LiteralPath $Workdir)) {
        throw "Workdir does not exist: $Workdir"
    }
    if (-not (Test-Path -LiteralPath $Workdir -PathType Container)) {
        throw "Workdir is not a directory: $Workdir"
    }
    $Workdir = (Resolve-Path -LiteralPath $Workdir).ProviderPath
}

$Url = $Url.TrimEnd("/")
$Headers = @{
    Authorization = "Bearer $Token"
    "Content-Type" = "application/json"
}

function Get-EventValue {
    param(
        [Parameter(Mandatory = $true)] $Event,
        [Parameter(Mandatory = $true)] [string] $Path
    )

    $current = $Event
    foreach ($part in $Path.Split(".")) {
        if ($null -eq $current) { throw "Missing template field: {$Path}" }

        $property = $current.PSObject.Properties[$part]
        if ($null -eq $property) { throw "Missing template field: {$Path}" }
        $current = $property.Value
    }

    if ($null -eq $current) { return "" }
    return [string]$current
}

function ConvertTo-CmdArgument {
    param([string]$Value)

    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Render-Command {
    param(
        [string] $Template,
        $Event
    )

    $rendered = $Template
    $matches = [regex]::Matches($Template, "\{([^{}]+)\}")
    foreach ($match in $matches) {
        $path = $match.Groups[1].Value.Trim()
        $value = ConvertTo-CmdArgument (Get-EventValue -Event $Event -Path $path)
        $rendered = $rendered.Replace($match.Value, $value)
    }
    return $rendered
}

function Ack-Event {
    param([int]$EventId)

    Invoke-RestMethod -Method Post -Uri "$Url/events/$EventId/ack" -Headers $Headers | Out-Null
    Write-Host "ACK id=$EventId"
}

Write-Host "Agent Bus Windows polling listener"
Write-Host "agent=$Agent url=$Url poll=${PollSeconds}s workdir=$(if ($Workdir) { $Workdir } else { '<inherit>' })"

while ($true) {
    $events = Invoke-RestMethod -Method Get -Uri "$Url/events/pending?agent=$Agent" -Headers $Headers

    foreach ($event in $events) {
        $taskId = $event.payload.task_id
        Write-Host "event id=$($event.id) type=$($event.type) task_id=$taskId"

        if ($event.type -ne "task:new") {
            Write-Host "skip id=$($event.id): no handler for type=$($event.type)"
            continue
        }

        try {
            $command = Render-Command -Template $OnTaskNew -Event $event
            Write-Host "handler start: $command"
            if ($Workdir) { Push-Location -LiteralPath $Workdir }
            try {
                cmd.exe /d /s /c $command
                $exitCode = $LASTEXITCODE
            } finally {
                if ($Workdir) { Pop-Location }
            }
            Write-Host "handler exit_code=$exitCode"

            if ($exitCode -eq 0) {
                Ack-Event -EventId $event.id
            } else {
                Write-Host "leave unacked id=$($event.id)"
            }
        } catch {
            Write-Host "handler error id=$($event.id): $($_.Exception.Message)"
            Write-Host "leave unacked id=$($event.id)"
        }
    }

    if ($Once) { break }
    Start-Sleep -Seconds $PollSeconds
}
