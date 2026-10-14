"""Processes, Tailscale and pending updates (cached by the collector)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_collector

router = APIRouter(prefix="/api")


def _need(collector):
    if collector is None:
        raise HTTPException(status_code=503, detail="Collector is disabled.")
    return collector


@router.get("/processes/top")
def top_processes(limit: int = Query(15, ge=1, le=50), collector=Depends(get_collector)):
    return {"apps": _need(collector).processes[:limit]}


@router.get("/tailscale")
def tailscale(collector=Depends(get_collector)):
    data = _need(collector).tailscale
    if data is None:
        raise HTTPException(status_code=503, detail="Tailscale status not checked yet.")
    return data


@router.get("/updates")
def updates(collector=Depends(get_collector)):
    data = _need(collector).updates
    if data is None:
        raise HTTPException(status_code=503, detail="Update check is still running (can take a minute).")
    return data
