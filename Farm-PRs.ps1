$ErrorActionPreference = "Stop"

# Quantidade de PRs (48 PRs é o suficiente para o nível Ouro)
$TotalPRs = 48

$IntervaloEntrePRs = 10
$IntervaloEntreChamadas = 1

$MockFile = "data_feed_telemetry.csv"

# Conta SECUNDÁRIA (Quem executa e envia o PR)
$AuthorName = "ineedfoundmyway"
$AuthorEmail = "335617621+notalkonlyxtc@users.noreply.github.com"

# Conta PRINCIPAL (Quem recebe a medalha Pair Extraordinaire)
$CoAuthorTag = "Co-authored-by: brunnojob <contato@brunnodev.store>"

function Invoke-Checked {
    param(
        [string]$Program,
        [string[]]$Arguments
    )

    if ($Program -eq "gh") {
        Start-Sleep -Seconds $IntervaloEntreChamadas
    }

    & $Program @Arguments
    $ExitCode = $LASTEXITCODE

    if ($ExitCode -ne 0) {
        throw @"
$Program falhou com código $ExitCode.
A automação foi interrompida.
"@
    }
}

$MessageFile = [System.IO.Path]::GetTempFileName()
$BodyFile = [System.IO.Path]::GetTempFileName()

try {
    Write-Host "Verificando autenticação no GitHub CLI..." -ForegroundColor Cyan
    Invoke-Checked "gh" @("auth", "status")

    Write-Host "Repositório de destino:" -ForegroundColor Cyan
    Invoke-Checked "git" @("remote", "get-url", "origin")

    # Configura a identidade local no repositório para a conta SECUNDÁRIA
    Invoke-Checked "git" @("config", "--local", "user.name", $AuthorName)
    Invoke-Checked "git" @("config", "--local", "user.email", $AuthorEmail)

    Write-Host "Autor do Commit: $AuthorName <$AuthorEmail>" -ForegroundColor Cyan
    Write-Host "Coautor (Ganha a Badge): brunnojob <contato@brunnodev.store>" -ForegroundColor Green

    # Limpeza/Verificação da árvore de trabalho
    Invoke-Checked "git" @("diff", "--exit-code")
    Invoke-Checked "git" @("diff", "--cached", "--exit-code")

    Write-Host "Iniciando $TotalPRs PRs com coautoria..." -ForegroundColor Cyan

    for ($i = 1; $i -le $TotalPRs; $i++) {
        $SessionID = [guid]::NewGuid().ToString("N")
        $BranchName = "telemetry-update-$SessionID"

        Invoke-Checked "git" @("switch", "main")
        Invoke-Checked "git" @("pull", "--ff-only", "origin", "main")
        Invoke-Checked "git" @("switch", "-c", $BranchName)

        if (-not (Test-Path -LiteralPath $MockFile)) {
            $Header = "SessionID,Timestamp,SensorStatus"
            Set-Content -LiteralPath $MockFile -Value $Header -Encoding UTF8
        }

        $TimeLog = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $NewRow = "$SessionID,$TimeLog,OK"

        Add-Content -LiteralPath $MockFile -Value $NewRow -Encoding UTF8

        Write-Host "[$i/$TotalPRs] Gerando entrada de dados: $NewRow" -ForegroundColor Yellow

        $CommitMessage = @"
chore(telemetry): update sensor readings log $SessionID

Simulated telemetry ping for IoT data ingestion test.

$CoAuthorTag
"@

        Set-Content -LiteralPath $MessageFile -Value $CommitMessage -Encoding UTF8

        Invoke-Checked "git" @("add", "--", $MockFile)

        Invoke-Checked "git" @(
            "commit",
            "--author", "$AuthorName <$AuthorEmail>",
            "-F", $MessageFile
        )

        $HeadSha = Invoke-Checked "git" @("rev-parse", "HEAD")
        $HeadSha = "$HeadSha".Trim()

        Invoke-Checked "git" @("push", "-u", "origin", $BranchName)

        $PRTitle = "chore(telemetry): update sensor readings log $SessionID"
        $PRBody = "Automated PR from $AuthorName with co-authorship assigned to brunnojob."

        Set-Content -LiteralPath $BodyFile -Value $PRBody -Encoding UTF8

        $PRUrl = Invoke-Checked "gh" @(
            "pr", "create",
            "--title", $PRTitle,
            "--body-file", $BodyFile,
            "--base", "main",
            "--head", $BranchName
        )

        $PRUrl = "$PRUrl".Trim()
        Write-Host "PR criado: $PRUrl" -ForegroundColor Cyan

        # Faz o merge do PR
        Invoke-Checked "gh" @(
            "pr", "merge", $PRUrl,
            "--merge",
            "--delete-branch",
            "--match-head-commit", $HeadSha
        )

        Invoke-Checked "git" @("switch", "main")
        Invoke-Checked "git" @("pull", "--ff-only", "origin", "main")

        Write-Host "PR $i de $TotalPRs mesclado com sucesso!" -ForegroundColor Green

        if ($i -lt $TotalPRs) {
            Write-Host "Aguardando $IntervaloEntrePRs segundos..." -ForegroundColor Cyan
            Start-Sleep -Seconds $IntervaloEntrePRs
        }
    }

    Write-Host "Execução concluída com sucesso!" -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $MessageFile -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $BodyFile -ErrorAction SilentlyContinue
}