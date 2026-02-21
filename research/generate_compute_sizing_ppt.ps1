param(
    [string]$CsvPath = "research/compute_systems_llama3_2_sizing.csv",
    [string]$OutPath = "research/compute_systems_llama3_2_sizing_report.pptx"
)

$ErrorActionPreference = "Stop"

function Add-Title {
    param($Slide, [string]$Text)
    $titleBox = $Slide.Shapes.AddTextbox(1, 40, 20, 1200, 50)
    $titleBox.TextFrame.TextRange.Text = $Text
    $titleBox.TextFrame.TextRange.Font.Size = 30
    $titleBox.TextFrame.TextRange.Font.Bold = $true
}

function Add-ChartSlide {
    param(
        $Presentation,
        [string]$Title,
        [int]$ChartType,
        [string[]]$Categories,
        [hashtable]$SeriesMap,
        [string]$YAxisTitle = ""
    )

    # 12 = ppLayoutBlank
    $slide = $Presentation.Slides.Add($Presentation.Slides.Count + 1, 12)
    Add-Title -Slide $slide -Text $Title

    $shape = $slide.Shapes.AddChart2(-1, $ChartType, 60, 90, 1200, 580)
    $chart = $shape.Chart
    $chartData = $chart.ChartData
    $chartData.Activate()

    $wb = $null
    for ($try = 0; $try -lt 10 -and $wb -eq $null; $try++) {
        Start-Sleep -Milliseconds 250
        try {
            $wb = $chartData.Workbook
        } catch {
            $wb = $null
        }
    }
    if ($wb -eq $null) {
        throw "Unable to access chart data workbook for slide: $Title"
    }
    $ws = $wb.Worksheets.Item(1)

    # Header row
    $ws.Cells.Item(1, 1) = "Configuration"
    $seriesNames = @($SeriesMap.Keys)
    for ($i = 0; $i -lt $seriesNames.Count; $i++) {
        $ws.Cells.Item(1, $i + 2) = [string]$seriesNames[$i]
    }

    # Data rows
    for ($r = 0; $r -lt $Categories.Count; $r++) {
        $ws.Cells.Item($r + 2, 1) = [string]$Categories[$r]
        for ($c = 0; $c -lt $seriesNames.Count; $c++) {
            $series = $SeriesMap[$seriesNames[$c]]
            $ws.Cells.Item($r + 2, $c + 2) = [double]$series[$r]
        }
    }

    $lastRow = $Categories.Count + 1
    $lastCol = $seriesNames.Count + 1
    $colLetters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if ($lastCol -gt $colLetters.Length) {
        throw "Too many series columns for current helper logic."
    }
    $endColLetter = $colLetters.Substring($lastCol - 1, 1)
    $rangeAddress = "='Sheet1'!`$A`$1:`$$endColLetter`$$lastRow"
    $chart.SetSourceData($rangeAddress)

    $chart.HasTitle = $false
    $chart.HasLegend = $true

    if ($YAxisTitle -ne "") {
        # 2 = xlValue axis
        $chart.Axes(2).HasTitle = $true
        $chart.Axes(2).AxisTitle.Text = $YAxisTitle
    }

    # Cleanup Excel instance attached to the chart data editor
    $excelApp = $wb.Application
    $wb.Close($false)
    $excelApp.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excelApp)
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ws)
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($wb)
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($chartData)
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($chart)
}

if (-not (Test-Path $CsvPath)) {
    throw "CSV not found: $CsvPath"
}

$rows = Import-Csv $CsvPath
if ($rows.Count -eq 0) {
    throw "CSV has no rows: $CsvPath"
}

$labels = @()
$cost = @()
$totalRps = @()
$p50 = @()
$p95 = @()
$maxConcurrency = @()
$costPerRps = @()

foreach ($r in $rows) {
    $labels += "$($r.gpu_model) x$($r.gpu_count) (target $($r.target_peak_concurrency))"
    $c = [double]$r.estimated_total_price_usd
    $t = [double]$r.total_rps_est
    $cost += $c
    $totalRps += $t
    $p50 += [double]$r.p50_est_s
    $p95 += [double]$r.p95_est_s
    $maxConcurrency += [double]$r.max_peak_concurrency_assumed
    if ($t -gt 0) {
        $costPerRps += [math]::Round($c / $t, 2)
    } else {
        $costPerRps += 0
    }
}

$ppt = $null
try {
    $ppt = New-Object -ComObject PowerPoint.Application
    # -1 = msoTrue
    $ppt.Visible = -1
    $presentation = $ppt.Presentations.Add()

    # Title slide
    # 1 = ppLayoutTitle
    $slide1 = $presentation.Slides.Add(1, 1)
    $slide1.Shapes.Title.TextFrame.TextRange.Text = "Compute Sizing Report: Llama 3.2"
    $slide1.Shapes.Item(2).TextFrame.TextRange.Text = "Source: compute_systems_llama3_2_sizing.csv`nGenerated: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

    Add-ChartSlide -Presentation $presentation -Title "Estimated Total Cost by Configuration" -ChartType 51 -Categories $labels -SeriesMap ([ordered]@{
        "Estimated Cost (USD)" = $cost
    }) -YAxisTitle "USD"

    Add-ChartSlide -Presentation $presentation -Title "Estimated Throughput by Configuration" -ChartType 51 -Categories $labels -SeriesMap ([ordered]@{
        "Total RPS (est)" = $totalRps
    }) -YAxisTitle "Requests / sec"

    Add-ChartSlide -Presentation $presentation -Title "Latency Comparison (p50 vs p95)" -ChartType 4 -Categories $labels -SeriesMap ([ordered]@{
        "p50 (s)" = $p50
        "p95 (s)" = $p95
    }) -YAxisTitle "Seconds"

    Add-ChartSlide -Presentation $presentation -Title "Max Peak Concurrency (Assumed) by Configuration" -ChartType 51 -Categories $labels -SeriesMap ([ordered]@{
        "Max Peak Concurrency" = $maxConcurrency
    }) -YAxisTitle "Concurrent users"

    Add-ChartSlide -Presentation $presentation -Title "Cost Efficiency (USD per RPS)" -ChartType 51 -Categories $labels -SeriesMap ([ordered]@{
        "USD per RPS" = $costPerRps
    }) -YAxisTitle "USD / RPS"

    $fullOutPath = Join-Path (Get-Location) $OutPath
    $presentation.SaveAs($fullOutPath)
    $presentation.Close()
    Write-Host "Saved PPTX: $fullOutPath"
}
finally {
    if ($ppt -ne $null) {
        $ppt.Quit()
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
