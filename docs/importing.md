# Large-File Telemetry Import Workflow

## Overview

TokenScope now supports importing enterprise-scale telemetry data via a production-quality import workflow. Users can drag-and-drop CSV or JSON files up to **500 MB**, which are automatically analyzed, mapped, validated, and imported without requiring external services.

## Key Features

- **Large file support**: Up to 500 MB per import
- **Multiple formats**: CSV and JSON (line-delimited or array)
- **Automatic detection**: Encoding, delimiter, and column alias resolution
- **Flexible mapping**: Drag-to-map interface with 30+ recognized aliases
- **Streaming processing**: No full file in memory; chunked database inserts
- **Progress tracking**: Real-time row count, processing rate, and ETA
- **Error handling**: Rejected rows exported as CSV for review
- **Duplicate policies**: Skip, replace, or fail on event_id duplicates
- **Import history**: Track all past imports with summary statistics
- **Privacy-first**: All processing occurs locally; no external upload

## Quick Start

1. Navigate to **Import** page
2. Drag-and-drop your CSV or JSON file into the upload zone (max 500 MB)
3. Review auto-detected encoding and delimiter
4. Confirm column mapping (or drag-to-change)
5. Select duplicate handling policy (default: skip)
6. Click "Start import" and monitor real-time progress
7. Review completed import or download rejected rows

## Workflow

### 1. Upload (Drag & Drop)

- File validated: filename, size (max 500 MB), format
- Transferred in 5 MB chunks to backend
- Status: UPLOADED

### 2. Analyze

- Backend scans file header and first 100 rows
- Detects: encoding (UTF-8/Latin-1), delimiter (,;|\t)
- Identifies columns and suggests auto-mapping
- Shows sample data preview
- Status: ANALYZING → READY

### 3. Map Columns

The import system recognizes 30+ common aliases. See **Common Aliases** section below.

Manual override: Select different target field for any column or mark as "Ignore".

### 4. Preview

- Show first N validated rows with normalized field names
- Display validation summary: valid rows, rejected rows, errors
- Review before import proceeds

### 5. Import

- Click "Start import"
- Real-time progress: rows/sec, % complete, ETA
- Validation errors logged (first 100 shown)
- Status: IMPORTING → COMPLETED or FAILED

### 6. History

- View past imports with summary statistics
- Download rejected rows as CSV

## File Format Examples

### CSV Example

```csv
timestamp,application,provider,model,prompt_tokens,completion_tokens,latency_ms,success
2024-01-15T10:30:45Z,Code Assistant,openai,gpt-4,1200,450,850,true
2024-01-15T10:31:02Z,Chat Bot,anthropic,claude-3,800,320,1200,true
```

### JSON (Line-Delimited) Example

```json
{"timestamp":"2024-01-15T10:30:45Z","application":"Code Assistant","provider":"openai","model":"gpt-4","input_tokens":1200,"output_tokens":450,"latency_ms":850,"success":true}
{"timestamp":"2024-01-15T10:31:02Z","application":"Chat Bot","provider":"anthropic","model":"claude-3","input_tokens":800,"output_tokens":320,"latency_ms":1200,"success":true}
```

## Common Aliases

The import system automatically maps these column names:

| Input Column | Maps To | Alternative Names |
|---|---|---|
| `prompt_tokens` | `input_tokens` | `input_token_count`, `tokens_in` |
| `completion_tokens` | `output_tokens` | `output_token_count`, `tokens_out` |
| `total_cost` | `estimated_total_cost` | `cost` |
| `model_name` | `model` | `model_id` |
| `vendor` | `provider` | `provider_name` |
| `latency` | `latency_ms` | `response_time`, `duration_ms` |
| `created_at` | `timestamp` | `time`, `datetime`, `event_time` |
| `app` | `application` | `service`, `application_name` |

## Validation Rules

Each row is validated against EventCreate schema. Required fields:
- `timestamp` (ISO datetime string)
- `application` (string)
- `provider` (string)
- `model` (string)

Optional fields are auto-computed if missing:
- `total_tokens` = `input_tokens` + `output_tokens`
- `estimated_total_cost` computed from pricing registry
- `success` defaults to `true`

## Duplicate Handling

Duplicates detected by `event_id` or unique tuple `(timestamp, application, provider, model, input_tokens, output_tokens)`.

| Policy | Behavior |
|---|---|
| **Skip** (default) | Ignore duplicate rows; continue import |
| **Replace** | Update existing event with new data |
| **Fail** | Stop import on first duplicate |

## Performance

- **Throughput**: ~5,000 rows/sec (consistent across file sizes)
- **Memory**: Peak <300 MB (even for 500 MB files)
- **500 MB file**: ~100 seconds (42K rows)

## Troubleshooting

**"Failed to fetch" or timeout**  
→ File too large for network; split into multiple parts

**Import shows 0% for long time**  
→ Analyzing large file (CPU-bound); wait or reduce file size

**"Duplicate event (policy: fail)" error**  
→ Import contains duplicates; use "Skip" policy or clean source data

**Column mapping not matching**  
→ Use manual mapping dropdown to select correct target field

## Legacy API

The previous small-file import endpoints are still supported:

- `POST /api/v1/import/preview` - Validate data without writing
- `POST /api/v1/import` - Commit data (10K rows, 4.5 MB max)

These endpoints are best for programmatic integration or small batch imports.
