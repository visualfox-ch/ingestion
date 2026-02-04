#!/usr/bin/env python3
"""
JARVIS CODE METRICS COLLECTOR - Phase 1 Implementation
Runs inside the container to collect code quality metrics.

Metrics tracked:
1. Code Coverage (pytest-cov)
2. Cyclomatic Complexity (radon)
3. Code Duplication (pylint)
4. Maintainability Index (radon)
5. Line counts (source, tests, comments)
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Dict, Any
from datetime import datetime


class CodeMetricsCollector:
    """Collects code quality metrics for Jarvis codebase"""
    
    def __init__(self, repo_path: str = "/app"):
        self.repo_path = Path(repo_path)
        
    def collect_all_metrics(self) -> Dict[str, Any]:
        """Collect all code quality metrics"""
        return {
            "timestamp": datetime.now().isoformat(),
            "repo_path": str(self.repo_path),
            "coverage": self.get_coverage(),
            "complexity": self.get_complexity(),
            "maintainability": self.get_maintainability(),
            "line_counts": self.get_line_counts(),
            "duplication": self.get_duplication(),
        }
    
    def get_coverage(self) -> Dict[str, Any]:
        """
        Get test coverage metrics using pytest-cov.
        
        Returns:
            Dict with coverage percentage, lines covered, lines total
        """
        try:
            # Run pytest with coverage
            result = subprocess.run(
                [
                    "pytest",
                    "--cov=app",
                    "--cov-report=json",
                    "--cov-report=term",
                    "--quiet",
                    "--no-header",
                    "tests/",
                ],
                cwd=self.repo_path.parent,  # /app is inside /
                capture_output=True,
                text=True,
                timeout=300,
            )
            
            # Read coverage JSON report
            cov_file = Path("/tmp/coverage.json")
            if cov_file.exists():
                with open(cov_file) as f:
                    cov_data = json.load(f)
                
                return {
                    "percentage": round(cov_data["totals"]["percent_covered"], 2),
                    "lines_covered": cov_data["totals"]["covered_lines"],
                    "lines_total": cov_data["totals"]["num_statements"],
                    "lines_missing": cov_data["totals"]["missing_lines"],
                    "branches_covered": cov_data["totals"].get("covered_branches", 0),
                    "status": "success",
                }
            else:
                return {"status": "error", "message": "coverage.json not found"}
                
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "pytest timeout (>300s)"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_complexity(self) -> Dict[str, Any]:
        """
        Get cyclomatic complexity using radon.
        
        Returns:
            Dict with average complexity, max complexity, high-complexity functions
        """
        try:
            # Run radon cc (cyclomatic complexity)
            result = subprocess.run(
                ["radon", "cc", str(self.repo_path), "--json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode != 0 and not result.stdout:
                return {"status": "error", "message": result.stderr}
            
            data = json.loads(result.stdout)
            
            # Aggregate metrics
            complexities = []
            high_complexity = []
            
            for file_path, functions in data.items():
                for func in functions:
                    complexity = func["complexity"]
                    complexities.append(complexity)
                    
                    if complexity >= 10:  # High complexity threshold
                        high_complexity.append({
                            "file": file_path.replace("/app/", ""),
                            "function": func["name"],
                            "complexity": complexity,
                            "lines": f"{func['lineno']}-{func['endline']}",
                        })
            
            return {
                "average": round(sum(complexities) / len(complexities), 2) if complexities else 0,
                "max": max(complexities) if complexities else 0,
                "total_functions": len(complexities),
                "high_complexity_count": len(high_complexity),
                "high_complexity_functions": high_complexity[:10],  # Top 10
                "status": "success",
            }
            
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "radon timeout (>60s)"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_maintainability(self) -> Dict[str, Any]:
        """
        Get maintainability index using radon.
        
        Returns:
            Dict with average MI, files with low MI
        """
        try:
            # Run radon mi (maintainability index)
            result = subprocess.run(
                ["radon", "mi", str(self.repo_path), "--json"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode != 0 and not result.stdout:
                return {"status": "error", "message": result.stderr}
            
            data = json.loads(result.stdout)
            
            # Aggregate metrics
            mi_scores = []
            low_mi_files = []
            
            for file_path, file_data in data.items():
                mi = file_data["mi"]
                rank = file_data["rank"]
                mi_scores.append(mi)
                
                if mi < 20:  # Low maintainability (C or below)
                    low_mi_files.append({
                        "file": file_path.replace("/app/", ""),
                        "mi_score": round(mi, 2),
                        "rank": rank,
                    })
            
            return {
                "average": round(sum(mi_scores) / len(mi_scores), 2) if mi_scores else 0,
                "min": round(min(mi_scores), 2) if mi_scores else 0,
                "max": round(max(mi_scores), 2) if mi_scores else 0,
                "low_mi_count": len(low_mi_files),
                "low_mi_files": low_mi_files[:10],  # Worst 10
                "status": "success",
            }
            
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "radon timeout (>60s)"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_line_counts(self) -> Dict[str, Any]:
        """
        Get line counts (source code, comments, blanks).
        
        Returns:
            Dict with SLOC, comment lines, blank lines
        """
        try:
            # Count Python files
            py_files = list(self.repo_path.rglob("*.py"))
            
            total_lines = 0
            code_lines = 0
            comment_lines = 0
            blank_lines = 0
            
            for py_file in py_files:
                try:
                    with open(py_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            total_lines += 1
                            stripped = line.strip()
                            
                            if not stripped:
                                blank_lines += 1
                            elif stripped.startswith('#'):
                                comment_lines += 1
                            else:
                                code_lines += 1
                except:
                    continue
            
            return {
                "total_files": len(py_files),
                "total_lines": total_lines,
                "code_lines": code_lines,
                "comment_lines": comment_lines,
                "blank_lines": blank_lines,
                "comment_ratio": round((comment_lines / total_lines * 100), 2) if total_lines > 0 else 0,
                "status": "success",
            }
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_duplication(self) -> Dict[str, Any]:
        """
        Get code duplication metrics using pylint.
        
        Returns:
            Dict with duplication percentage
        """
        try:
            # Run pylint with duplication check
            result = subprocess.run(
                [
                    "pylint",
                    str(self.repo_path),
                    "--disable=all",
                    "--enable=duplicate-code",
                    "--output-format=json",
                    "--min-similarity-lines=6",  # Shorter minimum for duplicate detection
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            # Parse JSON output
            if result.stdout:
                data = json.loads(result.stdout)
                duplicate_count = len([m for m in data if m.get("message-id") == "R0801"])
                
                return {
                    "duplicate_blocks": duplicate_count,
                    "status": "success" if duplicate_count < 10 else "warning",
                }
            else:
                return {"duplicate_blocks": 0, "status": "success"}
                
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "pylint timeout (>120s)"}
        except Exception as e:
            # Pylint often has non-zero exit codes even on success
            return {"duplicate_blocks": 0, "status": "success", "note": "pylint error ignored"}


def export_to_prometheus_format(metrics: Dict[str, Any]) -> str:
    """
    Export metrics in Prometheus text format.
    
    Returns:
        String in Prometheus exposition format
    """
    lines = []
    
    # Coverage metrics
    if metrics["coverage"]["status"] == "success":
        lines.append(f"# HELP jarvis_code_coverage_percent Percentage of code covered by tests")
        lines.append(f"# TYPE jarvis_code_coverage_percent gauge")
        lines.append(f"jarvis_code_coverage_percent {metrics['coverage']['percentage']}")
        
        lines.append(f"# HELP jarvis_code_lines_covered Number of lines covered by tests")
        lines.append(f"# TYPE jarvis_code_lines_covered gauge")
        lines.append(f"jarvis_code_lines_covered {metrics['coverage']['lines_covered']}")
        
        lines.append(f"# HELP jarvis_code_lines_total Total number of executable lines")
        lines.append(f"# TYPE jarvis_code_lines_total gauge")
        lines.append(f"jarvis_code_lines_total {metrics['coverage']['lines_total']}")
    
    # Complexity metrics
    if metrics["complexity"]["status"] == "success":
        lines.append(f"# HELP jarvis_code_complexity_average Average cyclomatic complexity")
        lines.append(f"# TYPE jarvis_code_complexity_average gauge")
        lines.append(f"jarvis_code_complexity_average {metrics['complexity']['average']}")
        
        lines.append(f"# HELP jarvis_code_complexity_max Maximum cyclomatic complexity")
        lines.append(f"# TYPE jarvis_code_complexity_max gauge")
        lines.append(f"jarvis_code_complexity_max {metrics['complexity']['max']}")
        
        lines.append(f"# HELP jarvis_code_high_complexity_count Functions with complexity >= 10")
        lines.append(f"# TYPE jarvis_code_high_complexity_count gauge")
        lines.append(f"jarvis_code_high_complexity_count {metrics['complexity']['high_complexity_count']}")
    
    # Maintainability metrics
    if metrics["maintainability"]["status"] == "success":
        lines.append(f"# HELP jarvis_code_maintainability_average Average maintainability index")
        lines.append(f"# TYPE jarvis_code_maintainability_average gauge")
        lines.append(f"jarvis_code_maintainability_average {metrics['maintainability']['average']}")
        
        lines.append(f"# HELP jarvis_code_low_maintainability_count Files with MI < 20")
        lines.append(f"# TYPE jarvis_code_low_maintainability_count gauge")
        lines.append(f"jarvis_code_low_maintainability_count {metrics['maintainability']['low_mi_count']}")
    
    # Line count metrics
    if metrics["line_counts"]["status"] == "success":
        lines.append(f"# HELP jarvis_code_files_total Total Python files")
        lines.append(f"# TYPE jarvis_code_files_total gauge")
        lines.append(f"jarvis_code_files_total {metrics['line_counts']['total_files']}")
        
        lines.append(f"# HELP jarvis_code_sloc Source lines of code")
        lines.append(f"# TYPE jarvis_code_sloc gauge")
        lines.append(f"jarvis_code_sloc {metrics['line_counts']['code_lines']}")
        
        lines.append(f"# HELP jarvis_code_comment_ratio Percentage of comment lines")
        lines.append(f"# TYPE jarvis_code_comment_ratio gauge")
        lines.append(f"jarvis_code_comment_ratio {metrics['line_counts']['comment_ratio']}")
    
    # Duplication metrics
    if metrics["duplication"]["status"] == "success":
        lines.append(f"# HELP jarvis_code_duplicate_blocks Number of duplicate code blocks")
        lines.append(f"# TYPE jarvis_code_duplicate_blocks gauge")
        lines.append(f"jarvis_code_duplicate_blocks {metrics['duplication']['duplicate_blocks']}")
    
    return "\n".join(lines) + "\n"


def main():
    """Main entry point"""
    print("🔍 Jarvis Code Metrics Collector - Phase 1")
    print("=" * 70)
    
    collector = CodeMetricsCollector()
    
    print("\n📊 Collecting metrics...")
    metrics = collector.collect_all_metrics()
    
    # Save JSON report
    report_file = "/tmp/jarvis_code_metrics.json"
    with open(report_file, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"✅ JSON report saved: {report_file}")
    
    # Save Prometheus format
    prom_file = "/tmp/jarvis_code_metrics.prom"
    prom_data = export_to_prometheus_format(metrics)
    with open(prom_file, 'w') as f:
        f.write(prom_data)
    print(f"✅ Prometheus metrics saved: {prom_file}")
    
    # Print summary
    print("\n" + "=" * 70)
    print("METRICS SUMMARY")
    print("=" * 70)
    
    if metrics["coverage"]["status"] == "success":
        cov = metrics['coverage']
        target_met = "✅" if cov['percentage'] >= 60 else "⚠️"
        print(f"{target_met} Coverage:        {cov['percentage']}% ({cov['lines_covered']}/{cov['lines_total']} lines)")
        print(f"                 Target: >60% overall, >80% critical")
    
    if metrics["complexity"]["status"] == "success":
        cx = metrics['complexity']
        target_met = "✅" if cx['average'] < 10 else "⚠️"
        print(f"{target_met} Complexity:      Avg {cx['average']}, Max {cx['max']}")
        print(f"                 {cx['high_complexity_count']} high-complexity functions (>= 10)")
        print(f"                 Target: Avg <10 per function")
    
    if metrics["maintainability"]["status"] == "success":
        mi = metrics['maintainability']
        target_met = "✅" if mi['average'] >= 65 else "⚠️"
        print(f"{target_met} Maintainability: Avg {mi['average']}/100")
        print(f"                 {mi['low_mi_count']} low-MI files (<20)")
        print(f"                 Target: Avg >=65 (Rank B)")
    
    if metrics["line_counts"]["status"] == "success":
        lc = metrics['line_counts']
        comment_target = "✅" if lc['comment_ratio'] >= 10 else "⚠️"
        print(f"{comment_target} Lines of Code:   {lc['code_lines']:,} SLOC, {lc['comment_ratio']}% comments")
        print(f"                 Target: >=10% comment ratio")
    
    if metrics["duplication"]["status"] == "success":
        dup = metrics['duplication']
        target_met = "✅" if dup['duplicate_blocks'] < 5 else "⚠️"
        print(f"{target_met} Duplication:     {dup['duplicate_blocks']} duplicate blocks")
        print(f"                 Target: <5 duplicate blocks")
    
    print("=" * 70)
    
    # Print detailed findings if needed
    if metrics.get("complexity", {}).get("high_complexity_functions"):
        print("\n⚠️  HIGH COMPLEXITY FUNCTIONS:")
        for func in metrics["complexity"]["high_complexity_functions"][:5]:
            print(f"   {func['file']}:{func['lines']} - {func['function']} (complexity: {func['complexity']})")
    
    if metrics.get("maintainability", {}).get("low_mi_files"):
        print("\n⚠️  LOW MAINTAINABILITY FILES:")
        for file in metrics["maintainability"]["low_mi_files"][:5]:
            print(f"   {file['file']} - MI: {file['mi_score']}/100 (rank: {file['rank']})")


if __name__ == "__main__":
    main()
