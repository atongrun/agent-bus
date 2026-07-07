param(
    [string]$Url = $env:AGENT_BUS_URL,
    [string]$Token = $env:AGENT_BUS_TOKEN,
    [string]$Agent = $(if ($env:AGENT_BUS_AGENT) { $env:AGENT_BUS_AGENT } else { "receiver" }),
    [string]$CompletionTo = $env:AGENT_BUS_COMPLETION_TO,
    [string]$ArtifactUri = $env:AGENT_BUS_ARTIFACT_URI,
    [string]$Command = "powershell",
    [string[]]$CommandArgs = @("-NoProfile", "-Command", "Write-Output 'Agent Bus received task'; Write-Output `$args[0]"),
    [string]$Workdir,
    [int]$PollSeconds = 2,
    [switch]$Once
)

$ErrorActionPreference = "Stop"

if (-not $Url) { throw "AGENT_BUS_URL or -Url is required" }
if (-not $Token) { throw "AGENT_BUS_TOKEN or -Token is required" }

# -Workdir is local static adapter config. Never take a local filesystem path
# directly from a remote payload; add a local whitelist map before routing repos.
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

function Get-PayloadText {
    param(
        $Event,
        [string]$Name
    )

    if ($null -eq $Event.payload) { return "" }
    $property = $Event.payload.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) { return "" }
    return [string]$property.Value
}

function Get-ReplyAgent {
    param($Event)

    if ($CompletionTo) { return $CompletionTo }

    $requester = Get-PayloadText -Event $Event -Name "requester"
    if ($requester) { return $requester }

    if ($Event.from_agent) { return [string]$Event.from_agent }

    throw "No completion recipient available; set -CompletionTo or payload.requester"
}

function Ack-Event {
    param([int]$EventId)

    Invoke-RestMethod -Method Post -Uri "$Url/events/$EventId/ack" -Headers $Headers | Out-Null
    Write-Host "ACK id=$EventId"
}

function Send-AgentBusEvent {
    param(
        [string]$ToAgent,
        [string]$Type,
        [hashtable]$Payload
    )

    $body = @{
        from_agent = $Agent
        to_agent = $ToAgent
        type = $Type
        payload = $Payload
    } | ConvertTo-Json -Depth 8

    Invoke-RestMethod -Method Post -Uri "$Url/events" -Headers $Headers -Body $body | Out-Null
    Write-Host "sent type=$Type to=$ToAgent task_id=$($Payload["task_id"])"
}

function New-ResultPayload {
    param(
        $Event,
        [string]$Status,
        [string]$Summary,
        [string]$ErrorMessage = "",
        [int]$ExitCode = 0
    )

    $payload = @{
        task_id = Get-PayloadText -Event $Event -Name "task_id"
        status = $Status
        repo = Get-PayloadText -Event $Event -Name "repo"
        branch = Get-PayloadText -Event $Event -Name "branch"
    }

    if ($Status -eq "completed") {
        $payload["summary"] = $Summary
        $payload["artifact_uri"] = $ArtifactUri
    } else {
        $payload["error"] = $ErrorMessage
        $payload["exit_code"] = $ExitCode
    }

    return $payload
}

function Invoke-TaskHandler {
    param($Event)

    $prompt = Get-PayloadText -Event $Event -Name "prompt"

    Write-Host "handler start: $Command $($CommandArgs -join ' ') <payload.prompt>"
    if ($Workdir) { Push-Location -LiteralPath $Workdir }
    try {
        $global:LASTEXITCODE = 0
        & $Command @CommandArgs $prompt

        if ($null -eq $LASTEXITCODE) { return 0 }
        return [int]$LASTEXITCODE
    } finally {
        if ($Workdir) { Pop-Location }
    }
}

Write-Host "Agent Bus Windows polling adapter"
Write-Host "agent=$Agent url=$Url poll=${PollSeconds}s workdir=$(if ($Workdir) { $Workdir } else { '<inherit>' })"

while ($true) {
    $encodedAgent = [uri]::EscapeDataString($Agent)
    $events = @(Invoke-RestMethod -Method Get -Uri "$Url/events/pending?agent=$encodedAgent" -Headers $Headers)

    foreach ($event in $events) {
        $taskId = Get-PayloadText -Event $event -Name "task_id"
        Write-Host "event id=$($event.id) type=$($event.type) task_id=$taskId"

        if ($event.type -ne "task:new") {
            Write-Host "skip id=$($event.id): no handler for type=$($event.type)"
            continue
        }

        try {
            $replyTo = Get-ReplyAgent -Event $event
            $exitCode = Invoke-TaskHandler -Event $event
            Write-Host "handler exit_code=$exitCode"

            if ($exitCode -eq 0) {
                $completed = New-ResultPayload -Event $event -Status "completed" -Summary "Command exited 0"
                Send-AgentBusEvent -ToAgent $replyTo -Type "task:completed" -Payload $completed
                Ack-Event -EventId $event.id
            } else {
                $errorText = "Command exited $exitCode"
                $failed = New-ResultPayload -Event $event -Status "failed" -ErrorMessage $errorText -ExitCode $exitCode
                Send-AgentBusEvent -ToAgent $replyTo -Type "task:failed" -Payload $failed
                Write-Host "leave unacked id=$($event.id)"
            }
        } catch {
            Write-Host "handler error id=$($event.id): $($_.Exception.Message)"
            try {
                $replyTo = Get-ReplyAgent -Event $event
                $failed = New-ResultPayload -Event $event -Status "failed" -ErrorMessage $_.Exception.Message -ExitCode -1
                Send-AgentBusEvent -ToAgent $replyTo -Type "task:failed" -Payload $failed
            } catch {
                Write-Host "could not send task:failed id=$($event.id): $($_.Exception.Message)"
            }
            Write-Host "leave unacked id=$($event.id)"
        }
    }

    if ($Once) { break }
    Start-Sleep -Seconds $PollSeconds
}
