# PowerShell script to test chatbot performance
# Run: .\test_performance.ps1

Write-Host "=== Campus Store Chatbot Performance Tests ===" -ForegroundColor Yellow
Write-Host ""

# Test 1: Retrieval Speed
Write-Host "Test 1: Retrieval Speed (instructions + platform filter)" -ForegroundColor Cyan
$retrievalBody = @{
    message = "I cannot access McGraw Hill Connect"
} | ConvertTo-Json

try {
    $retrievalResult = Invoke-RestMethod -Uri "http://127.0.0.1:8000/debug/retrieval-only" `
        -Method POST `
        -ContentType "application/json" `
        -Body $retrievalBody
    
    Write-Host "  ✓ Elapsed: $($retrievalResult.elapsed_ms) ms" -ForegroundColor Green
    Write-Host "  ✓ Source: $($retrievalResult.source)" -ForegroundColor Green
    Write-Host "  ✓ Score: $($retrievalResult.score)" -ForegroundColor Green
    
    if ($retrievalResult.elapsed_ms -lt 500) {
        Write-Host "  ✓ PASS: Retrieval is fast!" -ForegroundColor Green
    }
    else {
        Write-Host "  ⚠ SLOW: Retrieval took longer than expected" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "  ✗ FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 2: LLM Speed
Write-Host "Test 2: LLM Generation Speed" -ForegroundColor Cyan
$llmBody = @{
    message = "Hello, how are you?"
} | ConvertTo-Json

try {
    $llmResult = Invoke-RestMethod -Uri "http://127.0.0.1:8000/debug/llm-only" `
        -Method POST `
        -ContentType "application/json" `
        -Body $llmBody
    
    Write-Host "  ✓ Elapsed: $($llmResult.elapsed_seconds) seconds" -ForegroundColor Green
    Write-Host "  ✓ Reply length: $($llmResult.reply_length) chars" -ForegroundColor Green
    
    if ($llmResult.elapsed_seconds -lt 10) {
        Write-Host "  ✓ PASS: LLM speed is normal for CPU" -ForegroundColor Green
    }
    else {
        Write-Host "  ⚠ SLOW: LLM is taking longer than expected" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "  ✗ FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 3: Session Stats
Write-Host "Test 3: Active Sessions" -ForegroundColor Cyan
try {
    $sessionStats = Invoke-RestMethod -Uri "http://127.0.0.1:8000/sessions/stats" `
        -Method GET
    
    Write-Host "  ✓ Active sessions: $($sessionStats.active_sessions)" -ForegroundColor Green
    
    foreach ($session in $sessionStats.sessions) {
        Write-Host "    - Session $($session.id): $($session.history_length) messages, age: $([math]::Round($session.age_minutes, 1))m" -ForegroundColor Gray
    }
}
catch {
    Write-Host "  ✗ FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""

# Test 4: Full Chat Request (McGraw Hill)
Write-Host "Test 4: Full Chat Request (McGraw Hill Platform Filter)" -ForegroundColor Cyan
$chatBody = @{
    message = "I can't access my McGraw Hill Connect textbook"
    session_id = "test-session-" + (Get-Random)
} | ConvertTo-Json

try {
    $startTime = Get-Date
    $chatResult = Invoke-RestMethod -Uri "http://127.0.0.1:8000/chat" `
        -Method POST `
        -ContentType "application/json" `
        -Body $chatBody
    $endTime = Get-Date
    $elapsed = ($endTime - $startTime).TotalSeconds
    
    Write-Host "  ✓ Total elapsed: $([math]::Round($elapsed, 2)) seconds" -ForegroundColor Green
    Write-Host "  ✓ Source: $($chatResult.source)" -ForegroundColor Green
    Write-Host "  ✓ Confidence: $($chatResult.confidence)" -ForegroundColor Green
    
    if ($chatResult.source -like "INSTR_MCGRAW*") {
        Write-Host "  ✓ PASS: Correctly routed to McGraw Hill instructions" -ForegroundColor Green
    }
    elseif ($chatResult.source -like "FAQ*") {
        Write-Host "  ✗ FAIL: Incorrectly routed to FAQs (should be instructions)" -ForegroundColor Red
    }
    else {
        Write-Host "  ⚠ WARNING: Unexpected source type" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "  ✗ FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Tests Complete ===" -ForegroundColor Yellow