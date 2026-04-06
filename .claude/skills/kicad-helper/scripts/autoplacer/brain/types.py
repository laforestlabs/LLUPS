"""Shared data structures for the autoplacer/autorouter system.

All types are plain Python dataclasses — no pcbnew imports.
These serve as the interchange format between Brain and Hardware layers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from math import hypot, atan2, pi
from typing import Optional


class Layer(IntEnum):
    FRONT = 0  # F.Cu
    BACK = 1   # B.Cu


@dataclass(slots=True)
class Point:
    x: float  # mm
    y: float  # mm

    def dist(self, other: Point) -> float:
        return hypot(self.x - other.x, self.y - other.y)

    def angle_to(self, other: Point) -> float:
        """Angle in radians from self to other."""
        return atan2(other.y - self.y, other.x - self.x)

    def __add__(self, other: Point) -> Point:
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point) -> Point:
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, s: float) -> Point:
        return Point(self.x * s, self.y * s)

    def __hash__(self):
        return hash((round(self.x, 4), round(self.y, 4)))


@dataclass(slots=True)
class Pad:
    ref: str        # component reference, e.g. "U2"
    pad_id: str     # pad number/name, e.g. "1"
    pos: Point      # absolute position in mm
    net: str        # net name
    layer: Layer


@dataclass
class Component:
    ref: str
    value: str
    pos: Point
    rotation: float       # degrees
    layer: Layer
    width_mm: float       # bounding box width
    height_mm: float      # bounding box height
    pads: list[Pad] = field(default_factory=list)
    locked: bool = False
    kind: str = ""        # "connector", "mounting_hole", "ic", "passive", "misc"

    @property
    def area(self) -> float:
        return self.width_mm * self.height_mm

    def bbox(self, clearance: float = 0.0) -> tuple[Point, Point]:
        """Return (top_left, bottom_right) with optional clearance margin."""
        hw = self.width_mm / 2 + clearance
        hh = self.height_mm / 2 + clearance
        return (
            Point(self.pos.x - hw, self.pos.y - hh),
            Point(self.pos.x + hw, self.pos.y + hh),
        )


@dataclass
class Net:
    name: str
    pad_refs: list[tuple[str, str]] = field(default_factory=list)  # [(ref, pad_id)]
    priority: int = 0          # higher = route first
    width_mm: float = 0.25     # trace width
    is_power: bool = False

    @property
    def component_refs(self) -> set[str]:
        return {ref for ref, _ in self.pad_refs}


@dataclass(slots=True)
class TraceSegment:
    start: Point
    end: Point
    layer: Layer
    net: str
    width_mm: float

    @property
    def length(self) -> float:
        return self.start.dist(self.end)


@dataclass(slots=True)
class Via:
    pos: Point
    net: str
    drill_mm: float = 0.3
    size_mm: float = 0.6


@dataclass
class BoardState:
    """Complete snapshot — the interchange format between Brain and Hardware."""
    components: dict[str, Component] = field(default_factory=dict)   # ref -> Component
    nets: dict[str, Net] = field(default_factory=dict)               # name -> Net
    traces: list[TraceSegment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    board_outline: tuple[Point, Point] = field(
        default_factory=lambda: (Point(0, 0), Point(90, 58))
    )

    @property
    def board_width(self) -> float:
        return self.board_outline[1].x - self.board_outline[0].x

    @property
    def board_height(self) -> float:
        return self.board_outline[1].y - self.board_outline[0].y

    @property
    def board_center(self) -> Point:
        tl, br = self.board_outline
        return Point((tl.x + br.x) / 2, (tl.y + br.y) / 2)


@dataclass(slots=True)
class GridCell:
    x: int    # column
    y: int    # row
    layer: Layer

    def __hash__(self):
        return hash((self.x, self.y, self.layer))

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y and self.layer == other.layer


@dataclass
class RoutingResult:
    segments: list[TraceSegment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    cost: float = 0.0
    success: bool = False


@dataclass
class PlacementScore:
    """Scores a placement configuration before routing.
    Higher is better for all fields (0-100 scale)."""
    total: float = 0.0
    net_distance: float = 0.0       # how close connected components are
    crossover_count: int = 0        # estimated ratsnest crossings
    crossover_score: float = 0.0    # 100 = zero crossings
    compactness: float = 0.0        # board utilization
    edge_compliance: float = 0.0    # connectors/holes on edges
    rotation_score: float = 0.0     # pad alignment quality
    board_containment: float = 0.0  # % of pads/bodies inside board outline

    def compute_total(self, weights: Optional[dict] = None) -> float:
        w = weights or {
            "net_distance": 0.25,
            "crossover_score": 0.25,
            "compactness": 0.05,
            "edge_compliance": 0.10,
            "rotation_score": 0.05,
            "board_containment": 0.30,
        }
        self.total = sum(
            getattr(self, k) * v for k, v in w.items()
        )
        return self.total


@dataclass
class ExperimentScore:
    """Unified score combining placement + routing quality.
    Single metric for the outer optimization loop. Higher = better."""
    placement: PlacementScore = field(default_factory=PlacementScore)
    routed_nets: int = 0
    total_nets: int = 0
    failed_nets: int = 0
    trace_count: int = 0
    via_count: int = 0
    total_trace_length_mm: float = 0.0
    total: float = 0.0

    def compute(self, weights: Optional[dict] = None) -> float:
        """Compute unified score. Routing completion dominates."""
        w = weights or {
            "placement": 0.20,       # placement quality (0-100)
            "route_completion": 0.50, # % nets routed (0-100)
            "trace_efficiency": 0.20, # shorter traces = better (0-100)
            "via_penalty": 0.10,      # fewer vias = better (0-100)
        }
        # Route completion: most important metric
        if self.total_nets > 0:
            route_pct = ((self.total_nets - self.failed_nets)
                         / self.total_nets) * 100
        else:
            route_pct = 100.0

        # Trace efficiency: normalize against board diagonal * net count
        # Lower total length is better; use a soft cap
        if self.total_trace_length_mm > 0 and self.total_nets > 0:
            avg_per_net = self.total_trace_length_mm / max(1, self.routed_nets)
            # ~50mm avg per net = score 50, lower = better
            trace_eff = max(0, min(100, 100 - avg_per_net))
        else:
            trace_eff = 50.0

        # Via penalty: fewer vias per routed net = better
        if self.routed_nets > 0:
            vias_per_net = self.via_count / self.routed_nets
            via_score = max(0, min(100, 100 - vias_per_net * 20))
        else:
            via_score = 50.0

        self.total = (
            w["placement"] * self.placement.total +
            w["route_completion"] * route_pct +
            w["trace_efficiency"] * trace_eff +
            w["via_penalty"] * via_score
        )
        return self.total

    def summary(self) -> str:
        return (f"score={self.total:.1f} "
                f"routed={self.routed_nets}/{self.total_nets} "
                f"failed={self.failed_nets} "
                f"traces={self.trace_count} vias={self.via_count} "
                f"length={self.total_trace_length_mm:.0f}mm "
                f"placement={self.placement.total:.1f}")
