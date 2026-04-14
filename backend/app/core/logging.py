"""Logging configuration"""
import logging
import os
from datetime import datetime

def setup_logging(run_id: str) -> None:
    """Setup logging with run_id context"""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    logging.basicConfig(
        level=getattr(logging, level),
        format=f"%(asctime)s | {run_id} | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
