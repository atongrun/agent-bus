param(
    [string]$Url = $env:AGENT_BUS_URL,
    [string]$Token = $env:AGENT_BUS_TOKEN,
    [string]$Agent = $(if ($env:AGENT_BUS_AGENT) { $env:AGENT_BUS_AGENT } else { "receiver" }),
    [string]$Command = "powershell",
    [string[]]$CommandArgs = @("-NoProfile", "-Command", "Write-Output 'Agent Bus received task'; Write-Output `$args[0]"),
    [int]$PollSeconds = 2,
    [switch]$Once
)

$ErrorActionPreference = "Stop"

if (-not $Url) { throw "AGENT_BUS_URL or -Url is required" }
if (-not $Token) { throw "AGENT_BUS_TOKEN or -Token is required" }

$Url = $Url.TrimEnd("/")
$Headers = @{
    Authorization = "Bearer $Token"
    "Content-Type" = "application/json"
}

function Ack-Event {
    param([int]$EventId)

    Invoke-RestMethod -Method Post -Uri "$Url/events/$EventId/ack" -Headers $Headers | Out-Null
    Write-Host "ACK id=$EventId"
}

function Invoke-TaskHandler {
    param($Event)

    $prompt = ""
    if ($null -ne $Event.payload -and $null -ne $Event.payload.prompt) {
        $prompt = [string]$Event.payload.prompt
    }

    Write-Host "handler start: $Command $($CommandArgs -join ' ') <payload.prompt>"
    $global:LASTEXITCODE = 0
    & $Command @CommandArgs $prompt

    if ($null -eq $LASTEXITCODE) { return 0 }
    return [int]$LASTEXITCODE
}

Write-Host "Agent Bus Windows polling adapter"
Write-Host "agent=$Agent url=$Url poll=${PollSeconds}s"

while ($true) {
    $events = @(Invoke-RestMethod -Method Get -Uri "$Url/events/pending?agent=$Agent" -Headers $Headers)

    foreach ($event in $events) {
        $taskId = ""
        if ($null -ne $event.payload -and $null -ne $event.payload.task_id) {
            $taskId = [string]$event.payload.task_id
        }

        Write-Host "event id=$($event.id) type=$($event.type) task_id=$taskId"

        if ($event.type -ne "task:new") {
            Write-Host "skip id=$($event.id): no handler for type=$($event.type)"
            continue
        }

        try {
            $exitCode = Invoke-TaskHandler -Event $event
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
