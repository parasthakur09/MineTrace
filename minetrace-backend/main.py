"""MineTrace API. Serves only cached local data; it never calls the internet.

Run:  uvicorn main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import narrative
import report
import service
from config import CORS_ORIGINS
from db import init_db

@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="MineTrace API",
    description="Explainable risk screening for critical-mineral trade routes.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _not_found(error):
    raise HTTPException(status_code=404, detail=str(error))


@app.get("/")
def root():
    return {"project": "MineTrace", "status": "online", "docs": "/docs"}


@app.get("/health")
def health():
    return service.health()


@app.get("/minerals")
def minerals():
    return {"minerals": service.list_minerals()}


@app.get("/rules")
def rules():
    return service.rules()


@app.get("/routes")
def routes(mineral: str = Query("cobalt"), year: int | None = Query(None)):
    try:
        return service.list_routes(mineral, year)
    except service.NotFound as error:
        _not_found(error)


@app.get("/route")
def route(mineral: str, year: int, exporter: str, importer: str):
    try:
        return service.route_detail(mineral, year, exporter.upper(), importer.upper())
    except service.NotFound as error:
        _not_found(error)


@app.get("/route/explanation")
def route_explanation(mineral: str, year: int, exporter: str, importer: str, llm: bool = True):
    try:
        detail = service.route_detail(mineral, year, exporter.upper(), importer.upper())
    except service.NotFound as error:
        _not_found(error)
    return narrative.explain(detail, use_llm=llm)


@app.get("/route/report", response_class=HTMLResponse)
def route_report(mineral: str, year: int, exporter: str, importer: str, llm: bool = True):
    try:
        detail = service.route_detail(mineral, year, exporter.upper(), importer.upper())
    except service.NotFound as error:
        _not_found(error)
    return HTMLResponse(report.build_report(detail, narrative.explain(detail, use_llm=llm)))
