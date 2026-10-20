"""
Report service. Owns no table of its own - see app/service.py.
"""
import datetime as dt
import logging

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from common.config import get_settings
from common.errors import register_error_handlers

from app.service import ReportService

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Report Service", version="0.1.0")
register_error_handlers(app)


@app.get("/health")
def health():
    return {"status": "ok", "service": "report-service"}


@app.get("/reports/daily")
def daily_report_json(report_date: dt.date):
    report = ReportService().daily_report(report_date)
    return report.__dict__


@app.get("/reports/daily/text", response_class=PlainTextResponse)
def daily_report_text(report_date: dt.date):
    report = ReportService().daily_report(report_date)
    return report.as_text()
