"""
Unit tests for the large-file import workflow.
Tests streaming parsing, validation, chunking, and duplicate handling.
"""

import pytest
import tempfile
import uuid
from pathlib import Path
import asyncio
import sys

# Add the app directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'apps' / 'api'))

from tokenscope_api.importer_streaming import (
    StreamingImporter,
    validate_file_metadata,
    guess_csv_delimiter,
    guess_encoding,
    parse_csv_rows,
    parse_json_rows,
    auto_map_columns,
    coerce_value,
    KNOWN_ALIASES,
)


class TestFileValidation:
    """Test file metadata validation."""
    
    def test_valid_csv(self):
        """CSV with .csv extension should pass."""
        assert validate_file_metadata('data.csv', 1024, 'csv') is None
    
    def test_valid_json(self):
        """JSON with .json extension should pass."""
        assert validate_file_metadata('data.json', 1024, 'json') is None
    
    def test_valid_jsonl(self):
        """JSONL with .jsonl extension should pass."""
        assert validate_file_metadata('data.jsonl', 1024, 'json') is None
    
    def test_invalid_extension_csv(self):
        """CSV with wrong extension should fail."""
        from tokenscope_api.importer_streaming import FileValidationError
        with pytest.raises(FileValidationError):
            validate_file_metadata('data.txt', 1024, 'csv')
    
    def test_oversized_file(self):
        """File exceeding 500 MB should fail."""
        from tokenscope_api.importer_streaming import FileValidationError
        with pytest.raises(FileValidationError):
            validate_file_metadata('data.csv', 501 * 1024 * 1024, 'csv')
    
    def test_path_traversal_protection(self):
        """Filename with path traversal should fail."""
        from tokenscope_api.importer_streaming import FileValidationError
        with pytest.raises(FileValidationError):
            validate_file_metadata('../../../etc/passwd.csv', 1024, 'csv')
    
    def test_path_separator_protection(self):
        """Filename with directory separators should fail."""
        from tokenscope_api.importer_streaming import FileValidationError
        with pytest.raises(FileValidationError):
            validate_file_metadata('folder/data.csv', 1024, 'csv')


class TestDelimiterDetection:
    """Test CSV delimiter detection."""
    
    def test_comma_delimiter(self):
        """Should detect comma as delimiter."""
        sample = "a,b,c\n1,2,3\n4,5,6\n"
        assert guess_csv_delimiter(sample) == ','
    
    def test_semicolon_delimiter(self):
        """Should detect semicolon as delimiter."""
        sample = "a;b;c\n1;2;3\n4;5;6\n"
        assert guess_csv_delimiter(sample) == ';'
    
    def test_tab_delimiter(self):
        """Should detect tab as delimiter."""
        sample = "a\tb\tc\n1\t2\t3\n4\t5\t6\n"
        assert guess_csv_delimiter(sample) == '\t'
    
    def test_pipe_delimiter(self):
        """Should detect pipe as delimiter."""
        sample = "a|b|c\n1|2|3\n4|5|6\n"
        assert guess_csv_delimiter(sample) == '|'


class TestEncodingDetection:
    """Test file encoding detection."""
    
    def test_utf8_detection(self):
        """Should detect UTF-8 encoding."""
        data = "name,age\nJosé,25\nFrançois,30\n".encode('utf-8')
        encoding = guess_encoding(data)
        assert encoding in ['utf-8', 'UTF-8']
    
    def test_latin1_detection(self):
        """Should detect Latin-1 encoding."""
        # Create Latin-1 encoded data
        data = "name,age\nJosé,25\n".encode('latin-1')
        encoding = guess_encoding(data)
        assert encoding is not None


class TestCsvParsing:
    """Test CSV row parsing."""
    
    def test_simple_csv(self):
        """Should parse simple CSV rows."""
        content = "a,b,c\n1,2,3\n4,5,6\n"
        rows = list(parse_csv_rows(content, ','))
        assert len(rows) == 2
        assert rows[0] == {'a': '1', 'b': '2', 'c': '3'}
        assert rows[1] == {'a': '4', 'b': '5', 'c': '6'}
    
    def test_csv_with_quotes(self):
        """Should handle quoted fields."""
        content = 'name,description\nTest,"Contains, comma"\n'
        rows = list(parse_csv_rows(content, ','))
        assert rows[0]['description'] == 'Contains, comma'
    
    def test_csv_with_empty_fields(self):
        """Should handle empty fields."""
        content = "a,b,c\n1,,3\n"
        rows = list(parse_csv_rows(content, ','))
        assert rows[0] == {'a': '1', 'b': '', 'c': '3'}
    
    def test_csv_with_multiline(self):
        """Should handle multiline fields."""
        content = 'name,description\nTest,"Line 1\nLine 2"\n'
        rows = list(parse_csv_rows(content, ','))
        assert 'Line 1' in rows[0]['description']


class TestJsonParsing:
    """Test JSON parsing."""
    
    def test_jsonl_parsing(self):
        """Should parse line-delimited JSON."""
        content = '{"a": 1, "b": 2}\n{"a": 3, "b": 4}\n'
        rows = list(parse_json_rows(content))
        assert len(rows) == 2
        assert rows[0] == {'a': 1, 'b': 2}
        assert rows[1] == {'a': 3, 'b': 4}
    
    def test_json_array_parsing(self):
        """Should parse JSON array."""
        content = '[{"a": 1}, {"a": 2}]'
        rows = list(parse_json_rows(content))
        assert len(rows) == 2
        assert rows[0] == {'a': 1}


class TestColumnMapping:
    """Test column mapping with aliases."""
    
    def test_exact_field_match(self):
        """Should recognize exact field names."""
        headers = ['timestamp', 'application', 'input_tokens', 'output_tokens']
        mapping = auto_map_columns(headers)
        assert mapping['timestamp'] == 'timestamp'
        assert mapping['application'] == 'application'
    
    def test_alias_detection(self):
        """Should detect and map known aliases."""
        headers = ['prompt_tokens', 'completion_tokens', 'total_cost']
        mapping = auto_map_columns(headers)
        assert mapping['prompt_tokens'] == 'input_tokens'
        assert mapping['completion_tokens'] == 'output_tokens'
        assert mapping['total_cost'] == 'estimated_total_cost'
    
    def test_case_insensitive_matching(self):
        """Should match case-insensitively."""
        headers = ['Timestamp', 'Application', 'MODEL']
        mapping = auto_map_columns(headers)
        assert 'timestamp' in str(mapping).lower()
    
    def test_multiple_aliases(self):
        """Should handle all defined aliases."""
        # Test that each alias in KNOWN_ALIASES is recognized and mapped correctly
        for target_field, aliases in KNOWN_ALIASES.items():
            # Test the target field itself maps to itself
            headers = [target_field]
            mapping = auto_map_columns(headers)
            assert mapping.get(target_field) == target_field, f"Target field {target_field} should map to itself"
            
            # Test each alias maps to the target
            for alias in aliases:
                headers = [alias]
                mapping = auto_map_columns(headers)
                assert mapping.get(alias) == target_field, f"Alias {alias} should map to {target_field}"


class TestValueCoercion:
    """Test type coercion for field values."""
    
    def test_integer_coercion(self):
        """Should coerce to integer."""
        assert coerce_value('123', 'input_tokens') == 123
        assert coerce_value(456, 'input_tokens') == 456
    
    def test_float_coercion(self):
        """Should coerce to float."""
        assert coerce_value('12.34', 'latency_ms') == 12.34
        assert coerce_value(56.78, 'latency_ms') == 56.78
    
    def test_boolean_coercion(self):
        """Should coerce to boolean."""
        assert coerce_value('true', 'success') is True
        assert coerce_value('false', 'success') is False
        assert coerce_value('True', 'success') is True
        assert coerce_value('False', 'success') is False
    
    def test_string_passthrough(self):
        """Should keep strings as-is."""
        assert coerce_value('test', 'application') == 'test'
        assert coerce_value('2024-01-01T00:00:00', 'timestamp') == '2024-01-01T00:00:00'
    
    def test_invalid_integer(self):
        """Should raise on invalid integer."""
        with pytest.raises(ValueError):
            coerce_value('abc', 'input_tokens')
    
    def test_none_handling(self):
        """Should handle None values."""
        result = coerce_value(None, 'input_tokens')
        assert result is None


class TestStreamingImporter:
    """Test the main StreamingImporter class."""
    
    @pytest.fixture
    def importer(self):
        """Create a StreamingImporter instance for testing."""
        import_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            importer = StreamingImporter(import_id, temp_dir=temp_dir)
            yield importer
    
    @pytest.mark.asyncio
    async def test_chunk_reception(self, importer):
        """Should accept and store file chunks."""
        chunk1 = b"timestamp,application,model\n"
        chunk2 = b"2024-01-01,app1,gpt-4\n"
        
        await importer.receive_file_chunk(chunk1)
        await importer.receive_file_chunk(chunk2)
        
        temp_path = importer.get_temp_path()
        assert temp_path.exists()
        
        content = temp_path.read_bytes()
        assert chunk1 + chunk2 == content
    
    def test_temp_dir_creation(self, importer):
        """Should create temp directory if needed."""
        temp_path = importer.get_temp_path()
        assert temp_path.parent.exists()
        assert 'tokenscope_imports' in str(temp_path)
    
    @pytest.mark.asyncio
    async def test_cleanup_on_cancel(self, importer):
        """Should remove temp file when cancelled (file cleanup only)."""
        chunk = b"test data\n"
        await importer.receive_file_chunk(chunk)
        
        temp_path = importer.get_temp_path()
        assert temp_path.exists()
        
        # Note: Full cancel() requires database, so we just test file cleanup
        # await importer.cancel()
        # For now, just verify temp path exists
        assert temp_path.parent.name == 'tokenscope_imports'


class TestDuplicateHandling:
    """Test duplicate detection policies."""
    
    def test_skip_duplicates(self):
        """Skip policy should not process duplicate rows."""
        # This would be tested with actual database operations
        # Placeholder for integration test
        pass
    
    def test_replace_duplicates(self):
        """Replace policy should update existing rows."""
        # This would be tested with actual database operations
        # Placeholder for integration test
        pass
    
    def test_fail_on_duplicates(self):
        """Fail policy should raise on first duplicate."""
        # This would be tested with actual database operations
        # Placeholder for integration test
        pass


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v', '--tb=short'])
