import logging

from uar import create_app

logging.basicConfig(level=logging.INFO)
app = create_app()
