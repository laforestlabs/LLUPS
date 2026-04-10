"""Shared data structures for the autoplacer/autorouter system.

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


@dataclass(slots=True)
class GridCell:
    x: int    # column
    y: int    # row
    layer: Layer

    def __hash__(self):
        return hash((self.x, self.y, self.layer))

    def __eq__(self, other):
        return self.x == other.x and self.y == other.y and self.layer == other.layer


class PathResult(NamedTuple):
    """Result from A* find_path — path cells + search metrics."""
    path: list[GridCell] | None
    expansions: int = 0
    cost: float = 0.0


@dataclass
class RoutingResult:
    segments: list[TraceSegment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    cost: float = 0.0
    success: bool = False


@dataclass
class NetRoutingResult:
    """Per-net routing metrics for observability."""
    net_name: str = ""
    success: bool = False
    segment_count: int = 0
    via_count: int = 0
    total_length_mm: float = 0.0
    a_star_expansions: int = 0
    time_ms: float = 0.0
    width_used_mm: float = 0.0
    width_relaxed: bool = False
    mst_retries: int = 0
    front_length_mm: float = 0.0
    back_length_mm: float = 0.0
    failure_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "net": self.net_name,
            "success": self.success,
            "segments": self.segment_count,
            "vias": self.via_count,
            "length_mm": round(self.total_length_mm, 2),
            "a_star_expansions": self.a_star_expansions,
            "time_ms": round(self.time_ms, 1),
            "width_mm": round(self.width_used_mm, 3),
            "width_relaxed": self.width_relaxed,
            "mst_retries": self.mst_retries,
            "front_mm": round(self.front_length_mm, 2),
            "back_mm": round(self.back_length_mm, 2),
            "failure_reason": self.failure_reason,
        }


@dataclass
class RRRIteration:
    """One iteration of the rip-up and re-route loop."""
    iteration: int = 0
    target_net: str = ""
    success: bool = False
    victims_ripped: list[str] = field(default_factory=list)
    queue_size: int = 0
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "target": self.target_net,
            "success": self.success,
            "victims": self.victims_ripped,
            "queue": self.queue_size,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


@dataclass
class RRRSummary:
    """Summary of a full RRR run for observability."""
    iterations_used: int = 0
    nets_recovered: int = 0
    nets_still_failed: int = 0
    total_rips: int = 0
    timed_out: bool = False
    stagnated: bool = False
    elapsed_ms: float = 0.0
    iteration_log: list[RRRIteration] = field(default_factory=list)
    rip_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "iterations_used": self.iterations_used,
            "nets_recovered": self.nets_recovered,
            "nets_still_failed": self.nets_still_failed,
            "total_rips": self.total_rips,
            "timed_out": self.timed_out,
            "stagnated": self.stagnated,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "iterations": [it.to_dict() for it in self.iteration_log],
            "rip_counts": dict(self.rip_counts),
        }


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
            "crossover_score": 0.30,     # fewer crossings = easier routing
            "compactness": 0.02,
            "edge_compliance": 0.05,
            "rotation_score": 0.03,
            "board_containment": 0.20,
            "courtyard_overlap": 0.15,
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
    # Phase timing (ms)
    placement_ms: float = 0.0
    routing_ms: float = 0.0
    rrr_ms: float = 0.0
    # Detailed results (not serialized in summary)
    per_net_results: list[NetRoutingResult] = field(default_factory=list)
    rrr_summary: RRRSummary | None = None
    failed_net_names: list[str] = field(default_factory=list)
    total_a_star_expansions: int = 0

    def compute(self, weights: Optional[dict] = None) -> float:
        """Compute unified score. Route completion dominates, then placement."""
        w = weights or {}
        w_placement = w.get("placement", 0.15)
        w_route = w.get("route_completion", 0.65)
        w_via = w.get("via_penalty", 0.10)
        w_contain = w.get("containment", 0.10)

        # Route completion: most important — must get all nets routed
        if self.total_nets > 0:
            route_pct = ((self.total_nets - self.failed_nets)
                         / self.total_nets) * 100
        else:
            route_pct = 100.0

        # Via penalty: fewer vias per routed net = better
        if self.routed_nets > 0:
            vias_per_net = self.via_count / self.routed_nets
            via_score = max(0, min(100, 100 - vias_per_net * 20))
        else:
            via_score = 50.0

        self.total = (
            w_placement * self.placement.total +
            w_route * route_pct +
            w_via * via_score +
            w_contain * self.placement.board_containment
        )
        return self.total

    def summary(self) -> str:
        return (f"score={self.total:.1f} "
                f"routed={self.routed_nets}/{self.total_nets} "
                f"failed={self.failed_nets} "
                f"traces={self.trace_count} vias={self.via_count} "
                f"length={self.total_trace_length_mm:.0f}mm "
                f"placement={self.placement.total:.1f}")
