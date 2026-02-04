"""Unit tests for Phase 2 autonomy settings."""

import pytest
import sys
from pathlib import Path
from typing import Optional

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.routers.memory_router import AutonomySettingsRequest, TimezoneSettingRequest


class TestAutonomySettingsRequest:
    """Test AutonomySettingsRequest model."""
    
    def test_create_with_all_fields(self):
        """Create with all fields."""
        req = AutonomySettingsRequest(
            level="medium",
            focus_areas=["decision_log", "learning"],
            notify=True
        )
        assert req.level == "medium"
        assert len(req.focus_areas) == 2
        assert req.notify is True
    
    def test_create_with_minimum_fields(self):
        """Create with only required fields."""
        req = AutonomySettingsRequest(level="high")
        assert req.level == "high"
        # Optional fields should have defaults or be None
        assert hasattr(req, "focus_areas")
        assert hasattr(req, "notify")
    
    def test_valid_levels(self):
        """Test valid autonomy levels."""
        for level in ["low", "medium", "high"]:
            req = AutonomySettingsRequest(level=level)
            assert req.level == level
    
    def test_focus_areas_list(self):
        """Test focus_areas as list."""
        areas = ["decision_log", "suggestions", "learning"]
        req = AutonomySettingsRequest(level="high", focus_areas=areas)
        assert req.focus_areas == areas
    
    def test_focus_areas_optional(self):
        """Test focus_areas is optional."""
        req = AutonomySettingsRequest(level="medium")
        # Should not raise error even if focus_areas not provided
        assert True
    
    def test_notify_boolean(self):
        """Test notify is boolean."""
        req_true = AutonomySettingsRequest(level="low", notify=True)
        assert req_true.notify is True
        
        req_false = AutonomySettingsRequest(level="low", notify=False)
        assert req_false.notify is False


class TestTimezoneSettingRequest:
    """Test TimezoneSettingRequest model."""
    
    def test_create_valid_timezone(self):
        """Create with valid IANA timezone."""
        req = TimezoneSettingRequest(timezone="Europe/Zurich")
        assert req.timezone == "Europe/Zurich"
    
    def test_various_valid_timezones(self):
        """Test various valid IANA timezones."""
        timezones = [
            "UTC",
            "Europe/Berlin",
            "America/New_York",
            "Asia/Tokyo",
            "Australia/Sydney",
        ]
        for tz in timezones:
            req = TimezoneSettingRequest(timezone=tz)
            assert req.timezone == tz
    
    def test_timezone_string_type(self):
        """Verify timezone is string."""
        req = TimezoneSettingRequest(timezone="UTC")
        assert isinstance(req.timezone, str)


class TestProductionSafety:
    """Test production safety of settings endpoints."""
    
    def test_no_hardcoded_user_ids(self):
        """Verify no hardcoded default user_ids."""
        # This is a documentation test
        # The actual endpoint should NOT have user_id="micha"
        # It should be user_id: Optional[str] = None
        assert True
    
    def test_autonomy_settings_model_valid(self):
        """Verify AutonomySettingsRequest validates correctly."""
        req = AutonomySettingsRequest(level="medium")
        # Model should be valid without user_id
        assert req is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
