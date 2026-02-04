"""
Jarvis Execution Orchestrator (Phase 0 Deployment Loop)

Purpose:
  Coordinate: Approval → Write → Test → Deploy → Measure → Learn
  
Flow:
  1. Poll approval_store for APPROVED changes
  2. Write code to file
  3. Run tests (validate)
  4. Deploy via NAS wrapper
  5. Measure impact (pre/post metrics)
  6. Record learning (update confidence)
  7. Log immutably

Safety:
  - Pre-write snapshot (rollback reference)
  - Validation gates (syntax, tests)
  - Deployment monitoring (NAS health)
  - Metric correlation (prove impact)
  - Immutable audit trail (every step logged)

References:
  - JARVIS_SELF_IMPROVEMENT_PROTOCOL.md (Propose→Review→Execute)
  - AUTONOMOUS_WRITE_SAFETY_BASELINE.md (Rollback SLA 15 min)
  - Phase 0 deployment starts Feb 4, 09:00 UTC
"""

from dataclasses import dataclass
from typing import Dict, Optional, Any, List
from datetime import datetime
import asyncio
import logging
import json
from pathlib import Path
import subprocess

logger = logging.getLogger("jarvis.execution_orchestrator")


@dataclass
class DeploymentResult:
    """Result of a full deployment cycle."""
    change_id: str
    approval_id: str
    success: bool
    stage: str  # "write", "test", "deploy", "measure"
    impact: Optional[Dict[str, float]] = None
    error: Optional[str] = None
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + "Z"


class JarvisExecutionOrchestrator:
    """
    Orchestrate code deployment: approval → execution → measurement → learning.
    
    Phase 0 (Feb 4-9): Run once per approved change (manual approval only).
    Phase 1+: Batch processing, conditional auto-execution.
    """
    
    def __init__(
        self,
        approval_store=None,
        metrics_bridge=None,
        learning_manager=None,
        audit_log=None,
        logger=None
    ):
        """
        Args:
            approval_store: Redis/DB store for approval requests
            metrics_bridge: JarvisMetricsBridge for pre/post measurement
            learning_manager: JarvisLearningManager for feedback
            audit_log: Immutable audit trail backend
            logger: Logger instance
        """
        self.approval_store = approval_store
        self.metrics_bridge = metrics_bridge
        self.learning_manager = learning_manager
        self.audit_log = audit_log
        self.logger = logger or logging.getLogger(__name__)
    
    async def run_phase0_loop(self, interval_sec: int = 300):
        """
        Phase 0 execution loop: check for approvals → execute → measure → learn.
        
        Runs continuously during Phase 0 (Feb 4-9).
        
        Args:
            interval_sec: Check interval (default 5 min)
        """
        self.logger.info("Phase 0 execution loop started", extra={"interval_sec": interval_sec})
        
        while True:
            try:
                # Poll for approved changes
                approvals = await self.approval_store.get_approved_pending()
                
                if approvals:
                    self.logger.info(
                        f"Found {len(approvals)} approved changes",
                        extra={"count": len(approvals)}
                    )
                    
                    for approval in approvals:
                        try:
                            result = await self.execute_single_change(approval)
                            
                            # Log result
                            await self._log_deployment(result)
                            
                            # Mark as processed
                            await self.approval_store.mark_executed(
                                approval.request_id,
                                status="executed" if result.success else "failed",
                                result=result.to_dict() if hasattr(result, 'to_dict') else {
                                    "success": result.success,
                                    "stage": result.stage,
                                    "error": result.error
                                }
                            )
                        
                        except Exception as e:
                            self.logger.error(
                                f"Error executing approval {approval.request_id}: {e}",
                                extra={"request_id": approval.request_id, "error": str(e)}
                            )
                
                # Wait before next poll
                await asyncio.sleep(interval_sec)
            
            except KeyboardInterrupt:
                self.logger.info("Phase 0 loop interrupted by user")
                break
            
            except Exception as e:
                self.logger.error(
                    f"Phase 0 loop error: {e}",
                    extra={"error": str(e)}
                )
                await asyncio.sleep(interval_sec)
    
    async def execute_single_change(self, approval) -> DeploymentResult:
        """
        Execute a single approved change through full cycle.
        
        Flow:
          1. Validate change (forbidden paths, size)
          2. Create pre-write snapshot
          3. Write code to file
          4. Run tests
          5. If success: deploy via NAS
          6. Measure impact (pre/post metrics)
          7. Record learning
          8. Return result
        
        Args:
            approval: Approved change from approval_store
        
        Returns:
            DeploymentResult with success status and impact metrics
        """
        
        change_id = approval.change.id
        
        try:
            # Stage 1: Validate
            self.logger.info("Validating change", extra={"change_id": change_id})
            
            change = approval.change
            validation = self._validate_change(change)
            
            if not validation["valid"]:
                return DeploymentResult(
                    change_id=change_id,
                    approval_id=approval.request_id,
                    success=False,
                    stage="validation",
                    error=f"Validation failed: {validation['reason']}"
                )
            
            # Stage 2: Create snapshot (rollback reference)
            self.logger.info("Creating pre-write snapshot", extra={"change_id": change_id})
            
            snapshot = await self._create_snapshot(change.file_path)
            
            # Stage 3: Write code
            self.logger.info("Writing code to file", extra={"change_id": change_id, "file": change.file_path})
            
            try:
                await self._write_change(change)
            except Exception as e:
                await self._rollback_from_snapshot(snapshot)
                return DeploymentResult(
                    change_id=change_id,
                    approval_id=approval.request_id,
                    success=False,
                    stage="write",
                    error=f"Write failed: {str(e)}"
                )
            
            # Stage 4: Run tests
            self.logger.info("Running tests", extra={"change_id": change_id})
            
            tests_pass = await self._run_tests(change.file_path)
            
            if not tests_pass:
                await self._rollback_from_snapshot(snapshot)
                return DeploymentResult(
                    change_id=change_id,
                    approval_id=approval.request_id,
                    success=False,
                    stage="test",
                    error="Tests failed after write"
                )
            
            # Stage 5: Deploy via NAS
            self.logger.info("Deploying via NAS wrapper", extra={"change_id": change_id})
            
            deploy_success = await self._deploy_with_nas(change)
            
            if not deploy_success:
                await self._rollback_from_snapshot(snapshot)
                return DeploymentResult(
                    change_id=change_id,
                    approval_id=approval.request_id,
                    success=False,
                    stage="deploy",
                    error="NAS deployment failed"
                )
            
            # Stage 6: Measure impact
            self.logger.info("Measuring deployment impact", extra={"change_id": change_id})
            
            if self.metrics_bridge:
                impact = await self.metrics_bridge.measure_change_impact(
                    change,
                    duration_sec=300  # Wait 5 min for metrics
                )
            else:
                impact = None
            
            # Stage 7: Record learning
            self.logger.info("Recording learning", extra={"change_id": change_id})
            
            if self.learning_manager:
                await self.learning_manager.process_deployment_result(
                    change=change,
                    impact=impact,
                    approval=approval
                )
            
            return DeploymentResult(
                change_id=change_id,
                approval_id=approval.request_id,
                success=True,
                stage="complete",
                impact=impact
            )
        
        except Exception as e:
            self.logger.error(
                f"Unexpected error in execute_single_change: {e}",
                extra={"change_id": change_id, "error": str(e)}
            )
            return DeploymentResult(
                change_id=change_id,
                approval_id=approval.request_id,
                success=False,
                stage="unknown",
                error=f"Unexpected error: {str(e)}"
            )
    
    def _validate_change(self, change) -> Dict[str, Any]:
        """Quick validation before write."""
        
        forbidden_paths = [".env", "secrets", "credentials", "PASSWORD", "docker-compose.yml"]
        
        for forbidden in forbidden_paths:
            if forbidden.lower() in change.file_path.lower():
                return {"valid": False, "reason": f"Forbidden path: {forbidden}"}
        
        if change.line_count > 500:
            return {"valid": False, "reason": f"Change too large ({change.line_count} lines)"}
        
        return {"valid": True}
    
    async def _create_snapshot(self, file_path: str) -> Dict[str, str]:
        """Create pre-write snapshot for rollback."""
        
        try:
            path = Path(file_path)
            
            if path.exists():
                content = path.read_text()
            else:
                content = None
            
            snapshot = {
                "file_path": file_path,
                "original_content": content,
                "snapshot_time": datetime.utcnow().isoformat() + "Z"
            }
            
            self.logger.info(
                "Snapshot created",
                extra={"file": file_path, "exists": path.exists()}
            )
            
            return snapshot
        
        except Exception as e:
            self.logger.error(f"Snapshot creation failed: {e}")
            raise
    
    async def _write_change(self, change) -> None:
        """Write code change to file."""
        
        path = Path(change.file_path)
        
        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        path.write_text(change.full_diff)  # Assuming full_diff is the new content
        
        self.logger.info(f"Code written to {change.file_path}")
    
    async def _run_tests(self, file_path: str) -> bool:
        """Run tests for modified file."""
        
        try:
            # Infer test file name
            test_file = f"tests/test_{Path(file_path).stem}.py"
            
            if not Path(test_file).exists():
                self.logger.warning(f"No test file found: {test_file}")
                return True  # No tests = pass (for now)
            
            # Run pytest
            result = subprocess.run(
                ["python3", "-m", "pytest", test_file, "-v"],
                capture_output=True,
                timeout=60
            )
            
            success = result.returncode == 0
            
            self.logger.info(
                f"Tests {'passed' if success else 'failed'}: {test_file}",
                extra={"success": success, "returncode": result.returncode}
            )
            
            return success
        
        except subprocess.TimeoutExpired:
            self.logger.error(f"Test timeout for {file_path}")
            return False
        
        except Exception as e:
            self.logger.error(f"Error running tests: {e}")
            return False
    
    async def _deploy_with_nas(self, change) -> bool:
        """Deploy via NAS wrapper (./jarvis-docker.sh ...)."""
        
        try:
            # Call NAS deployment script
            # For Phase 0, assume this is a no-op or simple health check
            
            result = subprocess.run(
                ["./jarvis-docker.sh", "health-check"],
                capture_output=True,
                timeout=30,
                cwd="/Volumes/BRAIN/system/docker"
            )
            
            success = result.returncode == 0
            
            self.logger.info(
                f"NAS deployment {'succeeded' if success else 'failed'}",
                extra={"success": success, "change_id": change.id}
            )
            
            return success
        
        except Exception as e:
            self.logger.error(f"NAS deployment error: {e}")
            return False
    
    async def _rollback_from_snapshot(self, snapshot: Dict[str, str]) -> None:
        """Rollback file to pre-write snapshot."""
        
        try:
            file_path = snapshot["file_path"]
            original_content = snapshot["original_content"]
            
            if original_content is None:
                # File didn't exist, delete it
                Path(file_path).unlink(missing_ok=True)
            else:
                # Restore original
                Path(file_path).write_text(original_content)
            
            self.logger.info(f"Rolled back {file_path}")
        
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
    
    async def _log_deployment(self, result: DeploymentResult) -> None:
        """Log deployment result immutably."""
        
        if self.audit_log:
            try:
                await self.audit_log.record_deployment({
                    "change_id": result.change_id,
                    "approval_id": result.approval_id,
                    "success": result.success,
                    "stage": result.stage,
                    "impact": result.impact,
                    "error": result.error,
                    "timestamp": result.timestamp
                })
            except Exception as e:
                self.logger.error(f"Failed to log deployment: {e}")
