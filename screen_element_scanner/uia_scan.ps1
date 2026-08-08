param(
  [int]$MaxDepth = 8,
  [int]$MaxElements = 2500
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName UIAutomationClient | Out-Null
Add-Type -AssemblyName UIAutomationTypes | Out-Null

$script:items = New-Object System.Collections.Generic.List[object]
$script:seen = New-Object 'System.Collections.Generic.HashSet[string]'
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$root = [System.Windows.Automation.AutomationElement]::RootElement

$interestingTypes = @(
  "ControlType.Button",
  "ControlType.Edit",
  "ControlType.Hyperlink",
  "ControlType.CheckBox",
  "ControlType.RadioButton",
  "ControlType.ComboBox",
  "ControlType.ListItem",
  "ControlType.MenuItem",
  "ControlType.TabItem",
  "ControlType.DataItem",
  "ControlType.HeaderItem",
  "ControlType.SplitButton",
  "ControlType.Spinner",
  "ControlType.Slider",
  "ControlType.Document",
  "ControlType.Pane",
  "ControlType.Window"
)

function Get-ElementKey($element) {
  try {
    $r = $element.Current.BoundingRectangle
  } catch {
    return
  }
  return "$($element.Current.ControlType.ProgrammaticName)|$($element.Current.Name)|$($element.Current.AutomationId)|$([int]$r.Left),$([int]$r.Top),$([int]$r.Right),$([int]$r.Bottom)"
}

function Add-Element($element, [int]$depth) {
  if ($null -eq $element) { return }
  if ($script:items.Count -ge $MaxElements) { return }

  try {
    $r = $element.Current.BoundingRectangle
    $typeName = $element.Current.ControlType.ProgrammaticName
    $name = $element.Current.Name
    $automationId = $element.Current.AutomationId
    $localizedControlType = $element.Current.LocalizedControlType
    $className = $element.Current.ClassName
    $processId = $element.Current.ProcessId
  } catch {
    return
  }
  $w = [double]($r.Right - $r.Left)
  $h = [double]($r.Bottom - $r.Top)
  if ($w -le 1 -or $h -le 1) { return }
  if ([string]::IsNullOrWhiteSpace($typeName)) { return }

  $hasUsefulText = -not [string]::IsNullOrWhiteSpace($name) -or -not [string]::IsNullOrWhiteSpace($automationId)
  $isInteresting = $interestingTypes -contains $typeName
  if (-not $isInteresting -and -not $hasUsefulText) { return }

  $key = Get-ElementKey $element
  if ([string]::IsNullOrWhiteSpace($key)) { return }
  if (-not $script:seen.Add($key)) { return }

  $script:items.Add([ordered]@{
    source = "uia"
    role = $typeName.Replace("ControlType.", "").ToLowerInvariant()
    localized_role = $localizedControlType
    label = $name
    automation_id = $automationId
    class_name = $className
    process_id = $processId
    depth = $depth
    bounds = @(
      [int]$r.Left,
      [int]$r.Top,
      [int]$r.Right,
      [int]$r.Bottom
    )
    center = @(
      [int](($r.Left + $r.Right) / 2),
      [int](($r.Top + $r.Bottom) / 2)
    )
    confidence = 0.95
  }) | Out-Null
}

function Walk-Element($element, [int]$depth) {
  if ($null -eq $element) { return }
  if ($depth -gt $MaxDepth) { return }
  if ($script:items.Count -ge $MaxElements) { return }

  Add-Element $element $depth

  try {
    $child = $walker.GetFirstChild($element)
  } catch {
    return
  }
  while ($null -ne $child) {
    Walk-Element $child ($depth + 1)
    if ($script:items.Count -ge $MaxElements) { return }
    try {
      $child = $walker.GetNextSibling($child)
    } catch {
      return
    }
  }
}

Walk-Element $root 0

$script:items | ConvertTo-Json -Depth 6
