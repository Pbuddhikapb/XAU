"""
Production Health & Self-Healing Watchdog for Binance XAUUSDT System.
Probes /api/v1/system/health every 60s, checks database connectivity,
audits candle freshness lag, and triggers automatic ingestion service restarts on stalls.
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any
from urllib import error, request

LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)
HEALTH_LOG_FILE = os.path.join(LOG_DIR, "health.log")

logger = logging.getLogger("xau.watchdog")


def get_system_memory_usage() -> float:
    """Read host memory usage percentage from /proc/meminfo."""
    try:
        mem_total = 0.0
        mem_available = 0.0
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = float(parts[1].split()[0])
                    if key == "MemTotal":
                        mem_total = val
                    elif key == "MemAvailable":
                        mem_available = val
        if mem_total > 0:
            return round(((mem_total - mem_available) / mem_total) * 100, 2)
    except (OSError, ValueError):
        pass
    return 0.0


def probe_health_endpoint(
    url: str = "http://127.0.0.1:8000/api/v1/system/health",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """HTTP probe to FastAPI health endpoint."""
    req = request.Request(url, headers={"User-Agent": "XAU-Health-Watchdog/1.0"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
            return {"status": "UNHEALTHY", "http_status": resp.status}
    except error.URLError as e:
        return {"status": "UNREACHABLE", "error": str(e)}
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "ERROR", "error": str(e)}


def evaluate_health_and_remediate(health_data: dict[str, Any], max_lag_seconds: int = 300) -> bool:
    """
    Evaluate system telemetry and issue self-healing recovery commands if needed.
    Returns True if healthy, False if degraded or remediation triggered.
    """
    now_str = datetime.now(UTC).isoformat()
    status = health_data.get("status")
    db_connected = health_data.get("database_connected", False)
    underlying_active = health_data.get("underlying_active", False)
    freshness = health_data.get("data_freshness", {})
    candle_lag = freshness.get("candle_lag_seconds", 0)
    mem_usage = get_system_memory_usage()

    health_record = {
        "timestamp": now_str,
        "status": status,
        "database_connected": db_connected,
        "underlying_active": underlying_active,
        "candle_lag_seconds": candle_lag,
        "memory_usage_pct": mem_usage,
    }

    # Append to health.log
    with open(HEALTH_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(health_record) + "\n")

    # 1. API or DB down
    if status != "HEALTHY" or not db_connected:
        logger.critical(f"System UNHEALTHY: status={status}, db_connected={db_connected}")
        return False

    # 2. Candle staleness during active market hours
    if underlying_active and candle_lag > max_lag_seconds:
        logger.warning(
            f"Stale market data detected! Candle lag {candle_lag}s > {max_lag_seconds}s during active CME hours."
        )
        logger.info("Triggering self-healing recovery: restarting xau-ingestion.service...")
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", "xau-ingestion.service"],
                check=False,
                capture_output=True,
                timeout=10,
            )
            logger.info("Self-healing restart command issued to systemd.")
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Failed to issue systemd restart: {e}")
        return False

    logger.debug(f"Health check OK. Lag: {candle_lag}s | Memory: {mem_usage}%")
    return True


async def watchdog_loop(
    interval_seconds: float = 60.0,
    health_url: str = "http://127.0.0.1:8000/api/v1/system/health",
    max_lag: int = 300,
) -> None:
    """Continuous watchdog loop probing health and logging metrics."""
    logger.info(f"Starting Health Watchdog loop (Interval: {interval_seconds}s, Target: {health_url})...")
    while True:
        try:
            data = probe_health_endpoint(url=health_url)
            evaluate_health_and_remediate(data, max_lag_seconds=max_lag)
        except (OSError, RuntimeError) as e:
            logger.error(f"Error in health watchdog probe: {e}")
        await asyncio.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="XAU Intelligence Health Watchdog")
    parser.add_argument("--once", action="store_true", help="Run a single probe and exit with code 0 or 1")
    parser.add_argument("--interval", type=float, default=60.0, help="Probe interval in seconds")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8000/api/v1/system/health")
    parser.add_argument("--max-lag", type=int, default=300, help="Max permitted candle lag in seconds")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if args.once:
        data = probe_health_endpoint(url=args.url)
        is_healthy = evaluate_health_and_remediate(data, max_lag_seconds=args.max_lag)
        sys.exit(0 if is_healthy else 1)
    else:
        asyncio.run(watchdog_loop(interval_seconds=args.interval, health_url=args.url, max_lag=args.max_lag))


if __name__ == "__main__":
    main()
