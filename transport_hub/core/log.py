"""سجلات المنصة: مستوى من متغير البيئة TRANSPORT_HUB_LOG (الافتراضي INFO)، وملف اختياري TRANSPORT_HUB_LOG_FILE."""

import logging
import os

_CONFIGURED = False


def get_logger(name="transport_hub"):
    global _CONFIGURED
    if not _CONFIGURED:
        level = getattr(logging, os.environ.get("TRANSPORT_HUB_LOG", "INFO").upper(), logging.INFO)
        handlers = [logging.StreamHandler()]
        if os.environ.get("TRANSPORT_HUB_LOG_FILE"):
            handlers.append(logging.FileHandler(os.environ["TRANSPORT_HUB_LOG_FILE"], encoding="utf-8"))
        logging.basicConfig(level=level, handlers=handlers, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        _CONFIGURED = True
    return logging.getLogger(name if name.startswith("transport_hub") else f"transport_hub.{name}")
