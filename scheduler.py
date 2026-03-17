import schedule
import time
import logging
from main import daily_setup_and_execution, settlement_job

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def start_scheduler():
    """
    Long-running loop for local / self-hosted deployments.
    When deployed via skill.json the platform handles scheduling directly,
    calling daily_setup_and_execution and settlement_job at the cron times
    specified in skill.json — so this loop is NOT needed in that case.
    """
    logger.info("Starting NBA Alpha Agent local scheduler...")

    # schedule uses local time; ensure server runs on US Eastern time or adjust accordingly
    schedule.every().day.at("10:00").do(daily_setup_and_execution)
    schedule.every().day.at("02:00").do(settlement_job)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    start_scheduler()
