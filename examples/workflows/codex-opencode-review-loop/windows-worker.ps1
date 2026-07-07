param(
    [Parameter(Mandatory = $true)]
    [string]$Workdir,

    [string]$ReviewerAgent = $env:AGENT_BUS_REVIEWER_AGENT,
    [string]$ArtifactUri = $env:AGENT_BUS_ARTIFACT_URI,
    [switch]$Once
)

$ErrorActionPreference = "Stop"

$poller = Join-Path $PSScriptRoot "..\..\windows\poll-listener.ps1"
if (-not (Test-Path -LiteralPath $poller -PathType Leaf)) {
    throw "Windows polling adapter not found: $poller"
}

$params = @{
    Workdir = $Workdir
    Command = "opencode"
    CommandArgs = @("run", "--prompt")
}

if ($ReviewerAgent) {
    $params["CompletionTo"] = $ReviewerAgent
}

if ($ArtifactUri) {
    $params["ArtifactUri"] = $ArtifactUri
}

& $poller @params -Once:$Once
