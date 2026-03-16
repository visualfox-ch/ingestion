"""
Batch Processor Service (Phase O1).

Multi-provider batch processing for cost optimization.
- OpenAI Batch API: 50% discount, 24h completion
- Anthropic Message Batches: 50% discount (+ caching → 90%)

Supports: embedding, classification, summarization, verification, custom jobs.
"""

import logging
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BatchProcessor:
    """Service for multi-provider batch processing."""

    def __init__(self):
        """Initialize the batch processor."""
        from app.postgres_state import get_cursor
        self.get_cursor = get_cursor
        self._openai_client = None
        self._anthropic_client = None

    @property
    def openai_client(self):
        """Lazy-load OpenAI client."""
        if self._openai_client is None:
            import openai
            import os
            self._openai_client = openai.OpenAI(
                api_key=os.getenv("OPENAI_API_KEY")
            )
        return self._openai_client

    @property
    def anthropic_client(self):
        """Lazy-load Anthropic client."""
        if self._anthropic_client is None:
            import anthropic
            import os
            self._anthropic_client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY")
            )
        return self._anthropic_client

    # =========================================================================
    # Job Creation
    # =========================================================================

    def create_job(
        self,
        provider: str,
        model: str,
        job_type: str,
        requests: List[Dict[str, Any]],
        description: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Create a new batch job.

        Args:
            provider: 'openai' or 'anthropic'
            model: Model to use (e.g., 'gpt-4o-mini', 'claude-3-haiku-20240307')
            job_type: Type of job ('embedding', 'classification', 'summarization', 'verification', 'custom')
            requests: List of request dicts, each with 'custom_id' and request-specific fields
            description: Optional job description
            metadata: Optional metadata

        Returns:
            Job info dict with job_id
        """
        if provider not in ('openai', 'anthropic'):
            raise ValueError(f"Invalid provider: {provider}")

        try:
            with self.get_cursor() as cur:
                # Create job
                cur.execute("""
                    SELECT create_batch_job(%s, %s, %s, %s, %s)
                """, (provider, model, job_type, description, json.dumps(metadata) if metadata else None))
                job_id = cur.fetchone()[0]

                # Add items
                items = []
                for req in requests:
                    custom_id = req.get('custom_id') or f"req_{len(items)}"
                    items.append({
                        "custom_id": custom_id,
                        "request": req
                    })

                cur.execute("""
                    SELECT add_batch_items(%s, %s)
                """, (job_id, json.dumps(items)))
                item_count = cur.fetchone()[0]

                return {
                    "success": True,
                    "job_id": job_id,
                    "provider": provider,
                    "model": model,
                    "job_type": job_type,
                    "request_count": item_count,
                    "status": "pending",
                    "message": f"Batch job created with {item_count} requests. Use submit_batch_job to start."
                }
        except Exception as e:
            logger.error(f"Failed to create batch job: {e}")
            raise

    # =========================================================================
    # Job Submission
    # =========================================================================

    def submit_job(self, job_id: str) -> Dict[str, Any]:
        """
        Submit a batch job to the provider.

        Args:
            job_id: The job ID to submit

        Returns:
            Submission result
        """
        try:
            # Get job details
            job = self._get_job(job_id)
            if not job:
                return {"success": False, "error": f"Job {job_id} not found"}

            if job['status'] != 'pending':
                return {"success": False, "error": f"Job is already {job['status']}"}

            # Get items
            items = self._get_job_items(job_id)
            if not items:
                return {"success": False, "error": "No items in job"}

            # Update status
            self._update_status(job_id, 'uploading')

            # Submit to provider
            if job['provider'] == 'openai':
                result = self._submit_openai(job, items)
            else:
                result = self._submit_anthropic(job, items)

            if result.get('success'):
                self._update_status(
                    job_id,
                    'submitted',
                    provider_batch_id=result.get('provider_batch_id')
                )

            return result

        except Exception as e:
            logger.error(f"Failed to submit job {job_id}: {e}")
            self._update_status(job_id, 'failed')
            return {"success": False, "error": str(e)}

    def _submit_openai(self, job: Dict, items: List[Dict]) -> Dict[str, Any]:
        """Submit batch to OpenAI."""
        import tempfile
        import os

        # Build JSONL content
        jsonl_lines = []
        for item in items:
            request = item['request']
            line = {
                "custom_id": item['custom_id'],
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": job['model'],
                    "messages": request.get('messages', []),
                    "max_tokens": request.get('max_tokens', 1000)
                }
            }
            jsonl_lines.append(json.dumps(line))

        jsonl_content = "\n".join(jsonl_lines)

        # Upload file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write(jsonl_content)
            temp_path = f.name

        try:
            with open(temp_path, 'rb') as f:
                file_response = self.openai_client.files.create(
                    file=f,
                    purpose="batch"
                )

            # Create batch
            batch_response = self.openai_client.batches.create(
                input_file_id=file_response.id,
                endpoint="/v1/chat/completions",
                completion_window="24h",
                metadata={"job_id": job['job_id']}
            )

            return {
                "success": True,
                "provider_batch_id": batch_response.id,
                "input_file_id": file_response.id,
                "status": batch_response.status
            }
        finally:
            os.unlink(temp_path)

    def _submit_anthropic(self, job: Dict, items: List[Dict]) -> Dict[str, Any]:
        """Submit batch to Anthropic."""
        # Build requests
        requests = []
        for item in items:
            request = item['request']
            requests.append({
                "custom_id": item['custom_id'],
                "params": {
                    "model": job['model'],
                    "max_tokens": request.get('max_tokens', 1000),
                    "messages": request.get('messages', [])
                }
            })

        # Create batch
        batch_response = self.anthropic_client.messages.batches.create(
            requests=requests
        )

        return {
            "success": True,
            "provider_batch_id": batch_response.id,
            "status": batch_response.processing_status
        }

    # =========================================================================
    # Status Checking
    # =========================================================================

    def get_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get the status of a batch job.

        Args:
            job_id: The job ID

        Returns:
            Job status info
        """
        try:
            job = self._get_job(job_id)
            if not job:
                return {"error": f"Job {job_id} not found"}

            # If submitted, check with provider
            if job['status'] in ('submitted', 'in_progress') and job['provider_batch_id']:
                if job['provider'] == 'openai':
                    provider_status = self._check_openai_status(job)
                else:
                    provider_status = self._check_anthropic_status(job)

                # Update local status if changed
                if provider_status.get('status') != job['status']:
                    new_status = provider_status.get('status')
                    if new_status in ('completed', 'failed', 'expired', 'cancelled'):
                        self._update_status(
                            job_id,
                            new_status,
                            output_file_id=provider_status.get('output_file_id'),
                            error_file_id=provider_status.get('error_file_id')
                        )
                    elif new_status == 'in_progress':
                        self._update_status(job_id, 'in_progress')

                job.update(provider_status)

            return job

        except Exception as e:
            logger.error(f"Failed to get status for {job_id}: {e}")
            return {"error": str(e)}

    def _check_openai_status(self, job: Dict) -> Dict[str, Any]:
        """Check OpenAI batch status."""
        batch = self.openai_client.batches.retrieve(job['provider_batch_id'])

        status_map = {
            'validating': 'submitted',
            'in_progress': 'in_progress',
            'finalizing': 'in_progress',
            'completed': 'completed',
            'failed': 'failed',
            'expired': 'expired',
            'cancelling': 'in_progress',
            'cancelled': 'cancelled'
        }

        return {
            "status": status_map.get(batch.status, job['status']),
            "provider_status": batch.status,
            "output_file_id": batch.output_file_id,
            "error_file_id": batch.error_file_id,
            "request_counts": {
                "total": batch.request_counts.total if batch.request_counts else 0,
                "completed": batch.request_counts.completed if batch.request_counts else 0,
                "failed": batch.request_counts.failed if batch.request_counts else 0
            }
        }

    def _check_anthropic_status(self, job: Dict) -> Dict[str, Any]:
        """Check Anthropic batch status."""
        batch = self.anthropic_client.messages.batches.retrieve(job['provider_batch_id'])

        status_map = {
            'in_progress': 'in_progress',
            'ended': 'completed'
        }

        return {
            "status": status_map.get(batch.processing_status, job['status']),
            "provider_status": batch.processing_status,
            "request_counts": batch.request_counts.__dict__ if batch.request_counts else {}
        }

    # =========================================================================
    # Result Retrieval
    # =========================================================================

    def get_results(self, job_id: str) -> Dict[str, Any]:
        """
        Retrieve results from a completed batch job.

        Args:
            job_id: The job ID

        Returns:
            Results dict
        """
        try:
            job = self._get_job(job_id)
            if not job:
                return {"error": f"Job {job_id} not found"}

            # Check if already retrieved
            if job.get('results'):
                return {
                    "job_id": job_id,
                    "status": job['status'],
                    "result_count": job['result_count'],
                    "results": job['results']
                }

            # Must be completed
            if job['status'] != 'completed':
                return {"error": f"Job is {job['status']}, not completed"}

            # Retrieve from provider
            if job['provider'] == 'openai':
                results = self._retrieve_openai_results(job)
            else:
                results = self._retrieve_anthropic_results(job)

            # Store results
            self._store_results(job_id, results)

            return {
                "job_id": job_id,
                "status": "completed",
                "result_count": len(results),
                "results": results
            }

        except Exception as e:
            logger.error(f"Failed to get results for {job_id}: {e}")
            return {"error": str(e)}

    def _retrieve_openai_results(self, job: Dict) -> List[Dict]:
        """Retrieve results from OpenAI."""
        if not job.get('output_file_id'):
            return []

        # Download output file
        content = self.openai_client.files.content(job['output_file_id'])
        lines = content.text.strip().split('\n')

        results = []
        for line in lines:
            if line:
                result = json.loads(line)
                results.append({
                    "custom_id": result.get('custom_id'),
                    "response": result.get('response', {}).get('body', {}),
                    "error": result.get('error')
                })

        return results

    def _retrieve_anthropic_results(self, job: Dict) -> List[Dict]:
        """Retrieve results from Anthropic."""
        results = []

        # Stream results
        for result in self.anthropic_client.messages.batches.results(job['provider_batch_id']):
            results.append({
                "custom_id": result.custom_id,
                "response": result.result.message.__dict__ if hasattr(result.result, 'message') else None,
                "error": result.result.error if hasattr(result.result, 'error') else None
            })

        return results

    def _store_results(self, job_id: str, results: List[Dict]) -> None:
        """Store results in database."""
        with self.get_cursor() as cur:
            # Update job
            cur.execute("""
                UPDATE batch_jobs
                SET results = %s,
                    result_count = %s,
                    error_count = %s
                WHERE job_id = %s
            """, (
                json.dumps(results),
                len([r for r in results if not r.get('error')]),
                len([r for r in results if r.get('error')]),
                job_id
            ))

            # Update items
            for result in results:
                cur.execute("""
                    UPDATE batch_job_items
                    SET response = %s,
                        status = %s,
                        error_message = %s,
                        completed_at = NOW()
                    WHERE job_id = %s AND custom_id = %s
                """, (
                    json.dumps(result.get('response')),
                    'error' if result.get('error') else 'success',
                    str(result.get('error')) if result.get('error') else None,
                    job_id,
                    result['custom_id']
                ))

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_job(self, job_id: str) -> Optional[Dict]:
        """Get job from database."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT job_id, provider, model, job_type, description,
                       status, request_count, result_count, error_count,
                       provider_batch_id, output_file_id, error_file_id,
                       results, created_at, submitted_at, completed_at,
                       estimated_cost, actual_cost, metadata
                FROM batch_jobs
                WHERE job_id = %s
            """, (job_id,))
            row = cur.fetchone()
            if not row:
                return None

            return {
                "job_id": row[0],
                "provider": row[1],
                "model": row[2],
                "job_type": row[3],
                "description": row[4],
                "status": row[5],
                "request_count": row[6],
                "result_count": row[7],
                "error_count": row[8],
                "provider_batch_id": row[9],
                "output_file_id": row[10],
                "error_file_id": row[11],
                "results": row[12],
                "created_at": row[13].isoformat() if row[13] else None,
                "submitted_at": row[14].isoformat() if row[14] else None,
                "completed_at": row[15].isoformat() if row[15] else None,
                "estimated_cost": row[16],
                "actual_cost": row[17],
                "metadata": row[18]
            }

    def _get_job_items(self, job_id: str) -> List[Dict]:
        """Get job items from database."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT custom_id, request, response, status
                FROM batch_job_items
                WHERE job_id = %s
                ORDER BY id
            """, (job_id,))
            return [
                {
                    "custom_id": row[0],
                    "request": row[1],
                    "response": row[2],
                    "status": row[3]
                }
                for row in cur.fetchall()
            ]

    def _update_status(
        self,
        job_id: str,
        status: str,
        provider_batch_id: Optional[str] = None,
        output_file_id: Optional[str] = None,
        error_file_id: Optional[str] = None
    ) -> None:
        """Update job status in database."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT update_batch_status(%s, %s, %s, %s, %s)
            """, (job_id, status, provider_batch_id, output_file_id, error_file_id))

    def list_jobs(
        self,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """List batch jobs."""
        with self.get_cursor() as cur:
            query = """
                SELECT job_id, provider, model, job_type, status,
                       request_count, result_count, created_at
                FROM batch_jobs
                WHERE 1=1
            """
            params = []

            if status:
                query += " AND status = %s"
                params.append(status)
            if provider:
                query += " AND provider = %s"
                params.append(provider)

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)

            return [
                {
                    "job_id": row[0],
                    "provider": row[1],
                    "model": row[2],
                    "job_type": row[3],
                    "status": row[4],
                    "request_count": row[5],
                    "result_count": row[6],
                    "created_at": row[7].isoformat() if row[7] else None
                }
                for row in cur.fetchall()
            ]

    def get_stats(self) -> Dict[str, Any]:
        """Get batch processing statistics."""
        with self.get_cursor() as cur:
            cur.execute("""
                SELECT provider, job_type, total_jobs, completed, failed,
                       total_requests, total_cost, avg_duration_seconds
                FROM v_batch_stats
            """)

            stats_by_provider = {}
            for row in cur.fetchall():
                provider = row[0]
                if provider not in stats_by_provider:
                    stats_by_provider[provider] = []
                stats_by_provider[provider].append({
                    "job_type": row[1],
                    "total_jobs": row[2],
                    "completed": row[3],
                    "failed": row[4],
                    "total_requests": row[5],
                    "total_cost": float(row[6]) if row[6] else 0,
                    "avg_duration_seconds": float(row[7]) if row[7] else 0
                })

            # Get cost savings
            cur.execute("""
                SELECT provider, batch_cost, estimated_sync_cost, estimated_savings
                FROM v_batch_cost_savings
            """)

            savings = {}
            for row in cur.fetchall():
                savings[row[0]] = {
                    "batch_cost": float(row[1]) if row[1] else 0,
                    "estimated_sync_cost": float(row[2]) if row[2] else 0,
                    "estimated_savings": float(row[3]) if row[3] else 0
                }

            return {
                "by_provider": stats_by_provider,
                "cost_savings": savings
            }

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """
        Cancel a batch job that hasn't completed yet.

        Args:
            job_id: The job ID to cancel

        Returns:
            Cancellation result
        """
        try:
            job = self._get_job(job_id)
            if not job:
                return {"success": False, "error": f"Job {job_id} not found"}

            # Check if cancelable
            if job['status'] in ('completed', 'failed', 'expired', 'cancelled'):
                return {"success": False, "error": f"Job is already {job['status']}"}

            # Cancel with provider if submitted
            if job['provider_batch_id']:
                if job['provider'] == 'openai':
                    self.openai_client.batches.cancel(job['provider_batch_id'])
                else:
                    self.anthropic_client.messages.batches.cancel(job['provider_batch_id'])

            # Update local status
            self._update_status(job_id, 'cancelled')

            return {
                "success": True,
                "job_id": job_id,
                "status": "cancelled"
            }
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Auto-Batch Queue Methods
    # =========================================================================

    def queue_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = 5
    ) -> Dict[str, Any]:
        """
        Queue a task for batch processing.

        Args:
            task_type: Type of task (learning_extract, pattern_detect, etc.)
            payload: Task-specific data
            priority: 1-10, higher = more urgent

        Returns:
            Queue result with task ID
        """
        try:
            with self.get_cursor() as cur:
                cur.execute(
                    "SELECT queue_for_batch(%s, %s, %s)",
                    (task_type, json.dumps(payload), priority)
                )
                task_id = cur.fetchone()[0]

            return {
                "success": True,
                "task_id": task_id,
                "task_type": task_type,
                "priority": priority,
                "message": f"Task queued. Will be processed in next batch run."
            }
        except Exception as e:
            logger.error(f"Failed to queue task: {e}")
            return {"success": False, "error": str(e)}

    def process_queue(
        self,
        task_type: str,
        model: str = "claude-haiku-4-5",
        max_batch_size: int = 50
    ) -> Dict[str, Any]:
        """
        Process queued tasks of a given type as a batch.

        Args:
            task_type: Type of tasks to process
            model: Model to use for processing
            max_batch_size: Max tasks per batch

        Returns:
            Batch submission result
        """
        try:
            with self.get_cursor() as cur:
                # Get queued tasks
                cur.execute(
                    "SELECT * FROM get_batch_queue(%s, %s)",
                    (task_type, max_batch_size)
                )
                tasks = cur.fetchall()

            if not tasks:
                return {"success": True, "message": "No tasks in queue"}

            # Build batch requests
            requests = []
            task_ids = []
            for task in tasks:
                task_id, payload, priority, queued_at = task
                task_ids.append(task_id)

                # Build request based on task type
                if task_type == "learning_extract":
                    requests.append({
                        "custom_id": f"learn_{task_id}",
                        "messages": [
                            {"role": "system", "content": "Extract key learnings from this conversation summary."},
                            {"role": "user", "content": json.dumps(payload)}
                        ],
                        "max_tokens": 500
                    })
                elif task_type == "pattern_detect":
                    requests.append({
                        "custom_id": f"pattern_{task_id}",
                        "messages": [
                            {"role": "system", "content": "Identify patterns and recurring themes."},
                            {"role": "user", "content": json.dumps(payload)}
                        ],
                        "max_tokens": 300
                    })
                else:
                    # Custom type - payload should include messages
                    requests.append({
                        "custom_id": f"custom_{task_id}",
                        **payload
                    })

            # Create and submit batch
            job_result = self.create_job(
                provider="anthropic",
                model=model,
                job_type=task_type,
                requests=requests,
                description=f"Auto-batch: {len(requests)} {task_type} tasks"
            )

            if not job_result.get("success"):
                return job_result

            job_id = job_result["job_id"]

            # Mark tasks as batched
            with self.get_cursor() as cur:
                cur.execute(
                    "SELECT mark_queue_batched(%s, %s)",
                    (task_ids, job_id)
                )

            # Submit to provider
            submit_result = self.submit_job(job_id)

            return {
                "success": True,
                "job_id": job_id,
                "task_count": len(requests),
                "task_type": task_type,
                "status": submit_result.get("status", "submitted"),
                "message": f"Batch submitted with {len(requests)} tasks. 50% cost savings."
            }
        except Exception as e:
            logger.error(f"Failed to process queue: {e}")
            return {"success": False, "error": str(e)}

    def get_queue_status(self) -> Dict[str, Any]:
        """Get summary of queued tasks."""
        try:
            with self.get_cursor() as cur:
                cur.execute("SELECT * FROM v_batch_queue_summary")
                rows = cur.fetchall()

            summary = {}
            for row in rows:
                task_type, status, count, avg_priority, oldest = row
                if task_type not in summary:
                    summary[task_type] = {}
                summary[task_type][status] = {
                    "count": count,
                    "avg_priority": float(avg_priority) if avg_priority else 0,
                    "oldest": oldest.isoformat() if oldest else None
                }

            return {
                "success": True,
                "queue_summary": summary
            }
        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_processor_instance: Optional[BatchProcessor] = None


def get_batch_processor() -> BatchProcessor:
    """Get the singleton batch processor instance."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = BatchProcessor()
    return _processor_instance
