<#
.SYNOPSIS
  Shared helpers for the FretWise PowerShell launchers (run.ps1 / run_local.ps1).
.DESCRIPTION
  Kept in a side file (not inside a launcher) so it can be dot-sourced by Pester
  tests WITHOUT starting the web server. See tests\run_local.Tests.ps1.
#>

function Test-IsBenignPixiEnvLine {
    <#
    .SYNOPSIS
      True if a pixi output line is the harmless "`.pixi\envs` already exists" error.
    .DESCRIPTION
      On Windows, `pixi run` sometimes tries to (re)create the environments
      directory that already exists and prints a NON-FATAL line such as:

        ERROR Failed to create directory 'X:\...\.pixi\envs': failed to create
        directory `X:\...\.pixi\envs`: Impossible de créer un fichier déjà
        existant. (os error 183)

      `os error 183` is Windows ERROR_ALREADY_EXISTS. The environment is intact
      and the app still launches, so this single line is pure noise that alarms
      users. We match on the language-independent markers only (the localized
      "Impossible de créer…" text is ignored), so it works on any OS locale.
    .OUTPUTS
      [bool]
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory, ValueFromPipeline)]
        [AllowEmptyString()]
        [AllowNull()]
        [string]$Line
    )
    process {
        if ([string]::IsNullOrWhiteSpace($Line)) { return $false }
        $isCreateFailure = $Line -match 'Failed to create directory'
        $isEnvsDir       = $Line -match '\.pixi[\\/]+envs'
        $isAlreadyExists = $Line -match 'os error 183'
        return [bool]($isCreateFailure -and $isEnvsDir -and $isAlreadyExists)
    }
}
