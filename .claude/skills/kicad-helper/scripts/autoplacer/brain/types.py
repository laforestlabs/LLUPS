"""Shared data structures for the autoplacer system.

All types are plain Python dataclasses — no pcbnew imports.
These serve as the interchange format between Brain and Hardware layers.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from math import hypot, atan2, pi
from typing import Optional, NamedTuple


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
    is_through_hole: bool = False  # True if footprint has PTH pads
    body_center: Point | None = None  # courtyard/body bbox center (absolute coords)

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
    width_mm: float = 0.127    # trace width
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


@dataclass
class PlacementIterationSnapshot:
    """Snapshot of placement state at one iteration."""
    iteration: int = 0
    score: float = 0.0
    max_displacement: float = 0.0
    stagnant_count: int = 0
    overlap_count: int = 0

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "score": round(self.score, 2),
            "max_displacement": round(self.max_displacement, 2),
            "stagnant": self.stagnant_count,
            "overlaps": self.overlap_count,
        }


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
    courtyard_overlap: float = 0.0  # 100 = no overlaps

    def compute_total(self, weights: Optional[dict] = None) -> float:
        w = weights or {
            "net_distance": 0.25,        # connected parts close together
            "crossover_score": 0.20,     # fewer crossings = easier routing
            "compactness": 0.12,         # tighter layouts = smaller boards
            "edge_compliance": 0.10,
            "rotation_score": 0.03,
            "board_containment": 0.15,
            "courtyard_overlap": 0.15,
        }
        self.total = sum(
            getattr(self, k) * v for k, v in w.items()
        )
        return self.total


@dataclass
class DRCScore:
    """DRC violation penalties. Higher = fewer violations. 0-100 scale."""
    total: float = 100.0
    shorts: float = 100.0
    unconnected: float = 100.0
    clearance: float = 100.0
    courtyard: float = 100.0

    @staticmethod
    def from_counts(drc_dict: dict) -> 'DRCScore':
        """Convert quick_drc() output dict to DRCScore on 0-100 scale."""
        import math

        def _violation_score(count: int, weight: float) -> float:
            if count == 0:
                return weight
            return max(0.0, weight * (1 - math.log10(1 + count) / math.log10(100)))

        s = DRCScore()
        s.shorts = _violation_score(drc_dict.get("shorts", 0), 40)
        s.unconnected = _violation_score(drc_dict.get("unconnected", 0), 30)
        s.clearance = _violation_score(drc_dict.get("clearance", 0), 20)
        s.courtyard = _violation_score(drc_dict.get("courtyard", 0), 10)
        s.total = s.shorts + s.unconnected + s.clearance + s.courtyard
        return s


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
    # Phase timing (ms)
    placement_ms: float = 0.0
    routing_ms: float = 0.0
    failed_net_names: list[str] = field(default_factory=list)
    drc_score: DRCScore = field(default_factory=DRCScore)
    pipeline_drc: dict = field(default_factory=dict)
    skipped_routing: bool = False

    def compute(self, weights: Optional[dict] = None,
                drc_dict: Optional[dict] = None,
                board_area_mm2: Optional[float] = None) -> float:
        """Compute unified score. Route completion dominates, then placement + DRC.
        
        If board_area_mm2 is provided (from board size search), an area bonus
        rewards smaller boards.
        """
        w = weights or {}
        w_placement = w.get("placement", 0.15)
        w_route = w.get("route_completion", 0.50)
        w_via = w.get("via_penalty", 0.10)
        w_contain = w.get("containment", 0.05)
        w_drc = w.get("drc", 0.20)

        # Route completion: most important — must get all nets routed
        if self.total_nets > 0:
            route_pct = ((self.total_nets - self.failed_nets)
                         / self.total_nets) * 100
        else:
            # No nets counted = routing was skipped or failed. Score 0, not 100.
            route_pct = 0.0

        # Via penalty: fewer vias per routed net = better
        if self.routed_nets > 0:
            vias_per_net = self.via_count / self.routed_nets
            via_score = max(0, min(100, 100 - vias_per_net * 20))
        elif self.skipped_routing:
            via_score = 0.0  # No routing = no via credit
        else:
            via_score = 50.0

        # DRC score — no credit when routing was skipped
        if drc_dict:
            self.drc_score = DRCScore.from_counts(drc_dict)
        if self.skipped_routing:
            drc_val = 0.0
        else:
            drc_val = self.drc_score.total

        self.total = (
            w_placement * self.placement.total +
            w_route * route_pct +
            w_via * via_score +
            w_contain * self.placement.board_containment +
            w_drc * drc_val
        )

        # Hard score gates: cap score based on route completion
        if route_pct <= 50.0:
            self.total = min(self.total, 40.0)
        elif route_pct < 90.0:
            self.total = min(self.total, 70.0)

        # Area bonus: reward smaller boards (only when board size search is active)
        if board_area_mm2 is not None:
            import math as _math
            # Nonlinear area scoring: exponential decay rewards being closer
            # to the minimum viable area.  A board at min_area scores ~85,
            # at 2x min_area scores ~35, at max_area scores ~10.
            max_area = 120.0 * 80.0  # generous upper bound
            # Use a reference area proportional to a reasonable min (40% of max)
            ref_area = max_area * 0.4
            area_score = max(0.0, min(100.0,
                100.0 * _math.exp(-board_area_mm2 / (1.8 * ref_area))))
            w_area = w.get("area", 0.15)
            # Scale other weights down proportionally
            scale = 1.0 - w_area
            self.total = self.total * scale + w_area * area_score

        return self.total

    def summary(self) -> str:
        return (f"score={self.total:.1f} "
                f"routed={self.routed_nets}/{self.total_nets} "
                f"failed={self.failed_nets} "
                f"traces={self.trace_count} vias={self.via_count} "
                f"length={self.total_trace_length_mm:.0f}mm "
                f"placement={self.placement.total:.1f}")
