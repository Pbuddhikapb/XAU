"""
Master execution script for full historical ingestion and data quality auditing.
Ingests:
1. Full 1m history (S3 monthly archives + REST for 2026-10-28 gap + November daily/REST)
2. Complete funding history (inception to current)
3. Full mark and index klines with basis computation
4. Executes comprehensive quality audit (duplicates, OHLC validity, gaps, MTF reconciliation)
"""

import json
import logging
import sys
import time

from backend.data.historical_downloader import HistoricalDownloader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ingestion_runner")


def main() -> None:
    downloader = HistoricalDownloader()

    logger.info("==================================================")
    logger.info("PHASE 1: Ingesting Full 1m Historical OHLCV...")
    logger.info("==================================================")
    t0 = time.time()
    hist_res = downloader.ingest_full_1m_history()
    t1 = time.time()
    logger.info("1m Ingestion completed in %.2fs: %s", t1 - t0, hist_res)

    logger.info("==================================================")
    logger.info("PHASE 2: Ingesting Complete Funding History...")
    logger.info("==================================================")
    t2 = time.time()
    funding_cnt = downloader.ingest_full_funding_history()
    t3 = time.time()
    logger.info("Funding Ingestion completed in %.2fs: %d records", t3 - t2, funding_cnt)

    logger.info("==================================================")
    logger.info("PHASE 3: Ingesting Mark & Index Price Series...")
    logger.info("==================================================")
    t4 = time.time()
    mark_res = downloader.ingest_full_mark_index_history()
    t5 = time.time()
    logger.info("Mark/Index Ingestion completed in %.2fs: %s", t5 - t4, mark_res)

    logger.info("==================================================")
    logger.info("PHASE 4: Running Comprehensive Data Quality Audit...")
    logger.info("==================================================")
    t6 = time.time()
    audit_res = downloader.run_data_quality_audit()
    t7 = time.time()
    logger.info("Quality Audit completed in %.2fs", t7 - t6)

    # Save structured audit results
    audit_file = "config/data_quality_audit_results.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(audit_res, f, indent=2, default=str)
    logger.info("Audit results saved to %s", audit_file)

    logger.info("==================================================")
    logger.info("SUMMARY RESULTS:")
    logger.info("Total 1m candles: %s", audit_res.get("total_1m_candles"))
    logger.info("Duplicate candles: %s", audit_res.get("duplicate_count"))
    logger.info("Invalid OHLC rows: %s", audit_res.get("invalid_ohlc_count"))
    logger.info("Funding records: %s", audit_res.get("funding_history_count"))
    logger.info("Mark/Index records: %s", audit_res.get("mark_index_prices_count"))
    logger.info("Timestamp range: %s to %s", audit_res.get("min_open_time"), audit_res.get("max_open_time"))
    logger.info(
        "Total gaps found: %s (Unresolved: %s)",
        audit_res.get("total_gaps_found"),
        audit_res.get("unresolved_gaps_count"),
    )
    logger.info("==================================================")


if __name__ == "__main__":
    main()
