"""PlacementSolver — edge-first pinning, clustering, force-directed placement
with integrated scoring to minimize routing difficulty.

Pure Python. All iteration runs locally — no LLM calls in the loop.
"""
from __future__ import annotations
import copy
import math
import random
from collections import defaultdict

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from .types import (
    Point, Component, Net, BoardState, Layer, Pad, PlacementScore
)
from .graph import (
    build_connectivity_graph, find_communities, minimum_spanning_tree,
    count_crossings, total_ratsnest_length, AdjacencyGraph
)


def _bbox_overlap(a: Component, b: Component, clearance: float = 0.5) -> bool:
    """Check if two component bounding boxes overlap with clearance."""
    a_tl, a_br = a.bbox(clearance / 2)
    b_tl, b_br = b.bbox(clearance / 2)
    return (a_tl.x < b_br.x and a_br.x > b_tl.x and
            a_tl.y < b_br.y and a_br.y > b_tl.y)


def _bbox_overlap_amount(a: Component, b: Component) -> float:
    """Return overlap area (0 if no overlap)."""
    a_tl, a_br = a.bbox()
    b_tl, b_br = b.bbox()
    ox = max(0, min(a_br.x, b_br.x) - max(a_tl.x, b_tl.x))
    oy = max(0, min(a_br.y, b_br.y) - max(a_tl.y, b_tl.y))
    return ox * oy


def _swap_pad_positions(a: Component, b: Component):
    """After swapping a.pos and b.pos, update pad positions accordingly."""
    # Pads are at absolute positions. After swap, shift by the delta.
    dx_a = a.pos.x - b.pos.x  # a moved from b's old pos to a's new pos...
    # Actually: a now has b's old position, b now has a's old position.
    # But we already swapped .pos. So shift pads by the same delta.
    # a's pads need to move by (a.pos - old_a_pos) = (b_old - a_old)
    # But .pos was already swapped so a.pos = b_old, b.pos = a_old
    # So a's old pos was b.pos (current), a's new pos is a.pos (current)
    delta_ax = a.pos.x - b.pos.x
    delta_ay = a.pos.y - b.pos.y
    for p in a.pads:
        p.pos = Point(p.pos.x + delta_ax, p.pos.y + delta_ay)
    for p in b.pads:
        p.pos = Point(p.pos.x - delta_ax, p.pos.y - delta_ay)


def _update_pad_positions(comp: Component, old_pos: Point, old_rot: float):
    """Update pad absolute positions after component move/rotate."""
    dx = comp.pos.x - old_pos.x
    dy = comp.pos.y - old_pos.y
    rot_delta = math.radians(comp.rotation - old_rot)

    for pad in comp.pads:
        if abs(rot_delta) < 0.001:
            # Translation only
            pad.pos = Point(pad.pos.x + dx, pad.pos.y + dy)
        else:
            # Rotate around new component center
            rx = pad.pos.x - old_pos.x
            ry = pad.pos.y - old_pos.y
            cos_r = math.cos(rot_delta)
            sin_r = math.sin(rot_delta)
            pad.pos = Point(
                comp.pos.x + rx * cos_r - ry * sin_r,
                comp.pos.y + rx * sin_r + ry * cos_r,
            )


class PlacementScorer:
    """Scores a placement configuration to guide optimization.

    Evaluates: net distance, crossover count, compactness, edge compliance,
    rotation quality. All computation is local.
    """

    def __init__(self, state: BoardState, config: dict = None):
        self.state = state
        self.cfg = config or {}

    def score(self) -> PlacementScore:
        s = PlacementScore()
        s.net_distance = self._score_net_distance()
        s.crossover_count = count_crossings(self.state)
        s.crossover_score = self._crossover_to_score(s.crossover_count)
        s.compactness = self._score_compactness()
        s.edge_compliance = self._score_edge_compliance()
        s.rotation_score = self._score_rotation()
        s.board_containment = self._score_board_containment()
        s.courtyard_overlap = self._score_courtyard_overlap()
        s.compute_total()
        return s

    def _score_net_distance(self) -> float:
        """Score based on total MST ratsnest length.
        Shorter = better. Normalized to 0-100."""
        total_len = total_ratsnest_length(self.state)
        # Heuristic: board diagonal is worst case per net
        diag = math.hypot(self.state.board_width, self.state.board_height)
        n_nets = max(1, len([n for n in self.state.nets.values()
                             if len(n.pad_refs) >= 2 and n.name not in ("GND", "/GND")]))
        worst_case = diag * n_nets
        if worst_case == 0:
            return 100.0
        ratio = total_len / worst_case
        return max(0, min(100, (1.0 - ratio) * 100))

    def _crossover_to_score(self, crossings: int) -> float:
        """Convert crossing count to 0-100 score. Fewer = better."""
        n_nets = max(1, len(self.state.nets))
        # Max expected crossings ~ n_nets^2 / 4 for random placement
        max_expected = n_nets * n_nets / 4
        if max_expected == 0:
            return 100.0
        ratio = crossings / max_expected
        return max(0, min(100, (1.0 - ratio) * 100))

    def _score_compactness(self) -> float:
        """Ratio of component area to board area. Gentle reward for smaller layouts.
        20% fill = 50, 40% fill = 75, 60%+ = 100. Not heavily penalized."""
        total_area = sum(c.area for c in self.state.components.values())
        board_area = self.state.board_width * self.state.board_height
        if board_area == 0:
            return 0.0
        fill = total_area / board_area
        # Gentle curve: 10% fill ≈ 40, 30% ≈ 65, 50%+ ≈ 90+
        return min(100, fill * 150 + 25)

    def _score_edge_compliance(self) -> float:
        """Check connectors and mounting holes are near board edges."""
        tl, br = self.state.board_outline
        margin = 3.0  # mm from edge
        total = 0
        compliant = 0
        for comp in self.state.components.values():
            if comp.kind not in ("connector", "mounting_hole"):
                continue
            total += 1
            x, y = comp.pos.x, comp.pos.y
            near_edge = (
                x - tl.x <= margin or br.x - x <= margin or
                y - tl.y <= margin or br.y - y <= margin
            )
            if near_edge:
                compliant += 1
        if total == 0:
            return 100.0
        return (compliant / total) * 100

    def _score_rotation(self) -> float:
        """Score component rotations.
        Passives should be at 0 or 90 degrees.
        ICs should minimize net-crossing angles.
        """
        total = 0
        good = 0
        for comp in self.state.components.values():
            if comp.kind in ("passive",):
                total += 1
                r = comp.rotation % 360
                if r in (0, 90, 180, 270):
                    good += 1
                elif r % 45 == 0:
                    good += 0.5
            elif comp.kind == "ic":
                total += 1
                r = comp.rotation % 360
                if r in (0, 90, 180, 270):
                    good += 1
        if total == 0:
            return 100.0
        return (good / total) * 100

    def _score_board_containment(self) -> float:
        """Score how well components and pads stay within the board outline."""
        tl, br = self.state.board_outline

        total_pads = 0
        pads_outside = 0
        total_bodies = 0
        bodies_outside = 0

        for comp in self.state.components.values():
            total_bodies += 1
            c_tl, c_br = comp.bbox()
            if (c_tl.x < tl.x or c_br.x > br.x or
                    c_tl.y < tl.y or c_br.y > br.y):
                bodies_outside += 1

            for pad in comp.pads:
                total_pads += 1
                if (pad.pos.x < tl.x or pad.pos.x > br.x or
                        pad.pos.y < tl.y or pad.pos.y > br.y):
                    pads_outside += 1

        if total_pads == 0 and total_bodies == 0:
            return 100.0

        pad_frac = pads_outside / max(1, total_pads)
        body_frac = bodies_outside / max(1, total_bodies)
        # Weighted: 80% pad containment, 20% body containment
        score = 100.0 * (1.0 - 0.8 * pad_frac - 0.2 * body_frac)
        return max(0.0, min(100.0, score))

    def _score_courtyard_overlap(self) -> float:
        """Penalize overlapping component courtyards.
        Uses bbox with clearance + courtyard_padding_mm as courtyard proxy."""
        comps = list(self.state.components.values())
        base_clearance = 0.25  # mm courtyard margin
        padding = self.cfg.get("courtyard_padding_mm", 0.0)
        clearance = base_clearance + padding
        n = len(comps)
        overlaps = 0
        total_pairs = 0

        for i in range(n):
            a = comps[i]
            for j in range(i + 1, n):
                b = comps[j]
                total_pairs += 1
                a_tl, a_br = a.bbox(clearance)
                b_tl, b_br = b.bbox(clearance)
                if (a_tl.x < b_br.x and a_br.x > b_tl.x and
                        a_tl.y < b_br.y and a_br.y > b_tl.y):
                    overlaps += 1

        if total_pairs == 0:
            return 100.0
        # Each overlap costs 5 points
        return max(0.0, min(100.0, 100.0 - overlaps * 5.0))


class PlacementSolver:
    """Force-directed placement with edge-first constraints and scoring feedback.

    The solver iterates locally — all geometric computation in Python.
    Placement quality is scored each iteration; the solver converges
    when score improvement plateaus.
    """

    def __init__(self, state: BoardState, config: dict = None, seed: int = 0):
        self.state = state
        self.cfg = config or {}
        self.seed = seed
        self.rng = random.Random(seed)
        self.k_attract = self.cfg.get("force_attract_k", 0.08)
        self.k_repel = self.cfg.get("force_repel_k", 40.0)
        self.cooling = self.cfg.get("cooling_factor", 0.97)
        self.edge_margin = self.cfg.get("edge_margin_mm", 2.0)
        self.grid_snap = self.cfg.get("placement_grid_mm", 0.5)
        self.max_iterations = self.cfg.get("max_placement_iterations", 100)
        self.convergence_threshold = self.cfg.get("placement_convergence_threshold", 1.5)
        self.score_every_n = self.cfg.get("placement_score_every_n", 1)
        self.intra_cluster_iters = self.cfg.get("intra_cluster_iters", 80)
        # placement_clearance_mm is the min gap between component bboxes.
        # Falls back to clearance_mm for backwards compatibility, then 2.5mm.
        self.clearance = self.cfg.get(
            "placement_clearance_mm",
            self.cfg.get("clearance_mm", 2.5)
        )
        self._seen_force_states: set[int] = set()

    def solve(self, max_iterations: int = None,
              convergence_threshold: float = None) -> dict[str, Component]:
        """Run full placement pipeline. Returns updated components dict."""
        # Deep copy so we don't mutate the original
        comps = {ref: copy.deepcopy(c) for ref, c in self.state.components.items()}
        # Build a working state for scoring
        work_state = copy.copy(self.state)
        work_state.components = comps

        # Build connectivity graph
        conn_graph = build_connectivity_graph(self.state.nets)

        # Step 1: Pin edge components (connectors, mounting holes)
        self._pin_edge_components(comps)

        # Step 1.5: Use explicit IC groups to boost connectivity weights
        ic_groups = self.cfg.get("ic_groups", {})
        if ic_groups:
            # Add extra weight to connections within IC groups
            for ic_ref, supporting in ic_groups.items():
                for sup_ref in supporting:
                    if sup_ref in comps and ic_ref in comps:
                        conn_graph.add_edge(sup_ref, ic_ref, 2.0)  # Strong bond
            clusters = find_communities(conn_graph, seed=self.seed)
            print(f"  Found {len(clusters)} component clusters (with {len(ic_groups)} IC groups)")
        else:
            # Step 2: Cluster by connectivity (seeded for reproducible variation)
            clusters = find_communities(conn_graph, seed=self.seed)
            print(f"  Found {len(clusters)} component clusters")

        # Step 3: Initial cluster placement (with seeded jitter)
        self._place_clusters(comps, clusters, conn_graph)

        # Step 4: Optimize layout within each cluster before global layout
        self._optimize_intra_cluster(comps, clusters, conn_graph)

        # Step 5: Try 4 rotations per IC/connector, keep best
        self._optimize_rotations(comps, work_state)

        # Step 6: Force-directed refinement with scoring feedback
        scorer = PlacementScorer(work_state, self.cfg)
        best_score = scorer.score()
        best_comps = {r: copy.deepcopy(c) for r, c in comps.items()}
        damping = 1.0
        stagnant = 0
        reheat_strength = self.cfg.get("reheat_strength", 0.0)
        reheat_done = False

        print(f"  Initial placement score: {best_score.total:.1f} "
              f"(nets={best_score.net_distance:.0f} "
              f"cross={best_score.crossover_score:.0f} "
              f"xovers={best_score.crossover_count})")

        for iteration in range(self.max_iterations):
            # Temperature reheat: at 50% of iterations, apply perturbation kick
            if (not reheat_done and reheat_strength > 0
                    and iteration == self.max_iterations // 2):
                reheat_done = True
                tl_r, br_r = self.state.board_outline
                diag = math.hypot(br_r.x - tl_r.x, br_r.y - tl_r.y)
                kick_mag = diag * reheat_strength
                unlocked_refs = [r for r in comps if not comps[r].locked]
                for ref in unlocked_refs:
                    old_pos = Point(comps[ref].pos.x, comps[ref].pos.y)
                    comps[ref].pos.x += self.rng.gauss(0, kick_mag)
                    comps[ref].pos.y += self.rng.gauss(0, kick_mag)
                    # Clamp to board
                    hw, hh = comps[ref].width_mm / 2, comps[ref].height_mm / 2
                    comps[ref].pos.x = max(tl_r.x + hw + 1, min(br_r.x - hw - 1, comps[ref].pos.x))
                    comps[ref].pos.y = max(tl_r.y + hh + 1, min(br_r.y - hh - 1, comps[ref].pos.y))
                    _update_pad_positions(comps[ref], old_pos, comps[ref].rotation)
                damping = 0.7  # partial reheat of damping
                stagnant = 0
                self._seen_force_states.clear()

            if _HAS_NUMPY:
                max_disp = self._force_step_numpy(comps, conn_graph, damping)
            else:
                max_disp = self._force_step(comps, conn_graph, damping)
            self._resolve_overlaps(comps)
            self._clamp_pads_to_board(comps)
            damping *= self.cooling

            # Score more frequently for faster convergence detection
            if iteration % self.score_every_n == 0:
                work_state.components = comps
                s = scorer.score()
                if s.total > best_score.total:
                    best_score = s
                    best_comps = {r: copy.deepcopy(c) for r, c in comps.items()}
                    stagnant = 0
                else:
                    stagnant += 1
                    # If stagnant, revert to best and add jitter
                    if stagnant >= 3 and stagnant % 3 == 0:
                        comps = {r: copy.deepcopy(c) for r, c in best_comps.items()}

                if stagnant >= 10:
                    print(f"  Converged at iteration {iteration+1}")
                    break

            if max_disp < self.convergence_threshold and iteration > 30:
                print(f"  Displacement converged at iteration {iteration+1}")
                break

            # Adaptive convergence: early exit when placement is good and stable
            if (iteration > 15 and best_score.total > 85.0
                    and max_disp < 3.0 and stagnant >= 3):
                print(f"  Adaptive early exit at iteration {iteration+1} "
                      f"(score={best_score.total:.1f}, disp={max_disp:.2f})")
                break

        # Step 7: Swap optimization — directly minimize crossovers
        comps = best_comps
        self._seen_force_states.clear()
        work_state.components = comps
        best_cross = count_crossings(work_state)
        print(f"  Starting swap optimization ({best_cross} crossings)")
        improved = True
        swap_round = 0
        while improved and swap_round < 5:
            improved = False
            swap_round += 1
            unlocked = [r for r in comps if not comps[r].locked]
            for i in range(len(unlocked)):
                for j in range(i + 1, len(unlocked)):
                    a, b = comps[unlocked[i]], comps[unlocked[j]]
                    # Only swap components of similar size
                    size_ratio = max(a.area, b.area) / max(min(a.area, b.area), 0.01)
                    if size_ratio > 4:
                        continue
                    # Swap positions and update pads
                    a.pos, b.pos = Point(b.pos.x, b.pos.y), Point(a.pos.x, a.pos.y)
                    _swap_pad_positions(a, b)
                    cross = count_crossings(work_state)
                    if cross < best_cross:
                        best_cross = cross
                        improved = True
                    else:
                        # Revert
                        a.pos, b.pos = Point(b.pos.x, b.pos.y), Point(a.pos.x, a.pos.y)
                        _swap_pad_positions(a, b)
            if improved:
                print(f"    Swap round {swap_round}: {best_cross} crossings")

        best_comps = comps

        # Step 8: Snap to grid
        self._snap_to_grid(best_comps)

        # Step 9: Final exhaustive overlap resolution — guarantee no courtyard
        # overlaps before routing. Must run after snap since snapping can
        # re-introduce small overlaps.
        self._resolve_overlaps(best_comps)

        # Step 10: Hard clamp — nothing outside the board
        self._clamp_to_board(best_comps)

        # Step 11: Ensure all pads are inside the board boundary
        self._clamp_pads_to_board(best_comps)

        # Final score
        work_state.components = best_comps
        final = PlacementScorer(work_state, self.cfg).score()
        print(f"  Final placement score: {final.total:.1f} "
              f"(nets={final.net_distance:.0f} "
              f"cross={final.crossover_score:.0f} "
              f"xovers={final.crossover_count})")

        return best_comps

    def _score_rotation_for_routing(self, work_state: BoardState, comp: Component) -> float:
        """Score component rotation for routability.
        
        Considers: crossovers, pad accessibility (pads not blocked by component body),
        and net distance.
        """
        cross = count_crossings(work_state)
        cross_score = 100 / (1 + cross) if cross > 0 else 100
        
        # Prefer rotations where pads face outward (toward board edge or open space)
        # Check if pads have clear path to edges
        tl, br = work_state.board_outline
        accessible = 0
        for pad in comp.pads:
            px, py = pad.pos.x, pad.pos.y
            # Check each quadrant for openness
            dirs = [(1,1), (1,-1), (-1,1), (-1,-1)]
            for dx, dy in dirs:
                dist = 0
                ox, oy = px, py
                while dist < 30:
                    ox += dx * 2
                    oy += dy * 2
                    if tl.x < ox < br.x and tl.y < oy < br.y:
                        dist += 2
                    else:
                        break
            accessible += dist
        
        # Higher = more accessible area around pads
        access_score = min(100, accessible / 10)
        
        # Net distance matters for routing
        from .graph import total_ratsnest_length
        net_dist = total_ratsnest_length(work_state)
        dist_score = max(0, 100 - net_dist / 5)
        
        return cross_score * 0.5 + access_score * 0.3 + dist_score * 0.2

    def _pin_edge_components(self, comps: dict[str, Component]):
        """Pin components based on component_zones config, with fallback heuristics.

        Supports three constraint types:
          - edge: snap to named edge (left/right/top/bottom), lock in place
          - corner: pin to named corner (top-left/top-right/bottom-left/bottom-right)
          - zone: confine to a board region (used during _place_clusters, not locked)

        Connectors without explicit zone config fall back to nearest-edge heuristic.
        Mounting holes without config fall back to nearest-corner.

        When unlock_all_footprints is True, initial positions are still set for
        edge/corner constraints but components are NOT locked — the force
        simulation can move them, and edge_compliance scoring incentivizes
        keeping them near edges.
        """
        tl, br = self.state.board_outline
        margin = self.edge_margin
        zones = self.cfg.get("component_zones", {})
        unlock_all = self.cfg.get("unlock_all_footprints", False)

        for ref, comp in comps.items():
            zone_cfg = zones.get(ref, {})

            if "edge" in zone_cfg:
                # Explicit edge assignment
                old_pos = Point(comp.pos.x, comp.pos.y)
                edge = zone_cfg["edge"]
                if edge == "left":
                    comp.pos.x = tl.x + margin
                elif edge == "right":
                    comp.pos.x = br.x - margin
                elif edge == "top":
                    comp.pos.y = tl.y + margin
                elif edge == "bottom":
                    comp.pos.y = br.y - margin
                _update_pad_positions(comp, old_pos, comp.rotation)
                comp.locked = not unlock_all

            elif "corner" in zone_cfg:
                # Explicit corner assignment
                corner = zone_cfg["corner"]
                if "left" in corner:
                    cx = tl.x + margin
                else:
                    cx = br.x - margin
                if "top" in corner:
                    cy = tl.y + margin
                else:
                    cy = br.y - margin
                old_pos = Point(comp.pos.x, comp.pos.y)
                comp.pos = Point(cx, cy)
                _update_pad_positions(comp, old_pos, comp.rotation)
                comp.locked = not unlock_all

            elif "zone" in zone_cfg:
                # Zone constraint — don't lock, just set initial position.
                # Actual confinement is enforced in _place_clusters and force sim.
                pass  # handled later

            elif comp.kind == "connector":
                # Fallback: snap connector to nearest edge
                old_pos = Point(comp.pos.x, comp.pos.y)
                x, y = comp.pos.x, comp.pos.y
                distances = {
                    "left": x - tl.x,
                    "right": br.x - x,
                    "top": y - tl.y,
                    "bottom": br.y - y,
                }
                nearest = min(distances, key=distances.get)
                if nearest == "left":
                    comp.pos.x = tl.x + margin
                elif nearest == "right":
                    comp.pos.x = br.x - margin
                elif nearest == "top":
                    comp.pos.y = tl.y + margin
                elif nearest == "bottom":
                    comp.pos.y = br.y - margin
                _update_pad_positions(comp, old_pos, comp.rotation)
                comp.locked = not unlock_all

            elif comp.kind == "mounting_hole":
                # Fallback: snap mounting hole to nearest corner
                cx = tl.x + margin if comp.pos.x < (tl.x + br.x) / 2 else br.x - margin
                cy = tl.y + margin if comp.pos.y < (tl.y + br.y) / 2 else br.y - margin
                old_pos = Point(comp.pos.x, comp.pos.y)
                comp.pos = Point(cx, cy)
                _update_pad_positions(comp, old_pos, comp.rotation)
                comp.locked = not unlock_all

    def _get_zone_bounds(self, zone_name: str) -> tuple[float, float, float, float]:
        """Return (x_min, y_min, x_max, y_max) for a named board zone."""
        tl, br = self.state.board_outline
        margin = self.edge_margin
        mid_x = (tl.x + br.x) / 2
        mid_y = (tl.y + br.y) / 2

        zone_map = {
            "center":        (tl.x + margin, tl.y + margin, br.x - margin, br.y - margin),
            "center-top":    (tl.x + margin, tl.y + margin, br.x - margin, mid_y),
            "center-bottom": (tl.x + margin, mid_y, br.x - margin, br.y - margin),
            "center-left":   (tl.x + margin, tl.y + margin, mid_x, br.y - margin),
            "center-right":  (mid_x, tl.y + margin, br.x - margin, br.y - margin),
            "top-left":      (tl.x + margin, tl.y + margin, mid_x, mid_y),
            "top-right":     (mid_x, tl.y + margin, br.x - margin, mid_y),
            "bottom-left":   (tl.x + margin, mid_y, mid_x, br.y - margin),
            "bottom-right":  (mid_x, mid_y, br.x - margin, br.y - margin),
        }
        return zone_map.get(zone_name, zone_map["center"])

    def _place_clusters(self, comps: dict[str, Component],
                        clusters: list[set[str]],
                        conn_graph: AdjacencyGraph):
        """Place each cluster's components near their connectivity centroid.

        Supports three placement strategies controlled by config:
          - scatter_mode="cluster": centroid-based with jitter (default, exploit)
          - scatter_mode="random": uniform random within board bounds (explore)
          - signal_flow_order: biases cluster centroids left-to-right
          - component_zones with "zone": confines components to named regions
          - Decoupling caps (C* in ic_groups) placed at tighter radius to IC leader
        """
        tl, br = self.state.board_outline
        margin = self.edge_margin + 5.0  # keep away from edges
        scatter_mode = self.cfg.get("scatter_mode", "cluster")
        signal_flow = self.cfg.get("signal_flow_order", [])
        ic_groups = self.cfg.get("ic_groups", {})
        zones_cfg = self.cfg.get("component_zones", {})
        randomize_group = self.cfg.get("randomize_group_layout", False)

        # Build reverse map: component ref -> group leader
        ref_to_leader = {}
        for leader, members in ic_groups.items():
            ref_to_leader[leader] = leader
            for m in members:
                ref_to_leader[m] = leader

        # Build signal-flow X targets (evenly spaced across board width)
        flow_x_targets = {}
        if signal_flow:
            usable_left = tl.x + margin
            usable_right = br.x - margin
            for i, leader in enumerate(signal_flow):
                frac = (i + 0.5) / len(signal_flow)
                flow_x_targets[leader] = usable_left + frac * (usable_right - usable_left)

        # Find locked component positions for attraction
        locked_positions = {
            ref: comp.pos for ref, comp in comps.items() if comp.locked
        }

        # Sort clusters by total connectivity (highest first) so the most
        # connected cluster gets placed first, improving net-topology bias.
        clusters = sorted(
            clusters,
            key=lambda c: sum(conn_graph.degree(r) for r in c),
            reverse=True,
        )

        for cluster in clusters:
            unlocked = [r for r in cluster if not comps[r].locked]
            if not unlocked:
                continue

            if scatter_mode == "random":
                # --- Random scatter: uniform random positions within bounds ---
                # Sort by area descending: large components placed first
                unlocked.sort(key=lambda r: comps[r].area, reverse=True)
                for ref in unlocked:
                    zone_cfg = zones_cfg.get(ref, {})
                    if "zone" in zone_cfg:
                        zx0, zy0, zx1, zy1 = self._get_zone_bounds(zone_cfg["zone"])
                    else:
                        zx0, zy0 = tl.x + margin, tl.y + margin
                        zx1, zy1 = br.x - margin, br.y - margin

                    hw, hh = comps[ref].width_mm / 2, comps[ref].height_mm / 2
                    old_pos = Point(comps[ref].pos.x, comps[ref].pos.y)
                    old_rot = comps[ref].rotation
                    comps[ref].pos = Point(
                        self.rng.uniform(zx0 + hw, max(zx0 + hw + 1, zx1 - hw)),
                        self.rng.uniform(zy0 + hh, max(zy0 + hh + 1, zy1 - hh)),
                    )
                    # Random allowed rotation
                    if comps[ref].kind == "ic":
                        comps[ref].rotation = self.rng.choice([0, 90, 180, 270])
                    elif comps[ref].kind == "passive":
                        comps[ref].rotation = self.rng.choice([0, 90])
                    _update_pad_positions(comps[ref], old_pos, old_rot)
                continue

            # --- Cluster mode: centroid-based with signal-flow bias ---
            # Compute centroid from locked neighbors' positions
            cx, cy, weight_sum = 0.0, 0.0, 0.0
            for ref in unlocked:
                for locked_ref, lpos in locked_positions.items():
                    w = conn_graph.weight(ref, locked_ref)
                    if w > 0:
                        cx += lpos.x * w
                        cy += lpos.y * w
                        weight_sum += w

            if weight_sum > 0:
                cx /= weight_sum
                cy /= weight_sum
            else:
                # Default to board center
                cx = (tl.x + br.x) / 2
                cy = (tl.y + br.y) / 2

            # Apply signal-flow X bias: blend centroid toward target X
            # Find the cluster's group leader (if any)
            cluster_leader = None
            for ref in cluster:
                leader = ref_to_leader.get(ref)
                if leader and leader in flow_x_targets:
                    cluster_leader = leader
                    break
            if cluster_leader and cluster_leader in flow_x_targets:
                target_x = flow_x_targets[cluster_leader]
                # 60% bias toward signal-flow target, 40% toward connectivity
                cx = 0.4 * cx + 0.6 * target_x

            # Clamp to board interior
            cx = max(tl.x + margin, min(br.x - margin, cx))
            cy = max(tl.y + margin, min(br.y - margin, cy))

            # Apply zone constraints: override centroid if component has a zone
            # (uses first zone-constrained component in cluster to bias centroid)
            for ref in unlocked:
                zone_cfg = zones_cfg.get(ref, {})
                if "zone" in zone_cfg:
                    zx0, zy0, zx1, zy1 = self._get_zone_bounds(zone_cfg["zone"])
                    cx = max(zx0, min(zx1, cx))
                    cy = max(zy0, min(zy1, cy))
                    break

            # Spread components around centroid (with seeded jitter)
            n = len(unlocked)
            # Sort by area descending: ICs and large components placed first,
            # then passives fill in around them.
            unlocked.sort(key=lambda r: comps[r].area, reverse=True)
            radius = math.sqrt(n) * 3.0  # spread based on count

            # Radius variation: wider for randomize_group_layout mode
            r_lo, r_hi = (0.3, 1.8) if randomize_group else (0.8, 1.2)

            # Track placed components for net-topology bias
            placed_this_cluster: set[str] = set()

            for i, ref in enumerate(unlocked):
                # Net-topology bias: if this component has already-placed
                # connected neighbors, bias position toward their centroid.
                nbr_cx, nbr_cy, nbr_w = 0.0, 0.0, 0.0
                for nbr, w in conn_graph.neighbors(ref).items():
                    if nbr in comps and (comps[nbr].locked or nbr in placed_this_cluster):
                        nbr_cx += comps[nbr].pos.x * w
                        nbr_cy += comps[nbr].pos.y * w
                        nbr_w += w
                if nbr_w > 0:
                    # Blend 50% toward connected neighbors, 50% toward cluster centroid
                    local_cx = 0.5 * cx + 0.5 * (nbr_cx / nbr_w)
                    local_cy = 0.5 * cy + 0.5 * (nbr_cy / nbr_w)
                else:
                    local_cx, local_cy = cx, cy

                # Decoupling cap proximity: caps in IC groups get tighter radius
                is_decoupling_cap = (
                    ref.startswith("C") and
                    ref in ref_to_leader and
                    ref_to_leader[ref] != ref  # not the leader itself
                )
                if is_decoupling_cap:
                    # Place within 1.5× clearance of centroid (very tight)
                    r = self.clearance * 1.5 * self.rng.uniform(0.6, 1.0)
                else:
                    r = radius * (0.5 + 0.5 * (i % 2)) * self.rng.uniform(r_lo, r_hi)

                angle = 2 * math.pi * i / max(n, 1) + self.rng.gauss(0, 0.3)

                old_pos = Point(comps[ref].pos.x, comps[ref].pos.y)
                old_rot = comps[ref].rotation
                new_x = local_cx + r * math.cos(angle)
                new_y = local_cy + r * math.sin(angle)

                # Enforce zone bounds if component has a zone constraint
                zone_cfg = zones_cfg.get(ref, {})
                if "zone" in zone_cfg:
                    zx0, zy0, zx1, zy1 = self._get_zone_bounds(zone_cfg["zone"])
                    hw, hh = comps[ref].width_mm / 2, comps[ref].height_mm / 2
                    new_x = max(zx0 + hw, min(zx1 - hw, new_x))
                    new_y = max(zy0 + hh, min(zy1 - hh, new_y))

                comps[ref].pos = Point(new_x, new_y)
                _update_pad_positions(comps[ref], old_pos, old_rot)

                # Early rotation: try all 4 orientations for ICs at placement
                # time — prevents suboptimal rotations from locking in.
                if comps[ref].kind == "ic" and len(comps[ref].pads) >= 2:
                    pad_offsets = [
                        (p.pos.x - comps[ref].pos.x, p.pos.y - comps[ref].pos.y)
                        for p in comps[ref].pads
                    ]
                    orig_rot = comps[ref].rotation
                    best_rot = orig_rot
                    best_rscore = -1.0
                    temp_state = copy.copy(self.state)
                    temp_state.components = comps
                    for rot in [0, 90, 180, 270]:
                        delta = math.radians(rot - orig_rot)
                        cos_d, sin_d = math.cos(delta), math.sin(delta)
                        for k, p in enumerate(comps[ref].pads):
                            ox, oy = pad_offsets[k]
                            p.pos = Point(
                                comps[ref].pos.x + ox * cos_d - oy * sin_d,
                                comps[ref].pos.y + ox * sin_d + oy * cos_d,
                            )
                        comps[ref].rotation = rot
                        rscore = self._score_rotation_for_routing(temp_state, comps[ref])
                        if rscore > best_rscore:
                            best_rscore = rscore
                            best_rot = rot
                    # Apply best rotation
                    delta = math.radians(best_rot - orig_rot)
                    cos_d, sin_d = math.cos(delta), math.sin(delta)
                    for k, p in enumerate(comps[ref].pads):
                        ox, oy = pad_offsets[k]
                        p.pos = Point(
                            comps[ref].pos.x + ox * cos_d - oy * sin_d,
                            comps[ref].pos.y + ox * sin_d + oy * cos_d,
                        )
                    comps[ref].rotation = best_rot

                placed_this_cluster.add(ref)

    def _optimize_intra_cluster(self, comps: dict[str, Component],
                                clusters: list[set[str]],
                                conn_graph: AdjacencyGraph):
        """Run a short force-directed pass within each cluster independently.

        This arranges components within functional groups (e.g. charger IC
        with its caps and resistors) before the global layout decides
        where groups go relative to each other.
        """
        tl, br = self.state.board_outline
        for cluster in clusters:
            unlocked = [r for r in cluster if not comps[r].locked]
            if len(unlocked) < 2:
                continue

            # Compute cluster centroid
            cx = sum(comps[r].pos.x for r in unlocked) / len(unlocked)
            cy = sum(comps[r].pos.y for r in unlocked) / len(unlocked)

            # Mini force-directed loop: attract connected, repel overlapping
            damping = 1.0
            for _ in range(self.intra_cluster_iters):
                forces = {r: Point(0, 0) for r in unlocked}

                # Attract connected pairs within cluster
                for i, ra in enumerate(unlocked):
                    for rb in unlocked[i + 1:]:
                        w = conn_graph.weight(ra, rb)
                        if w <= 0:
                            continue
                        a, b = comps[ra], comps[rb]
                        d = max(a.pos.dist(b.pos), 0.1)
                        # Pull together proportional to distance and weight
                        f = self.k_attract * w * d
                        dx = (b.pos.x - a.pos.x) / d * f
                        dy = (b.pos.y - a.pos.y) / d * f
                        forces[ra].x += dx
                        forces[ra].y += dy
                        forces[rb].x -= dx
                        forces[rb].y -= dy

                # Repel overlapping bboxes
                for i, ra in enumerate(unlocked):
                    for rb in unlocked[i + 1:]:
                        a, b = comps[ra], comps[rb]
                        overlap = _bbox_overlap_amount(a, b)
                        if overlap <= 0:
                            continue
                        d = max(a.pos.dist(b.pos), 0.1)
                        f = 3.0 * math.sqrt(overlap)
                        dx = (a.pos.x - b.pos.x) / d * f
                        dy = (a.pos.y - b.pos.y) / d * f
                        forces[ra].x += dx
                        forces[ra].y += dy
                        forces[rb].x -= dx
                        forces[rb].y -= dy

                # Apply forces
                for r in unlocked:
                    dx = forces[r].x * damping
                    dy = forces[r].y * damping
                    mag = math.hypot(dx, dy)
                    max_step = 1.5 * damping
                    if mag > max_step:
                        dx *= max_step / mag
                        dy *= max_step / mag

                    old_pos = Point(comps[r].pos.x, comps[r].pos.y)
                    comps[r].pos.x += dx
                    comps[r].pos.y += dy
                    # Clamp to board
                    hw, hh = comps[r].width_mm / 2, comps[r].height_mm / 2
                    comps[r].pos.x = max(tl.x + hw + 1.0, min(br.x - hw - 1.0, comps[r].pos.x))
                    comps[r].pos.y = max(tl.y + hh + 1.0, min(br.y - hh - 1.0, comps[r].pos.y))
                    _update_pad_positions(comps[r], old_pos, comps[r].rotation)

                damping *= 0.95

        print(f"  Intra-cluster optimization done ({len(clusters)} clusters)")

    def _optimize_rotations(self, comps: dict[str, Component],
                            work_state: BoardState):
        """Try 0/90/180/270 rotations - optimize for routing (low crossovers + accessible pads)."""
        work_state.components = comps

        for ref, comp in comps.items():
            if comp.locked or comp.kind == "mounting_hole":
                continue
            if len(comp.pads) < 2:
                continue

            # Store pad offsets relative to component center
            pad_offsets = []
            for p in comp.pads:
                pad_offsets.append((p.pos.x - comp.pos.x, p.pos.y - comp.pos.y))

            orig_rot = comp.rotation
            best_rot = orig_rot
            best_score = self._score_rotation_for_routing(work_state, comp)

            for rot in [0, 90, 180, 270]:
                if rot == orig_rot:
                    continue
                # Apply rotation: rotate pad offsets by (rot - orig_rot)
                delta = math.radians(rot - orig_rot)
                cos_d, sin_d = math.cos(delta), math.sin(delta)
                for i, p in enumerate(comp.pads):
                    ox, oy = pad_offsets[i]
                    p.pos = Point(
                        comp.pos.x + ox * cos_d - oy * sin_d,
                        comp.pos.y + ox * sin_d + oy * cos_d,
                    )
                comp.rotation = rot

                rot_score = self._score_rotation_for_routing(work_state, comp)
                if rot_score > best_score:
                    best_score = rot_score
                    best_rot = rot

            # Apply best rotation
            if best_rot != orig_rot:
                delta = math.radians(best_rot - orig_rot)
            else:
                delta = 0.0
            cos_d, sin_d = math.cos(delta), math.sin(delta)
            for i, p in enumerate(comp.pads):
                ox, oy = pad_offsets[i]
                p.pos = Point(
                    comp.pos.x + ox * cos_d - oy * sin_d,
                    comp.pos.y + ox * sin_d + oy * cos_d,
                )
            comp.rotation = best_rot

    def _force_step(self, comps: dict[str, Component],
                    conn_graph: AdjacencyGraph,
                    damping: float) -> float:
        """One iteration of force-directed simulation. Returns max displacement."""
        # State dedup: skip if we've seen this exact layout before
        state_h = hash(tuple(
            (r, round(comps[r].pos.x, 2), round(comps[r].pos.y, 2))
            for r in sorted(comps.keys())
        ))
        if state_h in self._seen_force_states:
            return 0.01  # signal convergence
        self._seen_force_states.add(state_h)

        tl, br = self.state.board_outline
        forces: dict[str, Point] = {ref: Point(0, 0) for ref in comps}
        refs = [r for r in comps if not comps[r].locked]

        # Attraction: pull connected components together
        for ref in refs:
            for nbr, weight in conn_graph.neighbors(ref).items():
                if nbr not in comps:
                    continue
                a = comps[ref]
                b = comps[nbr]
                d = a.pos.dist(b.pos)
                if d < 0.1:
                    continue
                # Target distance based on component sizes
                target = (a.width_mm + b.width_mm) / 2 + self.clearance
                f_mag = self.k_attract * weight * (d - target)
                angle = math.atan2(b.pos.y - a.pos.y, b.pos.x - a.pos.x)
                forces[ref].x += f_mag * math.cos(angle)
                forces[ref].y += f_mag * math.sin(angle)

        # Repulsion: push overlapping/close components apart.
        # Locked components (connectors, holes) act as repellers even though
        # they don't move — this keeps unlocked parts from clustering against them.
        ref_list = list(comps.keys())
        for i in range(len(ref_list)):
            a = comps[ref_list[i]]
            for j in range(i + 1, len(ref_list)):
                b = comps[ref_list[j]]
                if a.locked and b.locked:
                    continue  # both fixed, nothing to do
                d = a.pos.dist(b.pos)
                min_dist = (max(a.width_mm, a.height_mm) +
                            max(b.width_mm, b.height_mm)) / 2 + self.clearance
                if d > min_dist * 2:
                    continue  # too far to matter
                if d < 0.1:
                    d = 0.1
                f_mag = self.k_repel * (a.area * b.area) / (d * d)
                angle = math.atan2(a.pos.y - b.pos.y, a.pos.x - b.pos.x)
                fx = f_mag * math.cos(angle)
                fy = f_mag * math.sin(angle)
                if not a.locked:
                    forces[ref_list[i]].x += fx
                    forces[ref_list[i]].y += fy
                if not b.locked:
                    forces[ref_list[j]].x -= fx
                    forces[ref_list[j]].y -= fy

        # Boundary: strong spring force at edges
        margin = self.edge_margin + 2.0
        k_boundary = 10.0
        for ref in refs:
            c = comps[ref]
            hw, hh = c.width_mm / 2, c.height_mm / 2
            if c.pos.x - hw < tl.x + margin:
                forces[ref].x += k_boundary * (tl.x + margin - (c.pos.x - hw))
            if c.pos.x + hw > br.x - margin:
                forces[ref].x -= k_boundary * ((c.pos.x + hw) - (br.x - margin))
            if c.pos.y - hh < tl.y + margin:
                forces[ref].y += k_boundary * (tl.y + margin - (c.pos.y - hh))
            if c.pos.y + hh > br.y - margin:
                forces[ref].y -= k_boundary * ((c.pos.y + hh) - (br.y - margin))

        # Apply forces
        max_disp = 0.0
        for ref in refs:
            dx = forces[ref].x * damping
            dy = forces[ref].y * damping
            # Clamp max displacement per step
            mag = math.hypot(dx, dy)
            max_step = 2.0 * damping
            if mag > max_step:
                dx *= max_step / mag
                dy *= max_step / mag
                mag = max_step

            old_pos = Point(comps[ref].pos.x, comps[ref].pos.y)
            old_rot = comps[ref].rotation
            comps[ref].pos.x += dx
            comps[ref].pos.y += dy

            # Hard clamp: component bounding box must stay inside board
            c = comps[ref]
            hw, hh = c.width_mm / 2, c.height_mm / 2
            c.pos.x = max(tl.x + hw + 1.0, min(br.x - hw - 1.0, c.pos.x))
            c.pos.y = max(tl.y + hh + 1.0, min(br.y - hh - 1.0, c.pos.y))

            _update_pad_positions(comps[ref], old_pos, old_rot)

            max_disp = max(max_disp, mag)

        return max_disp

    def _force_step_numpy(self, comps: dict[str, Component],
                          conn_graph: AdjacencyGraph,
                          damping: float) -> float:
        """One iteration of force-directed simulation with numpy vectorization.
        Returns max displacement."""
        if not _HAS_NUMPY:
            return self._force_step(comps, conn_graph, damping)

        # State dedup: skip if we've seen this exact layout before
        state_h = hash(tuple(
            (r, round(comps[r].pos.x, 2), round(comps[r].pos.y, 2))
            for r in sorted(comps.keys())
        ))
        if state_h in self._seen_force_states:
            return 0.01
        self._seen_force_states.add(state_h)

        tl, br = self.state.board_outline
        forces: dict[str, Point] = {ref: Point(0, 0) for ref in comps}
        refs = [r for r in comps if not comps[r].locked]

        for ref in refs:
            for nbr, weight in conn_graph.neighbors(ref).items():
                if nbr not in comps:
                    continue
                a = comps[ref]
                b = comps[nbr]
                d = a.pos.dist(b.pos)
                if d < 0.1:
                    continue
                target = (a.width_mm + b.width_mm) / 2 + self.clearance
                f_mag = self.k_attract * weight * (d - target)
                angle = math.atan2(b.pos.y - a.pos.y, b.pos.x - a.pos.x)
                forces[ref].x += f_mag * math.cos(angle)
                forces[ref].y += f_mag * math.sin(angle)

        ref_list = list(comps.keys())
        n = len(ref_list)

        pos_x = np.array([comps[r].pos.x for r in ref_list], dtype=np.float64)
        pos_y = np.array([comps[r].pos.y for r in ref_list], dtype=np.float64)
        areas = np.array([comps[r].area for r in ref_list], dtype=np.float64)
        widths = np.array([comps[r].width_mm for r in ref_list], dtype=np.float64)
        heights = np.array([comps[r].height_mm for r in ref_list], dtype=np.float64)
        locked = np.array([comps[r].locked for r in ref_list], dtype=bool)

        max_dims = np.maximum(widths, heights)
        min_dists = (max_dims[:, np.newaxis] + max_dims[np.newaxis, :]) / 2 + self.clearance

        dx = pos_x[:, np.newaxis] - pos_x[np.newaxis, :]
        dy = pos_y[:, np.newaxis] - pos_y[np.newaxis, :]
        dists = np.sqrt(dx * dx + dy * dy)

        skip_mask = (dists > min_dists * 2) | (dists < 0.001)

        force_mags = self.k_repel * (areas[:, np.newaxis] * areas[np.newaxis, :]) / (dists * dists + 0.01)
        np.fill_diagonal(force_mags, 0)
        force_mags = np.where(skip_mask, 0, force_mags)

        safe_dists = np.where(dists > 0.1, dists, 0.1)
        norm_dx = dx / safe_dists
        norm_dy = dy / safe_dists

        fx_matrix = force_mags * norm_dx
        fy_matrix = force_mags * norm_dy

        both_locked = locked[:, np.newaxis] & locked[np.newaxis, :]
        np.fill_diagonal(both_locked, False)

        fx_matrix = np.where(both_locked, 0, fx_matrix)
        fy_matrix = np.where(both_locked, 0, fy_matrix)

        fx_totals = fx_matrix.sum(axis=1)
        fy_totals = fy_matrix.sum(axis=1)

        for i, ref in enumerate(ref_list):
            if not comps[ref].locked:
                forces[ref].x += float(fx_totals[i])
                forces[ref].y += float(fy_totals[i])

        margin = self.edge_margin + 2.0
        k_boundary = 10.0
        for ref in refs:
            c = comps[ref]
            hw, hh = c.width_mm / 2, c.height_mm / 2
            if c.pos.x - hw < tl.x + margin:
                forces[ref].x += k_boundary * (tl.x + margin - (c.pos.x - hw))
            if c.pos.x + hw > br.x - margin:
                forces[ref].x -= k_boundary * ((c.pos.x + hw) - (br.x - margin))
            if c.pos.y - hh < tl.y + margin:
                forces[ref].y += k_boundary * (tl.y + margin - (c.pos.y - hh))
            if c.pos.y + hh > br.y - margin:
                forces[ref].y -= k_boundary * ((c.pos.y + hh) - (br.y - margin))

        max_disp = 0.0
        for ref in refs:
            dx = forces[ref].x * damping
            dy = forces[ref].y * damping
            mag = math.hypot(dx, dy)
            max_step = 2.0 * damping
            if mag > max_step:
                dx *= max_step / mag
                dy *= max_step / mag
                mag = max_step

            old_pos = Point(comps[ref].pos.x, comps[ref].pos.y)
            old_rot = comps[ref].rotation
            comps[ref].pos.x += dx
            comps[ref].pos.y += dy

            c = comps[ref]
            hw, hh = c.width_mm / 2, c.height_mm / 2
            c.pos.x = max(tl.x + hw + 1.0, min(br.x - hw - 1.0, c.pos.x))
            c.pos.y = max(tl.y + hh + 1.0, min(br.y - hh - 1.0, c.pos.y))

            _update_pad_positions(comps[ref], old_pos, old_rot)

            max_disp = max(max_disp, mag)

        return max_disp

    def _resolve_overlaps(self, comps: dict[str, Component]):
        """Push apart components until no bboxes overlap (including clearance gap).

        For each overlapping pair, picks the escape direction that requires the
        least travel distance AND keeps the free component within board bounds.
        This handles edge cases where the shortest-axis push would send a component
        into a board edge (e.g. a small part trapped between a large locked battery
        holder and the board boundary).
        """
        refs = list(comps.keys())
        half_gap = self.clearance / 2.0
        tl, br = self.state.board_outline

        def _escape(free_c: Component, lock_tl: Point, lock_br: Point) -> bool:
            """Push free_c out of lock bbox. Returns True if moved."""
            hw, hh = free_c.width_mm / 2, free_c.height_mm / 2
            fc_tl, fc_br = free_c.bbox(half_gap)
            ox = min(lock_br.x, fc_br.x) - max(lock_tl.x, fc_tl.x)
            oy = min(lock_br.y, fc_br.y) - max(lock_tl.y, fc_tl.y)
            if ox <= 0 or oy <= 0:
                return False

            # 4 candidate escape moves: (travel_dist, new_x, new_y)
            # "escape right": move fc's left edge to lock's right edge
            # "escape left":  move fc's right edge to lock's left edge
            # "escape down":  move fc's top edge to lock's bottom edge
            # "escape up":    move fc's bottom edge to lock's top edge
            moves = [
                (ox + 0.1, free_c.pos.x + ox + 0.1, free_c.pos.y),  # right
                (ox + 0.1, free_c.pos.x - ox - 0.1, free_c.pos.y),  # left
                (oy + 0.1, free_c.pos.x, free_c.pos.y + oy + 0.1),  # down
                (oy + 0.1, free_c.pos.x, free_c.pos.y - oy - 0.1),  # up
            ]

            # Prefer moves that don't require clamping at the board edge
            best = None
            for travel, nx, ny in moves:
                nx_c = max(tl.x + hw + 1.0, min(br.x - hw - 1.0, nx))
                ny_c = max(tl.y + hh + 1.0, min(br.y - hh - 1.0, ny))
                clamped = (abs(nx_c - nx) > 0.01 or abs(ny_c - ny) > 0.01)
                key = (1 if clamped else 0, travel)
                if best is None or key < best[0]:
                    best = (key, nx_c, ny_c)

            _, nx, ny = best
            old = Point(free_c.pos.x, free_c.pos.y)
            free_c.pos.x, free_c.pos.y = nx, ny
            _update_pad_positions(free_c, old, free_c.rotation)
            return True

        for iteration in range(300):
            moved = False
            for i in range(len(refs)):
                a = comps[refs[i]]
                a_tl, a_br = a.bbox(half_gap)
                for j in range(i + 1, len(refs)):
                    b = comps[refs[j]]
                    if a.locked and b.locked:
                        continue

                    b_tl, b_br = b.bbox(half_gap)
                    ox = min(a_br.x, b_br.x) - max(a_tl.x, b_tl.x)
                    oy = min(a_br.y, b_br.y) - max(a_tl.y, b_tl.y)
                    if ox <= 0 or oy <= 0:
                        continue

                    if a.locked:
                        if _escape(b, a_tl, a_br):
                            b_tl, b_br = b.bbox(half_gap)
                            moved = True
                    elif b.locked:
                        if _escape(a, b_tl, b_br):
                            a_tl, a_br = a.bbox(half_gap)
                            moved = True
                    else:
                        # Both free: split the push evenly
                        hw_a, hh_a = a.width_mm / 2, a.height_mm / 2
                        hw_b, hh_b = b.width_mm / 2, b.height_mm / 2
                        if ox < oy:
                            push = (ox + 0.1) / 2
                            sign = 1.0 if a.pos.x >= b.pos.x else -1.0
                            old_a = Point(a.pos.x, a.pos.y)
                            old_b = Point(b.pos.x, b.pos.y)
                            a.pos.x = max(tl.x + hw_a + 1.0,
                                          min(br.x - hw_a - 1.0, a.pos.x + sign * push))
                            b.pos.x = max(tl.x + hw_b + 1.0,
                                          min(br.x - hw_b - 1.0, b.pos.x - sign * push))
                        else:
                            push = (oy + 0.1) / 2
                            sign = 1.0 if a.pos.y >= b.pos.y else -1.0
                            old_a = Point(a.pos.x, a.pos.y)
                            old_b = Point(b.pos.x, b.pos.y)
                            a.pos.y = max(tl.y + hh_a + 1.0,
                                          min(br.y - hh_a - 1.0, a.pos.y + sign * push))
                            b.pos.y = max(tl.y + hh_b + 1.0,
                                          min(br.y - hh_b - 1.0, b.pos.y - sign * push))
                        _update_pad_positions(a, old_a, a.rotation)
                        _update_pad_positions(b, old_b, b.rotation)
                        a_tl, a_br = a.bbox(half_gap)
                        moved = True

            if not moved:
                break  # fully separated

    def _clamp_to_board(self, comps: dict[str, Component]):
        """Hard clamp: force every component's bounding box inside the board."""
        tl, br = self.state.board_outline
        for comp in comps.values():
            if comp.locked:
                continue
            hw, hh = comp.width_mm / 2, comp.height_mm / 2
            old_pos = Point(comp.pos.x, comp.pos.y)
            comp.pos.x = max(tl.x + hw + 1.0, min(br.x - hw - 1.0, comp.pos.x))
            comp.pos.y = max(tl.y + hh + 1.0, min(br.y - hh - 1.0, comp.pos.y))
            if comp.pos.x != old_pos.x or comp.pos.y != old_pos.y:
                _update_pad_positions(comp, old_pos, comp.rotation)

    def _clamp_pads_to_board(self, comps: dict[str, Component]):
        """Hard clamp: shift components inward so all pads are inside the board."""
        tl, br = self.state.board_outline
        inset = self.cfg.get("pad_inset_margin_mm", 0.3)
        min_x = tl.x + inset
        min_y = tl.y + inset
        max_x = br.x - inset
        max_y = br.y - inset

        for comp in comps.values():
            if not comp.pads:
                continue

            # Find max violation across all pads
            shift_x = 0.0
            shift_y = 0.0
            for pad in comp.pads:
                if pad.pos.x < min_x:
                    shift_x = max(shift_x, min_x - pad.pos.x)
                elif pad.pos.x > max_x:
                    shift_x = min(shift_x, max_x - pad.pos.x)
                if pad.pos.y < min_y:
                    shift_y = max(shift_y, min_y - pad.pos.y)
                elif pad.pos.y > max_y:
                    shift_y = min(shift_y, max_y - pad.pos.y)

            if abs(shift_x) > 0.001 or abs(shift_y) > 0.001:
                old_pos = Point(comp.pos.x, comp.pos.y)
                comp.pos.x += shift_x
                comp.pos.y += shift_y
                _update_pad_positions(comp, old_pos, comp.rotation)

    def _snap_to_grid(self, comps: dict[str, Component]):
        """Snap all unlocked components to placement grid."""
        g = self.grid_snap
        for comp in comps.values():
            if comp.locked:
                continue
            old_pos = Point(comp.pos.x, comp.pos.y)
            comp.pos.x = round(comp.pos.x / g) * g
            comp.pos.y = round(comp.pos.y / g) * g
            _update_pad_positions(comp, old_pos, comp.rotation)
