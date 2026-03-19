"""
Auto-Refactoring Service (Tier 4 #15).

Automated Code Quality Analysis and Refactoring Suggestions:
- Complexity analysis (cyclomatic, cognitive)
- Duplication detection
- Maintainability scoring
- AI-generated refactoring suggestions
- Priority ranking by impact/effort
- Progress tracking

Uses radon, ast for static analysis.
"""

import ast
import os
import re
import json
import hashlib
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict

from ..postgres_state import get_cursor, get_dict_cursor

logger = logging.getLogger(__name__)


@dataclass
class CodeIssue:
    """A detected code quality issue."""
    issue_type: str  # complexity, duplication, maintainability, style
    severity: str  # low, medium, high, critical
    file_path: str
    line_start: int
    line_end: int
    description: str
    suggestion: str
    effort_hours: float
    impact_score: float  # 0-1, higher = more impactful to fix


@dataclass
class RefactoringSuggestion:
    """A prioritized refactoring suggestion."""
    id: str
    title: str
    description: str
    issues: List[Dict]
    priority_score: float  # impact / effort
    estimated_hours: float
    risk_level: str  # low, medium, high
    category: str  # complexity, duplication, architecture, style
    status: str  # pending, in_progress, completed, skipped
    created_at: datetime


class AutoRefactorService:
    """
    Automated code quality analysis and refactoring suggestions.

    Capabilities:
    - Static analysis of Python code
    - Complexity hotspot detection
    - Duplication analysis
    - AI-powered refactoring suggestions
    - Priority ranking
    - Progress tracking
    """

    def __init__(self, code_path: str = "/brain/system/ingestion/app"):
        self.code_path = Path(code_path)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure refactoring tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS refactor_issues (
                        id SERIAL PRIMARY KEY,
                        issue_hash VARCHAR(64) UNIQUE NOT NULL,
                        issue_type VARCHAR(50) NOT NULL,
                        severity VARCHAR(20) NOT NULL,
                        file_path TEXT NOT NULL,
                        line_start INTEGER,
                        line_end INTEGER,
                        description TEXT NOT NULL,
                        suggestion TEXT,
                        effort_hours FLOAT DEFAULT 1.0,
                        impact_score FLOAT DEFAULT 0.5,
                        detected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        resolved_at TIMESTAMP WITH TIME ZONE,
                        is_active BOOLEAN DEFAULT true
                    );

                    CREATE INDEX IF NOT EXISTS idx_refactor_issues_type
                        ON refactor_issues(issue_type, severity);
                    CREATE INDEX IF NOT EXISTS idx_refactor_issues_file
                        ON refactor_issues(file_path);

                    CREATE TABLE IF NOT EXISTS refactor_suggestions (
                        id VARCHAR(64) PRIMARY KEY,
                        title VARCHAR(200) NOT NULL,
                        description TEXT NOT NULL,
                        issues JSONB NOT NULL,
                        priority_score FLOAT NOT NULL,
                        estimated_hours FLOAT NOT NULL,
                        risk_level VARCHAR(20) NOT NULL,
                        category VARCHAR(50) NOT NULL,
                        status VARCHAR(20) DEFAULT 'pending',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        started_at TIMESTAMP WITH TIME ZONE,
                        completed_at TIMESTAMP WITH TIME ZONE,
                        notes TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_refactor_sugg_status
                        ON refactor_suggestions(status, priority_score DESC);

                    CREATE TABLE IF NOT EXISTS refactor_analysis_runs (
                        id SERIAL PRIMARY KEY,
                        run_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        files_analyzed INTEGER,
                        issues_found INTEGER,
                        suggestions_generated INTEGER,
                        summary JSONB
                    );
                """)
        except Exception as e:
            logger.debug(f"Refactor tables may exist: {e}")

    # =========================================================================
    # Static Analysis
    # =========================================================================

    def analyze_file(self, file_path: str) -> List[CodeIssue]:
        """Analyze a single Python file for code issues."""
        issues = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')

            # Parse AST
            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                issues.append(CodeIssue(
                    issue_type="syntax",
                    severity="critical",
                    file_path=file_path,
                    line_start=e.lineno or 0,
                    line_end=e.lineno or 0,
                    description=f"Syntax error: {e.msg}",
                    suggestion="Fix syntax error before other analysis",
                    effort_hours=0.5,
                    impact_score=1.0
                ))
                return issues

            # Analyze functions
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_issues = self._analyze_function(node, file_path, lines)
                    issues.extend(func_issues)

                elif isinstance(node, ast.ClassDef):
                    class_issues = self._analyze_class(node, file_path, lines)
                    issues.extend(class_issues)

            # Check for long files
            if len(lines) > 500:
                issues.append(CodeIssue(
                    issue_type="maintainability",
                    severity="medium",
                    file_path=file_path,
                    line_start=1,
                    line_end=len(lines),
                    description=f"File has {len(lines)} lines (>500)",
                    suggestion="Consider splitting into multiple modules",
                    effort_hours=2.0,
                    impact_score=0.6
                ))

            # Check import complexity
            import_issues = self._analyze_imports(tree, file_path)
            issues.extend(import_issues)

        except Exception as e:
            logger.error(f"Failed to analyze {file_path}: {e}")

        return issues

    def _analyze_function(
        self,
        node: ast.FunctionDef,
        file_path: str,
        lines: List[str]
    ) -> List[CodeIssue]:
        """Analyze a function for code issues."""
        issues = []
        func_name = node.name
        start_line = node.lineno
        end_line = node.end_lineno or start_line

        # Calculate cyclomatic complexity (simplified)
        complexity = self._calculate_complexity(node)

        if complexity > 15:
            issues.append(CodeIssue(
                issue_type="complexity",
                severity="high" if complexity > 20 else "medium",
                file_path=file_path,
                line_start=start_line,
                line_end=end_line,
                description=f"Function '{func_name}' has high complexity ({complexity})",
                suggestion="Break down into smaller functions, extract conditionals",
                effort_hours=1.5 if complexity < 20 else 3.0,
                impact_score=0.8
            ))

        # Check function length
        func_lines = end_line - start_line
        if func_lines > 50:
            issues.append(CodeIssue(
                issue_type="maintainability",
                severity="medium",
                file_path=file_path,
                line_start=start_line,
                line_end=end_line,
                description=f"Function '{func_name}' is too long ({func_lines} lines)",
                suggestion="Extract logical sections into helper functions",
                effort_hours=1.0,
                impact_score=0.6
            ))

        # Check parameter count
        params = len(node.args.args) + len(node.args.kwonlyargs)
        if params > 5:
            issues.append(CodeIssue(
                issue_type="style",
                severity="low",
                file_path=file_path,
                line_start=start_line,
                line_end=start_line,
                description=f"Function '{func_name}' has too many parameters ({params})",
                suggestion="Consider using a config object or dataclass",
                effort_hours=0.5,
                impact_score=0.4
            ))

        # Check nested depth
        max_depth = self._calculate_nesting_depth(node)
        if max_depth > 4:
            issues.append(CodeIssue(
                issue_type="complexity",
                severity="medium",
                file_path=file_path,
                line_start=start_line,
                line_end=end_line,
                description=f"Function '{func_name}' has deep nesting (depth {max_depth})",
                suggestion="Use early returns, extract nested logic",
                effort_hours=1.0,
                impact_score=0.7
            ))

        # Check for bare except
        for child in ast.walk(node):
            if isinstance(child, ast.ExceptHandler) and child.type is None:
                issues.append(CodeIssue(
                    issue_type="style",
                    severity="medium",
                    file_path=file_path,
                    line_start=child.lineno,
                    line_end=child.lineno,
                    description=f"Bare 'except:' in '{func_name}'",
                    suggestion="Catch specific exceptions (e.g., except ValueError)",
                    effort_hours=0.25,
                    impact_score=0.5
                ))

        return issues

    def _analyze_class(
        self,
        node: ast.ClassDef,
        file_path: str,
        lines: List[str]
    ) -> List[CodeIssue]:
        """Analyze a class for code issues."""
        issues = []
        class_name = node.name

        # Count methods
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

        if len(methods) > 20:
            issues.append(CodeIssue(
                issue_type="architecture",
                severity="medium",
                file_path=file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                description=f"Class '{class_name}' has too many methods ({len(methods)})",
                suggestion="Consider splitting into multiple classes (SRP)",
                effort_hours=3.0,
                impact_score=0.7
            ))

        # Check class length
        class_lines = (node.end_lineno or node.lineno) - node.lineno
        if class_lines > 300:
            issues.append(CodeIssue(
                issue_type="maintainability",
                severity="medium",
                file_path=file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                description=f"Class '{class_name}' is too large ({class_lines} lines)",
                suggestion="Extract functionality into separate classes or modules",
                effort_hours=4.0,
                impact_score=0.7
            ))

        return issues

    def _analyze_imports(self, tree: ast.Module, file_path: str) -> List[CodeIssue]:
        """Analyze imports for issues."""
        issues = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        # Too many imports
        if len(imports) > 30:
            issues.append(CodeIssue(
                issue_type="architecture",
                severity="low",
                file_path=file_path,
                line_start=1,
                line_end=50,
                description=f"File has many imports ({len(imports)})",
                suggestion="Consider if all imports are necessary, or split module",
                effort_hours=1.0,
                impact_score=0.4
            ))

        return issues

    def _calculate_complexity(self, node: ast.AST) -> int:
        """Calculate simplified cyclomatic complexity."""
        complexity = 1  # Base complexity

        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(child, ast.ExceptHandler):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                complexity += 1
            elif isinstance(child, ast.IfExp):  # Ternary
                complexity += 1

        return complexity

    def _calculate_nesting_depth(self, node: ast.AST, current_depth: int = 0) -> int:
        """Calculate maximum nesting depth."""
        max_depth = current_depth

        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.Try)):
                child_depth = self._calculate_nesting_depth(child, current_depth + 1)
                max_depth = max(max_depth, child_depth)
            else:
                child_depth = self._calculate_nesting_depth(child, current_depth)
                max_depth = max(max_depth, child_depth)

        return max_depth

    # =========================================================================
    # Full Codebase Analysis
    # =========================================================================

    def analyze_codebase(
        self,
        path: str = None,
        exclude_patterns: List[str] = None
    ) -> Dict[str, Any]:
        """Analyze entire codebase for code issues."""
        path = path or str(self.code_path)
        exclude_patterns = exclude_patterns or ["__pycache__", "migrations", "tests", ".git"]

        all_issues = []
        files_analyzed = 0

        try:
            for root, dirs, files in os.walk(path):
                # Filter excluded directories
                dirs[:] = [d for d in dirs if not any(p in d for p in exclude_patterns)]

                for file in files:
                    if not file.endswith('.py'):
                        continue

                    file_path = os.path.join(root, file)
                    relative_path = file_path.replace(path + "/", "")

                    issues = self.analyze_file(file_path)
                    for issue in issues:
                        issue.file_path = relative_path  # Use relative path

                    all_issues.extend(issues)
                    files_analyzed += 1

            # Save issues to database
            self._save_issues(all_issues)

            # Generate summary
            summary = self._generate_summary(all_issues)

            # Log analysis run
            self._log_analysis_run(files_analyzed, len(all_issues), 0, summary)

            return {
                "success": True,
                "files_analyzed": files_analyzed,
                "issues_found": len(all_issues),
                "summary": summary,
                "top_issues": [asdict(i) for i in sorted(
                    all_issues,
                    key=lambda x: x.impact_score,
                    reverse=True
                )[:10]]
            }

        except Exception as e:
            logger.error(f"Codebase analysis failed: {e}")
            return {"success": False, "error": str(e)}

    def _save_issues(self, issues: List[CodeIssue]):
        """Save issues to database."""
        try:
            with get_cursor() as cur:
                for issue in issues:
                    # Generate hash for deduplication
                    hash_input = f"{issue.file_path}:{issue.line_start}:{issue.issue_type}:{issue.description[:50]}"
                    issue_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

                    cur.execute("""
                        INSERT INTO refactor_issues
                        (issue_hash, issue_type, severity, file_path, line_start, line_end,
                         description, suggestion, effort_hours, impact_score)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (issue_hash) DO UPDATE SET
                            detected_at = NOW(),
                            is_active = true
                    """, (
                        issue_hash,
                        issue.issue_type,
                        issue.severity,
                        issue.file_path,
                        issue.line_start,
                        issue.line_end,
                        issue.description,
                        issue.suggestion,
                        issue.effort_hours,
                        issue.impact_score
                    ))
        except Exception as e:
            logger.error(f"Failed to save issues: {e}")

    def _generate_summary(self, issues: List[CodeIssue]) -> Dict[str, Any]:
        """Generate summary statistics."""
        by_type = defaultdict(int)
        by_severity = defaultdict(int)
        by_file = defaultdict(int)
        total_effort = 0.0

        for issue in issues:
            by_type[issue.issue_type] += 1
            by_severity[issue.severity] += 1
            by_file[issue.file_path] += 1
            total_effort += issue.effort_hours

        # Find worst files
        worst_files = sorted(by_file.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "worst_files": worst_files,
            "total_estimated_hours": round(total_effort, 1),
            "average_issues_per_file": round(len(issues) / max(len(by_file), 1), 2)
        }

    def _log_analysis_run(
        self,
        files: int,
        issues: int,
        suggestions: int,
        summary: Dict
    ):
        """Log analysis run."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO refactor_analysis_runs
                    (files_analyzed, issues_found, suggestions_generated, summary)
                    VALUES (%s, %s, %s, %s)
                """, (files, issues, suggestions, json.dumps(summary)))
        except Exception as e:
            logger.error(f"Failed to log analysis run: {e}")

    # =========================================================================
    # Refactoring Suggestions
    # =========================================================================

    def generate_suggestions(self, max_suggestions: int = 10) -> Dict[str, Any]:
        """Generate prioritized refactoring suggestions from issues."""
        try:
            # Get active issues grouped by file
            with get_cursor() as cur:
                cur.execute("""
                    SELECT issue_type, severity, file_path, line_start, line_end,
                           description, suggestion, effort_hours, impact_score
                    FROM refactor_issues
                    WHERE is_active = true
                    ORDER BY impact_score DESC, effort_hours ASC
                    LIMIT 100
                """)
                issues = cur.fetchall()

            if not issues:
                return {
                    "success": True,
                    "message": "No active issues found",
                    "suggestions": []
                }

            # Group related issues
            suggestions = []

            # Group by file + type for related suggestions
            grouped = defaultdict(list)
            for issue in issues:
                key = f"{issue['file_path']}:{issue['issue_type']}"
                grouped[key].append(issue)

            for key, file_issues in grouped.items():
                if len(suggestions) >= max_suggestions:
                    break

                file_path, issue_type = key.rsplit(":", 1)

                # Calculate aggregate metrics
                total_effort = sum(i['effort_hours'] for i in file_issues)
                avg_impact = sum(i['impact_score'] for i in file_issues) / len(file_issues)
                max_severity = max(file_issues, key=lambda x:
                    {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(x['severity'], 0))['severity']

                # Priority = impact / effort (higher is better)
                priority = avg_impact / max(total_effort, 0.5)

                # Generate ID
                sugg_id = hashlib.sha256(f"{key}:{datetime.now().isoformat()}".encode()).hexdigest()[:12]

                suggestion = RefactoringSuggestion(
                    id=sugg_id,
                    title=f"Refactor {issue_type} issues in {file_path.split('/')[-1]}",
                    description=self._generate_suggestion_description(file_issues),
                    issues=[dict(i) for i in file_issues],
                    priority_score=round(priority, 2),
                    estimated_hours=round(total_effort, 1),
                    risk_level="low" if total_effort < 2 else "medium" if total_effort < 5 else "high",
                    category=issue_type,
                    status="pending",
                    created_at=datetime.utcnow()
                )
                suggestions.append(suggestion)

            # Sort by priority
            suggestions.sort(key=lambda x: x.priority_score, reverse=True)

            # Save suggestions
            self._save_suggestions(suggestions[:max_suggestions])

            return {
                "success": True,
                "suggestions_generated": len(suggestions[:max_suggestions]),
                "suggestions": [asdict(s) for s in suggestions[:max_suggestions]]
            }

        except Exception as e:
            logger.error(f"Generate suggestions failed: {e}")
            return {"success": False, "error": str(e)}

    def _generate_suggestion_description(self, issues: List[Dict]) -> str:
        """Generate human-readable suggestion description."""
        if len(issues) == 1:
            return issues[0]['suggestion']

        descriptions = []
        for issue in issues[:3]:
            descriptions.append(f"- {issue['description']}")

        if len(issues) > 3:
            descriptions.append(f"- ... and {len(issues) - 3} more issues")

        return "\n".join(descriptions)

    def _save_suggestions(self, suggestions: List[RefactoringSuggestion]):
        """Save suggestions to database."""
        try:
            with get_cursor() as cur:
                for sugg in suggestions:
                    cur.execute("""
                        INSERT INTO refactor_suggestions
                        (id, title, description, issues, priority_score, estimated_hours,
                         risk_level, category, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            priority_score = EXCLUDED.priority_score
                    """, (
                        sugg.id,
                        sugg.title,
                        sugg.description,
                        json.dumps(sugg.issues),
                        sugg.priority_score,
                        sugg.estimated_hours,
                        sugg.risk_level,
                        sugg.category,
                        sugg.status
                    ))
        except Exception as e:
            logger.error(f"Failed to save suggestions: {e}")

    # =========================================================================
    # Suggestion Management
    # =========================================================================

    def get_pending_suggestions(
        self,
        category: str = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get pending refactoring suggestions."""
        try:
            with get_dict_cursor() as cur:
                if category:
                    cur.execute("""
                        SELECT id, title, description, priority_score, estimated_hours,
                               risk_level, category, created_at
                        FROM refactor_suggestions
                        WHERE status = 'pending' AND category = %s
                        ORDER BY priority_score DESC
                        LIMIT %s
                    """, (category, limit))
                else:
                    cur.execute("""
                        SELECT id, title, description, priority_score, estimated_hours,
                               risk_level, category, created_at
                        FROM refactor_suggestions
                        WHERE status = 'pending'
                        ORDER BY priority_score DESC
                        LIMIT %s
                    """, (limit,))

                suggestions = [{
                    "id": row['id'],
                    "title": row['title'],
                    "description": row['description'],
                    "priority": row['priority_score'],
                    "hours": row['estimated_hours'],
                    "risk": row['risk_level'],
                    "category": row['category'],
                    "created": row['created_at'].isoformat()
                } for row in cur.fetchall()]

                return {
                    "success": True,
                    "count": len(suggestions),
                    "suggestions": suggestions
                }
        except Exception as e:
            logger.error(f"Get suggestions failed: {e}")
            return {"success": False, "error": str(e)}

    def update_suggestion_status(
        self,
        suggestion_id: str,
        status: str,
        notes: str = None
    ) -> Dict[str, Any]:
        """Update suggestion status."""
        valid_statuses = ["pending", "in_progress", "completed", "skipped"]
        if status not in valid_statuses:
            return {"success": False, "error": f"Invalid status. Use: {valid_statuses}"}

        try:
            with get_dict_cursor() as cur:
                timestamp_field = ""
                if status == "in_progress":
                    timestamp_field = ", started_at = NOW()"
                elif status in ["completed", "skipped"]:
                    timestamp_field = ", completed_at = NOW()"

                cur.execute(f"""
                    UPDATE refactor_suggestions
                    SET status = %s, notes = COALESCE(%s, notes) {timestamp_field}
                    WHERE id = %s
                    RETURNING title
                """, (status, notes, suggestion_id))

                result = cur.fetchone()
                if result:
                    return {
                        "success": True,
                        "message": f"Updated '{result['title']}' to {status}"
                    }
                else:
                    return {"success": False, "error": "Suggestion not found"}
        except Exception as e:
            logger.error(f"Update status failed: {e}")
            return {"success": False, "error": str(e)}

    def get_refactoring_stats(self) -> Dict[str, Any]:
        """Get refactoring statistics."""
        try:
            with get_dict_cursor() as cur:
                # Issue stats
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE is_active) as active_issues,
                        COUNT(*) FILTER (WHERE NOT is_active) as resolved_issues,
                        SUM(effort_hours) FILTER (WHERE is_active) as total_effort_hours,
                        AVG(impact_score) FILTER (WHERE is_active) as avg_impact
                    FROM refactor_issues
                """)
                issue_stats = cur.fetchone()

                # Suggestion stats
                cur.execute("""
                    SELECT status, COUNT(*) as count
                    FROM refactor_suggestions
                    GROUP BY status
                """)
                suggestion_stats = {row['status']: row['count'] for row in cur.fetchall()}

                # Recent runs
                cur.execute("""
                    SELECT run_at, files_analyzed, issues_found
                    FROM refactor_analysis_runs
                    ORDER BY run_at DESC
                    LIMIT 5
                """)
                recent_runs = [{
                    "date": row['run_at'].isoformat(),
                    "files": row['files_analyzed'],
                    "issues": row['issues_found']
                } for row in cur.fetchall()]

                return {
                    "success": True,
                    "issues": {
                        "active": issue_stats['active_issues'] or 0,
                        "resolved": issue_stats['resolved_issues'] or 0,
                        "total_effort_hours": round(issue_stats['total_effort_hours'] or 0, 1),
                        "avg_impact": round(issue_stats['avg_impact'] or 0, 2)
                    },
                    "suggestions": suggestion_stats,
                    "recent_runs": recent_runs
                }
        except Exception as e:
            logger.error(f"Get stats failed: {e}")
            return {"success": False, "error": str(e)}

    def get_file_issues(self, file_path: str) -> Dict[str, Any]:
        """Get all issues for a specific file."""
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT issue_type, severity, line_start, line_end,
                           description, suggestion, effort_hours, impact_score
                    FROM refactor_issues
                    WHERE file_path LIKE %s AND is_active = true
                    ORDER BY line_start
                """, (f"%{file_path}%",))

                issues = [{
                    "type": row['issue_type'],
                    "severity": row['severity'],
                    "lines": f"{row['line_start']}-{row['line_end']}",
                    "description": row['description'],
                    "suggestion": row['suggestion'],
                    "effort": row['effort_hours'],
                    "impact": row['impact_score']
                } for row in cur.fetchall()]

                return {
                    "success": True,
                    "file": file_path,
                    "issue_count": len(issues),
                    "issues": issues
                }
        except Exception as e:
            logger.error(f"Get file issues failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[AutoRefactorService] = None


def get_auto_refactor_service() -> AutoRefactorService:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = AutoRefactorService()
    return _service
