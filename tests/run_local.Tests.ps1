<#
  Pester tests for the FretWise launcher helpers (scripts\pixi-helpers.ps1).

  Run:  Invoke-Pester -Path tests\run_local.Tests.ps1
  (Pester 3.4 — the version bundled with Windows PowerShell — is sufficient.)

  Only the helper file is dot-sourced, NOT run_local.ps1, so importing it here
  never starts the web server.
#>

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $here '..\scripts\pixi-helpers.ps1')

Describe 'Test-IsBenignPixiEnvLine' {

    It 'matches the real (French-locale) os-error-183 envs-already-exists line' {
        # Verbatim from the field report; here-string keeps quotes/backticks literal.
        $line = @'
ERROR Failed to create directory 'E:\pythonProject\fretwise\.pixi\envs': failed to create directory `E:\pythonProject\fretwise\.pixi\envs`: Impossible de creer un fichier deja existant. (os error 183)
'@
        Test-IsBenignPixiEnvLine $line | Should Be $true
    }

    It 'matches an English-locale variant of the same error' {
        $line = "ERROR Failed to create directory 'C:\proj\.pixi\envs': ... Cannot create a file when that file already exists. (os error 183)"
        Test-IsBenignPixiEnvLine $line | Should Be $true
    }

    It 'matches regardless of forward/back slashes in the envs path' {
        Test-IsBenignPixiEnvLine 'Failed to create directory: /home/u/proj/.pixi/envs (os error 183)' | Should Be $true
    }

    It 'does NOT match a different pixi failure (real error must pass through)' {
        Test-IsBenignPixiEnvLine 'ERROR failed to solve the environment: package not found' | Should Be $false
    }

    It 'does NOT match a normal uvicorn server log line' {
        Test-IsBenignPixiEnvLine 'INFO:     Uvicorn running on http://localhost:8080 (Press CTRL+C to quit)' | Should Be $false
    }

    It 'does NOT match an os-error-183 unrelated to the .pixi\envs directory' {
        # Same Windows error code, different directory — must NOT be silenced.
        Test-IsBenignPixiEnvLine "Failed to create directory 'C:\some\other\path' (os error 183)" | Should Be $false
    }

    It 'does NOT match a .pixi\envs create-failure with a different error code' {
        Test-IsBenignPixiEnvLine "Failed to create directory '.pixi\envs' (os error 5)" | Should Be $false
    }

    It 'returns false for empty / whitespace input' {
        Test-IsBenignPixiEnvLine ''    | Should Be $false
        Test-IsBenignPixiEnvLine '   ' | Should Be $false
    }
}
