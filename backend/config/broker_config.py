"""
Phase 27 — Live Broker Configuration & Resilience Settings

Safe configuration reader with bounds validation and fail-closed defaults.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Default resilience constants
DEFAULT_LIVE_RETRY_MAX = 3
DEFAULT_LIVE_RETRY_BACKOFF = 5.0  # seconds
DEFAULT_RECONCILIATION_INTERVAL = 60  # seconds
DEFAULT_ACCOUNT_SYNC_INTERVAL = 60  # seconds


def get_live_retry_max() -> int:
    """Retrieve validated maximum retry attempts for transient broker errors."""
    val_str = os.getenv("LIVE_RETRY_MAX", str(DEFAULT_LIVE_RETRY_MAX))
    try:
        val = int(val_str)
        if 0 <= val <= 10:
            return val
        logger.warning(f"Invalid LIVE_RETRY_MAX ({val}); using safe default {DEFAULT_LIVE_RETRY_MAX}")
        return DEFAULT_LIVE_RETRY_MAX
    except (ValueError, TypeError):
        return DEFAULT_LIVE_RETRY_MAX


def get_live_retry_backoff() -> float:
    """Retrieve validated backoff delay (seconds) between retry attempts."""
    val_str = os.getenv("LIVE_RETRY_BACKOFF", str(DEFAULT_LIVE_RETRY_BACKOFF))
    try:
        val = float(val_str)
        if 0.0 <= val <= 60.0:
            return val
        logger.warning(f"Invalid LIVE_RETRY_BACKOFF ({val}); using safe default {DEFAULT_LIVE_RETRY_BACKOFF}")
        return DEFAULT_LIVE_RETRY_BACKOFF
    except (ValueError, TypeError):
        return DEFAULT_LIVE_RETRY_BACKOFF


def get_reconciliation_interval() -> int:
    """Retrieve validated interval (seconds) for broker state reconciliation."""
    val_str = os.getenv("RECONCILIATION_INTERVAL", str(DEFAULT_RECONCILIATION_INTERVAL))
    try:
        val = int(val_str)
        if 1 <= val <= 3600:
            return val
        logger.warning(f"Invalid RECONCILIATION_INTERVAL ({val}); using safe default {DEFAULT_RECONCILIATION_INTERVAL}")
        return DEFAULT_RECONCILIATION_INTERVAL
    except (ValueError, TypeError):
        return DEFAULT_RECONCILIATION_INTERVAL


def get_account_sync_interval() -> int:
    """Retrieve validated interval (seconds) for background account state synchronization."""
    val_str = os.getenv("ACCOUNT_SYNC_INTERVAL", str(DEFAULT_ACCOUNT_SYNC_INTERVAL))
    try:
        val = int(val_str)
        if 1 <= val <= 3600:
            return val
        logger.warning(f"Invalid ACCOUNT_SYNC_INTERVAL ({val}); using safe default {DEFAULT_ACCOUNT_SYNC_INTERVAL}")
        return DEFAULT_ACCOUNT_SYNC_INTERVAL
    except (ValueError, TypeError):
        return DEFAULT_ACCOUNT_SYNC_INTERVAL
