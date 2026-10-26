"""
Location schemas — GPS coordinate collection and heatmap data.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.common import EMeshBaseModel


class LocationUpdate(EMeshBaseModel):
    """Payload sent by clients to update their GPS position."""
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy: Optional[float] = Field(None, ge=0.0, description="Accuracy radius in metres")
    client_id: Optional[str] = None


class LocationRead(EMeshBaseModel):
    """Location record with embedded user info (admin use)."""
    id: str
    user_id: str
    username: str
    full_name: str
    role: str
    latitude: float
    longitude: float
    accuracy: Optional[float] = None
    client_id: Optional[str] = None
    updated_at: datetime



class HeatmapPoint(EMeshBaseModel):
    """Single weighted point for heatmap rendering."""
    lat: float
    lng: float
    weight: float = 1.0
    user_id: str
    username: str
    role: str
    updated_at: str


class HeatmapResponse(EMeshBaseModel):
    """Response for admin heatmap endpoint."""
    points: List[HeatmapPoint]
    total_active: int
    bounds: Optional[dict] = None  # {min_lat, max_lat, min_lng, max_lng}
    generated_at: str
