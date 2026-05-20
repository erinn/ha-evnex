"""Typed coordinator payload for the Evnex integration."""

from __future__ import annotations

from pydantic import BaseModel, Field

from evnex.schema.charge_points import (
    EvnexChargePoint,
    EvnexChargePointOverrideConfig,
)
from evnex.schema.org import EvnexOrgBrief, EvnexOrgInsightEntry
from evnex.schema.user import EvnexUserDetail
from evnex.schema.v3.charge_points import (
    EvnexChargePointConnector,
    EvnexChargePointDetail,
    EvnexChargePointSession,
)


class EvnexCoordinatorData(BaseModel):
    """Snapshot of Evnex API state published by the DataUpdateCoordinator."""

    user: EvnexUserDetail | None = None
    # by org_id
    org_briefs: dict[str, EvnexOrgBrief] = Field(default_factory=dict)
    # by org_id
    org_insights: dict[str, list[EvnexOrgInsightEntry]] = Field(default_factory=dict)
    # by org_id -> list of CPs
    charge_points_by_org: dict[str, list[EvnexChargePoint]] = Field(
        default_factory=dict
    )
    # by cp_id
    charge_point_brief: dict[str, EvnexChargePoint] = Field(default_factory=dict)
    # by cp_id
    charge_point_details: dict[str, EvnexChargePointDetail] = Field(
        default_factory=dict
    )
    # by cp_id
    charge_point_override: dict[str, EvnexChargePointOverrideConfig] = Field(
        default_factory=dict
    )
    # by cp_id
    charge_point_sessions: dict[str, list[EvnexChargePointSession]] = Field(
        default_factory=dict
    )
    # by (cp_id, connectorId)
    connector_brief: dict[tuple[str, str], EvnexChargePointConnector] = Field(
        default_factory=dict
    )
    # by cp_id -> org_id
    charge_point_to_org_map: dict[str, str] = Field(default_factory=dict)
