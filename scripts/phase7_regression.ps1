Write-Host "Running Lance Phase 7 milestone regression..." -ForegroundColor Cyan

# --basetemp redirects pytest tmp_path away from the system temp directory.
# Required on this machine: the system temp (C:\Users\CMInter1\AppData\Local\Temp\pytest-of-CMInter1)
# has locked permissions from a previous process and cannot be recreated by the current user.
$basetemp = "--basetemp=.pytest_tmp"

python -m pytest tests/test_safety_filter.py tests/test_chat_safety_integration.py tests/test_chat_lifecycle_safety.py -q $basetemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest tests/test_config_loader.py tests/test_api_platforms.py -q $basetemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest tests/test_intake.py -q $basetemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest tests/test_recursive_content_dirs.py tests/test_admin_content_editing.py -q $basetemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest tests/test_feedback.py -q $basetemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest tests/test_metadata_filtering.py tests/test_retrieval_scoring.py tests/test_quick_help_routes.py tests/test_audit_quick_help.py -q $basetemp
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python scripts/audit_quick_help.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Phase 7 milestone regression completed." -ForegroundColor Green
