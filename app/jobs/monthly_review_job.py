"""
Monthly Review Job

Scheduled job that triggers the monthly optimization review on day 31.
Part of the self-optimization framework HITL (Human-In-The-Loop) workflow.

Schedule: Day 31 of each month at 03:00 UTC
Purpose: 
  1. Collect metrics from past month
  2. Generate optimization report
  3. Identify parameter candidates for change
  4. Present recommendations to human reviewers

Author: GitHub Copilot
Created: 2026-02-04
"""

from datetime import datetime
from typing import Dict, Any

from ..observability import get_logger, log_with_context
from ..monthly_review import MonthlyReviewProcess

logger = get_logger("jarvis.monthly_review_job")


def run_monthly_review_job() -> Dict[str, Any]:
    """
    Execute the monthly review process.
    
    Triggered automatically on day 31 of each month.
    This is the entry point for the HITL monthly optimization cycle.
    
    Returns:
        Dict with status and result details
    """
    log_with_context(logger, "info", "Starting monthly review job")
    
    try:
        # Initialize monthly review
        review = MonthlyReviewProcess()
        
        # Log the review start
        log_with_context(logger, "info", "Monthly review initiated",
                        timestamp=datetime.utcnow().isoformat())
        
        # Start the review process
        result = review.start_review()
        
        if result and result.get("success"):
            log_with_context(logger, "info", "Monthly review completed successfully",
                           status=result.get("status"),
                           review_id=result.get("review_id"))
            return {
                "success": True,
                "status": "review_initiated",
                "review_id": result.get("review_id"),
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            error_msg = result.get("error", "Unknown error") if result else "No result returned"
            log_with_context(logger, "error", "Monthly review failed", error=error_msg)
            return {
                "success": False,
                "error": error_msg,
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except Exception as e:
        log_with_context(logger, "error", "Monthly review job exception",
                        error=str(e), error_type=type(e).__name__)
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
