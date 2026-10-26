"""
Common shared schemas — pagination, error responses, timestamps.
"""
from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict

DataT = TypeVar("DataT")


class EMeshBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SuccessResponse(EMeshBaseModel):
    success: bool = True
    message: str = "OK"
    data: Optional[Any] = None


class ErrorResponse(EMeshBaseModel):
    success: bool = False
    message: str
    detail: Optional[Any] = None


class PaginatedResponse(EMeshBaseModel, Generic[DataT]):
    success: bool = True
    data: List[DataT]
    total: int
    page: int
    page_size: int
    total_pages: int
