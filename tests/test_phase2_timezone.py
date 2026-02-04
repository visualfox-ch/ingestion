"""Unit tests for Phase 2 timezone utilities."""

import pytest
from datetime import datetime
import pytz
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.timezone import ZURICH_TZ, now_zurich_iso, parse_to_zurich, to_zurich_iso


class TestTimezoneConstants:
    """Test timezone constant configuration."""
    
    def test_zurich_tz_configured(self):
        """Verify ZURICH_TZ is properly configured."""
        assert ZURICH_TZ is not None
        assert ZURICH_TZ.zone == "Europe/Zurich"
        assert isinstance(ZURICH_TZ, pytz.tzfile.DstTzInfo)
    
    def test_zurich_tz_handles_dst(self):
        """Verify ZURICH_TZ handles DST correctly."""
        # Winter time (no DST)
        winter = ZURICH_TZ.localize(datetime(2026, 1, 15, 12, 0, 0))
        assert winter.utcoffset().total_seconds() == 3600  # +01:00
        
        # Summer time (DST active)
        summer = ZURICH_TZ.localize(datetime(2026, 7, 15, 12, 0, 0))
        assert summer.utcoffset().total_seconds() == 7200  # +02:00


class TestNowZurichIso:
    """Test now_zurich_iso function."""
    
    def test_returns_string(self):
        """Verify now_zurich_iso returns string."""
        result = now_zurich_iso()
        assert isinstance(result, str)
    
    def test_iso_format(self):
        """Verify ISO 8601 format."""
        result = now_zurich_iso()
        assert "T" in result
        assert ("+01:00" in result or "+02:00" in result)
    
    def test_parseable(self):
        """Verify result can be parsed."""
        result = now_zurich_iso()
        parsed = parse_to_zurich(result)
        assert parsed is not None
        assert parsed.tzinfo.zone == "Europe/Zurich"


class TestParseToZurich:
    """Test parse_to_zurich function."""
    
    def test_parse_utc_iso(self):
        """Parse UTC ISO timestamp."""
        ts = "2026-02-04T12:00:00+00:00"
        result = parse_to_zurich(ts)
        assert result is not None
        assert result.tzinfo.zone == "Europe/Zurich"
    
    def test_parse_z_suffix(self):
        """Parse timestamp with Z suffix."""
        ts = "2026-02-04T12:00:00Z"
        result = parse_to_zurich(ts)
        assert result is not None
        assert result.tzinfo.zone == "Europe/Zurich"
    
    def test_parse_zurich_timestamp(self):
        """Parse Zurich timestamp."""
        ts = "2026-02-04T12:00:00+01:00"
        result = parse_to_zurich(ts)
        assert result is not None
        assert result.tzinfo.zone == "Europe/Zurich"
    
    def test_parse_none(self):
        """Handle None input."""
        result = parse_to_zurich(None)
        assert result is None
    
    def test_parse_invalid(self):
        """Handle invalid input."""
        result = parse_to_zurich("not-a-date")
        assert result is None


class TestToZurichIso:
    """Test to_zurich_iso function."""
    
    def test_convert_utc_to_zurich(self):
        """Convert UTC timestamp to Zurich ISO."""
        ts = "2026-02-04T12:00:00Z"
        result = to_zurich_iso(ts)
        assert result is not None
        assert "+01:00" in result or "+02:00" in result
    
    def test_preserves_invalid_input(self):
        """Preserve invalid input unchanged."""
        ts = "not-a-date"
        result = to_zurich_iso(ts)
        assert result == ts
    
    def test_handles_none(self):
        """Handle None gracefully."""
        result = to_zurich_iso(None)
        # Should return None or the input unchanged
        assert result is None or result == "None"
    
    def test_multiple_formats(self):
        """Test various ISO formats."""
        formats = [
            "2026-02-04T12:00:00Z",
            "2026-02-04T12:00:00+00:00",
            "2026-02-04T12:00:00+02:00",
        ]
        for ts in formats:
            result = to_zurich_iso(ts)
            assert result is not None
            assert "T" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
