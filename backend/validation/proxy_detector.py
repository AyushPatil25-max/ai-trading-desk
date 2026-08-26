"""
Proxy Pattern & Parametric Approximation Detector — Phase 5.5

Scans python modules and backtest engines to detect hardcoded performance multipliers,
proportional baseline proxies, and synthetic metric transformations.
"""

import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ProxyDetectionFinding(BaseModel):
    file_path: str
    line_number: int
    matched_pattern: str
    line_content: str
    severity: str  # "HIGH", "MEDIUM", "LOW"
    description: str


class ProxyAuditResult(BaseModel):
    proxies_detected: bool
    findings_count: int
    findings: List[ProxyDetectionFinding] = Field(default_factory=list)
    scanned_files_count: int = 0
    clean_files_count: int = 0
    audit_summary: str


class ProxyDetector:
    """
    Code scanner that inspects validation and simulation modules for hardcoded formulas.
    """

    SUSPICIOUS_PATTERNS = [
        (r"bench_ret\s*\*\s*\d+(\.\d+)?", "Proportional benchmark return multiplier"),
        (r"benchmark_return\s*\*\s*\d+(\.\d+)?", "Proportional benchmark return multiplier"),
        (r"strategy_metrics\.total_return_pct\s*\*\s*\d+(\.\d+)?", "Proportional strategy return multiplier"),
        (r"strategy_metrics\.sharpe_ratio\s*\*\s*\d+(\.\d+)?", "Proportional strategy Sharpe multiplier"),
        (r"strategy_metrics\.max_drawdown_pct\s*\*\s*\d+(\.\d+)?", "Proportional strategy drawdown multiplier"),
        (r"strategy_metrics\.win_rate\s*\*\s*\d+(\.\d+)?", "Proportional strategy win rate multiplier"),
        (r"full_metrics\.total_return_pct\s*\*\s*\d+(\.\d+)?", "Proportional full metrics ablation multiplier"),
        (r"full_metrics\.sharpe_ratio\s*\*\s*\d+(\.\d+)?", "Proportional full metrics Sharpe multiplier"),
        (r"full_metrics\.max_drawdown_pct\s*\*\s*\d+(\.\d+)?", "Proportional full metrics drawdown multiplier"),
    ]

    @classmethod
    def scan_file(cls, file_path: str) -> List[ProxyDetectionFinding]:
        findings: List[ProxyDetectionFinding] = []
        if not os.path.exists(file_path):
            return findings

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, 1):
                # Ignore comments or docstrings
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue

                for pat, desc in cls.SUSPICIOUS_PATTERNS:
                    if re.search(pat, line):
                        findings.append(
                            ProxyDetectionFinding(
                                file_path=file_path,
                                line_number=idx,
                                matched_pattern=pat,
                                line_content=stripped,
                                severity="HIGH",
                                description=desc,
                            )
                        )
        return findings

    @classmethod
    def scan_directory(cls, directory_path: str) -> ProxyAuditResult:
        all_findings: List[ProxyDetectionFinding] = []
        scanned_count = 0
        clean_count = 0

        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    scanned_count += 1
                    file_findings = cls.scan_file(full_path)
                    if file_findings:
                        all_findings.extend(file_findings)
                    else:
                        clean_count += 1

        detected = len(all_findings) > 0
        summary = (
            f"Proxy scan found {len(all_findings)} suspicious patterns across {scanned_count} files."
            if detected
            else f"Proxy scan clean. All {scanned_count} files use independent calculation paths."
        )

        return ProxyAuditResult(
            proxies_detected=detected,
            findings_count=len(all_findings),
            findings=all_findings,
            scanned_files_count=scanned_count,
            clean_files_count=clean_count,
            audit_summary=summary,
        )
