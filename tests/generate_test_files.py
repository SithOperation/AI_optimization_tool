#!/usr/bin/env python
"""
Test utilities for the large-file import workflow.
Generates test CSV files and validates import functionality.
"""

import csv
import json
from pathlib import Path
from datetime import datetime, timedelta
import random


def generate_test_csv(filename: str, row_count: int = 1000, size_mb: int = None):
    """
    Generate a test CSV file with realistic telemetry data.
    
    Args:
        filename: Output CSV filename
        row_count: Number of rows to generate (if size_mb is not specified)
        size_mb: Target file size in MB (overrides row_count if specified)
    """
    csv_path = Path(filename)
    
    # Headers matching event schema
    headers = [
        'timestamp',
        'application',
        'provider',
        'model',
        'prompt_tokens',
        'completion_tokens',
        'total_cost',
        'latency_ms',
        'success',
    ]
    
    providers = ['openai', 'anthropic', 'ollama', 'mistral']
    models = ['gpt-4', 'gpt-3.5-turbo', 'claude-3-opus', 'llama-2', 'mistral-7b']
    apps = ['Code Assistant', 'Chat Bot', 'Data Analysis', 'Search Engine', 'Report Generator']
    
    start_time = datetime.now() - timedelta(days=30)
    
    def get_row():
        """Generate a single row of telemetry data."""
        timestamp = start_time + timedelta(seconds=random.randint(0, 30 * 24 * 3600))
        input_tokens = random.randint(10, 2000)
        output_tokens = random.randint(10, 1000)
        
        return {
            'timestamp': timestamp.isoformat(),
            'application': random.choice(apps),
            'provider': random.choice(providers),
            'model': random.choice(models),
            'prompt_tokens': input_tokens,
            'completion_tokens': output_tokens,
            'total_cost': (input_tokens * 0.0005 + output_tokens * 0.0015) / 1000,
            'latency_ms': random.randint(100, 5000),
            'success': random.choice(['true', 'false']),
        }
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        
        if size_mb:
            # Write rows until we reach target size
            current_size = 0
            target_bytes = size_mb * 1024 * 1024
            while current_size < target_bytes:
                writer.writerow(get_row())
                current_size = csv_path.stat().st_size
        else:
            # Write fixed number of rows
            for _ in range(row_count):
                writer.writerow(get_row())
    
    return csv_path


def generate_test_json(filename: str, row_count: int = 1000):
    """
    Generate a test JSON file (line-delimited) with realistic telemetry data.
    """
    json_path = Path(filename)
    
    providers = ['openai', 'anthropic', 'ollama', 'mistral']
    models = ['gpt-4', 'gpt-3.5-turbo', 'claude-3-opus', 'llama-2', 'mistral-7b']
    apps = ['Code Assistant', 'Chat Bot', 'Data Analysis', 'Search Engine', 'Report Generator']
    
    start_time = datetime.now() - timedelta(days=30)
    
    with open(json_path, 'w', encoding='utf-8') as f:
        for i in range(row_count):
            timestamp = start_time + timedelta(seconds=random.randint(0, 30 * 24 * 3600))
            input_tokens = random.randint(10, 2000)
            output_tokens = random.randint(10, 1000)
            
            record = {
                'id': f'evt-{i:07d}',
                'timestamp': timestamp.isoformat(),
                'application': random.choice(apps),
                'provider': random.choice(providers),
                'model': random.choice(models),
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'estimated_total_cost': (input_tokens * 0.0005 + output_tokens * 0.0015) / 1000,
                'latency_ms': random.randint(100, 5000),
                'success': random.choice([True, False]),
            }
            f.write(json.dumps(record) + '\n')
    
    return json_path


if __name__ == '__main__':
    import sys
    
    print('Generating test files...')
    
    # Generate various sizes for testing
    sizes = [
        ('test_10k.csv', 10_000),
        ('test_100k.csv', 100_000),
        ('test_1m.csv', 1_000_000),
    ]
    
    for filename, rows in sizes:
        print(f'  Generating {filename} ({rows:,} rows)...')
        csv_path = generate_test_csv(filename, row_count=rows)
        size_mb = csv_path.stat().st_size / (1024 * 1024)
        print(f'    -> {size_mb:.1f} MB')
    
    # Generate 42 MB file (regression test)
    print('  Generating test_42mb.csv (42 MB target)...')
    csv_path = generate_test_csv('test_42mb.csv', size_mb=42)
    size_mb = csv_path.stat().st_size / (1024 * 1024)
    print(f'    -> {size_mb:.1f} MB')
    
    # Generate JSON test
    print('  Generating test_100k.jsonl (100K rows)...')
    json_path = generate_test_json('test_100k.jsonl', row_count=100_000)
    size_mb = json_path.stat().st_size / (1024 * 1024)
    print(f'    -> {size_mb:.1f} MB')
    
    print('Done! Test files ready for import workflow testing.')
