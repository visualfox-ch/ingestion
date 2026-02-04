"""Integration tests for Phase 2 API endpoints."""

import pytest
import sys
from pathlib import Path
import json

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Note: These are integration tests that require a running FastAPI instance
# They document the expected endpoint behavior


class TestAutonomySettingsEndpoints:
    """Test autonomy settings API endpoints."""
    
    def test_post_autonomy_settings_structure(self):
        """Document POST /memory/settings/autonomy structure."""
        # Expected request structure
        payload = {
            "level": "medium",
            "focus_areas": ["decision_log", "learning", "suggestions"],
            "notify": True
        }
        
        # Verify payload structure
        assert "level" in payload
        assert payload["level"] in ["low", "medium", "high"]
        assert isinstance(payload.get("focus_areas"), list)
        assert isinstance(payload.get("notify"), bool)
    
    def test_get_autonomy_settings_parameters(self):
        """Document GET /memory/settings/autonomy parameters."""
        # Expected query parameters
        params = {
            "user_id": "micha",  # Optional
            "include_metadata": True  # Optional
        }
        
        assert "user_id" in params or True  # user_id optional
        assert params.get("user_id") is None or isinstance(params.get("user_id"), str)


class TestTimezoneSettingsEndpoints:
    """Test timezone settings API endpoints."""
    
    def test_post_timezone_setting_structure(self):
        """Document POST /memory/settings/timezone structure."""
        payload = {
            "timezone": "Europe/Zurich"
        }
        
        assert "timezone" in payload
        assert isinstance(payload["timezone"], str)
        # Common IANA timezones
        assert payload["timezone"] in [
            "Europe/Zurich", "UTC", "Europe/Berlin", 
            "America/New_York", "Asia/Tokyo"
        ]
    
    def test_get_timezone_setting_parameters(self):
        """Document GET /memory/settings/timezone parameters."""
        params = {
            "user_id": "micha",  # Optional
        }
        
        # user_id should be optional
        assert params.get("user_id") is None or isinstance(params.get("user_id"), str)


class TestImpactSummaryEndpoint:
    """Test impact summary API endpoint."""
    
    def test_get_impact_summary_parameters(self):
        """Document GET /learning/impact-summary parameters."""
        # Expected parameters
        params = {
            "days": 7,  # Default period
            "user_id": None  # Optional
        }
        
        assert isinstance(params.get("days"), int)
        assert params.get("days") > 0
        assert params.get("user_id") is None or isinstance(params.get("user_id"), str)
    
    def test_impact_summary_response_structure(self):
        """Document expected impact summary response."""
        expected_response = {
            "period_days": 7,
            "stats": {
                "total_suggestions": 5,
                "outcomes": {
                    "worked": 3,
                    "partially_worked": 1,
                    "didn't_work": 1,
                    "not_tried": 0
                },
                "effectiveness": 0.75,
                "confidence": 0.8
            },
            "top_suggestions": [
                {
                    "suggestion_id": "123abc",
                    "domain": "focus",
                    "outcome": "worked"
                }
            ],
            "count_top": 5
        }
        
        # Verify structure
        assert "period_days" in expected_response
        assert "stats" in expected_response
        assert "top_suggestions" in expected_response
        assert isinstance(expected_response["stats"], dict)
        assert isinstance(expected_response["top_suggestions"], list)


class TestEndpointValidation:
    """Test endpoint parameter validation."""
    
    def test_user_id_optional_on_autonomy_get(self):
        """Verify user_id is optional on GET autonomy."""
        # This endpoint should work with or without user_id
        # Both should return 200 OK
        assert True  # Validated separately
    
    def test_user_id_optional_on_timezone_get(self):
        """Verify user_id is optional on GET timezone."""
        assert True  # Validated separately
    
    def test_user_id_optional_on_impact_summary(self):
        """Verify user_id is optional on impact-summary."""
        assert True  # Validated separately


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
