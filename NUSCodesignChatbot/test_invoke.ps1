<#
.SYNOPSIS
  Invoke the deployed chatbot_harnessAgent runtime for a given phase/topic and print the reply.

.EXAMPLE
  .\test_invoke.ps1 -Prompt "When is the final project due?" -Phase qa -SessionId my-test-session-aaaaaaaaaa

.EXAMPLE
  .\test_invoke.ps1 -Prompt "Everyone will love a mobile app for this" -Phase coaching -Topic concept_generation -SessionId my-test-session-aaaaaaaaaa

.EXAMPLE
  .\test_invoke.ps1 -Prompt "Score my thinking so far" -Phase scoring -SessionId my-test-session-aaaaaaaaaa

.NOTES
  Reuse the same -SessionId across calls to test that history carries across phase switches.
  SessionId must be at least 33 characters (AWS requirement) -- pad short ones with "a"s if needed.
  -StudentId sets the AgentCore Memory actor_id (per-student history scope). Omit it and history
  falls back to being scoped by -SessionId alone (anonymous/test use).
#>
param(
    [Parameter(Mandatory = $true)][string]$Prompt,
    [Parameter(Mandatory = $true)][ValidateSet("qa", "coaching", "scoring")][string]$Phase,
    [string]$Topic,
    [string]$SessionId = ("test-session-" + [guid]::NewGuid().ToString("N")),
    [string]$StudentId,
    [string]$AgentRuntimeArn = "arn:aws:bedrock-agentcore:us-west-2:355604674280:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7",
    [string]$Region = "us-west-2",
    [string]$AwsCli = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
)

$ErrorActionPreference = "Stop"

# AWS requires runtimeSessionId to be at least 33 characters.
if ($SessionId.Length -lt 33) {
    $SessionId = $SessionId.PadRight(33, "a")
}

$payloadObj = [ordered]@{ prompt = $Prompt; phase = $Phase }
if ($Topic) { $payloadObj.topic = $Topic }
if ($StudentId) { $payloadObj.student_id = $StudentId }

$payloadFile = New-TemporaryFile
$responseFile = New-TemporaryFile
try {
    ($payloadObj | ConvertTo-Json -Compress) | Out-File -FilePath $payloadFile -Encoding utf8 -NoNewline

    & $AwsCli bedrock-agentcore invoke-agent-runtime `
        --agent-runtime-arn $AgentRuntimeArn `
        --payload "fileb://$payloadFile" `
        --runtime-session-id $SessionId `
        --region $Region `
        $responseFile | Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "aws invoke-agent-runtime failed with exit code $LASTEXITCODE"
    }

    Write-Host "Session: $SessionId" -ForegroundColor Cyan
    Write-Host "Phase:   $Phase$(if ($Topic) { " / $Topic" })" -ForegroundColor Cyan
    Write-Host "---" -ForegroundColor DarkGray

    $reply = New-Object System.Text.StringBuilder
    Get-Content $responseFile | ForEach-Object {
        if ($_ -like "data: {*") {
            $json = $_.Substring(6) | ConvertFrom-Json
            $text = $json.event.contentBlockDelta.delta.text
            if ($text) { [void]$reply.Append($text) }
        }
    }
    Write-Host $reply.ToString()
}
finally {
    Remove-Item $payloadFile, $responseFile -ErrorAction SilentlyContinue
}
