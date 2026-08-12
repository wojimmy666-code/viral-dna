from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_windows_launcher_restarts_only_a_stale_viral_dna_api() -> None:
    launcher = (REPOSITORY_ROOT / "scripts" / "start.bat").read_text("utf-8")
    detector = (REPOSITORY_ROOT / "scripts" / "api-service-state.ps1").read_text("utf-8")

    assert "api-service-state.ps1" in launcher
    assert "-Mode check" in launcher
    assert "-Mode stop-stale" in launcher
    assert 'if "%API_STATE%"=="2"' in launcher
    assert 'if "%API_STATE%"=="3"' in launcher

    assert "workspace_schema_version" in detector
    assert "process_started_at" in detector
    assert "Get-LatestApiSourceWriteTimeUtc" in detector
    assert 'health.service -ne "viral-dna-api"' in detector
    assert 'commandLine -notmatch "uvicorn"' in detector
    assert 'commandLine -notmatch "viral_dna_api\\.main:app"' in detector
    assert "Stop-Process -Id $listenerProcessId" in detector
