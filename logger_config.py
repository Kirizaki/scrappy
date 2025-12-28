import logging
import sys

def setup_logging(level=logging.INFO):
    """
    Sets up the logging configuration for the application.
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
