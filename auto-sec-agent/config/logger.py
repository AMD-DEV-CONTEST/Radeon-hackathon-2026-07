"""
AutoSec Agent — Logging System
"""
import logging
import sys
from pathlib import Path
from datetime import datetime

class AutoSecLogger:
    """Centralized logging for AutoSec Agent"""
    
    def __init__(self, log_dir=None, level=logging.INFO):
        self.log_dir = Path(log_dir) if log_dir else Path(__file__).parent / "logs"
        self.log_dir.mkdir(exist_ok=True, parents=True)
        
        self.logger = logging.getLogger("AutoSec")
        self.logger.setLevel(level)
        
        # File handler
        log_file = self.log_dir / f"autosec_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        fh = logging.FileHandler(log_file)
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        self.logger.addHandler(fh)
        
        # Console handler  
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        self.logger.addHandler(ch)
        
        self.log_file = log_file
    
    def info(self, msg): self.logger.info(msg)
    def warn(self, msg): self.logger.warning(msg)
    def error(self, msg): self.logger.error(msg)
    def debug(self, msg): self.logger.debug(msg)
    
    def get_recent_logs(self, n=50):
        if self.log_file.exists():
            with open(self.log_file) as f:
                lines = f.readlines()
            return "".join(lines[-n:])
        return "No logs yet"
