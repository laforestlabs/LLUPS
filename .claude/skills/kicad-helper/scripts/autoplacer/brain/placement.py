"""PlacementSolver — edge-first pinning, clustering, force-directed placement
with integrated scoring to minimize routing difficulty.

Pure Python. All iteration runs locally — no LLM calls in the loop.
"""
from __future__ import annotations
import copy
import math
import random
from collections import defaultdict

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

    def __init__(self, state: BoardState):
        self.state = state

    def score(self) -> PlacementScore:
        s = PlacementScore()
        s.net_distance = self._score_net_distance()
        s.crossover_count = count_crossings(self.state)
        s.crossover_score = self._crossover_to_score(s.crossover_count)
        s.compactness = self._score_compactness()
        s.edge_compliance = self._score_edge_compliance()
        s.rotation_score = self._score_rotation()
        s.board_containment = self._score_board_containment()
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
        """Ratio of component area to board area. Higher = more compact."""
        total_area = sum(c.area for c in self.state.components.values())
        board_area = self.state.board_width * self.state.board_height
        if board_area == 0:
            return 0.0
        return min(100, (total_area / board_area) * 200)  # 50% fill = 100 score

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
        """Score how well components and pads stay within the board outline.

        Edge-mounted connectors (kind=connector) are excluded — their pads
        intentionally overhang the board edge (USB, battery holders, etc).
        """
        tl, br = self.state.board_outline

        total_pads = 0
        pads_outside = 0
        total_bodies = 0
        bodies_outside = 0

        for comp in self.state.components.values():
            # Connectors are edge-mounted by design — skip containment check
            if comp.kind in ("connector", "mounting_hole"):
                continue

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

        penalty = pads_outside * 10.0 + bodies_outside * 3.0
        return max(0.0, min(100.0, 100.0 - penalty))


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
        self.clearance = self.cfg.get("clearance_mm", 0.5)

    def solve(self, max_iterations: int = 300,
              convergence_threshold: float = 0.5) -> dict[str, Component]:
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

        # Step 2: Cluster by connectivity (seeded for reproducible variation)
        clusters = find_communities(conn_graph, seed=self.seed)
        print(f"  Found {len(clusters)} component clusters")

        # Step 3: Initial cluster placement (with seeded jitter)
        self._place_clusters(comps, clusters, conn_graph)

        # Step 4: Try 4 rotations per IC/connector, keep best
        self._optimize_rotations(comps, work_state)

        # Step 5: Force-directed refinement with scoring feedback
        scorer = PlacementScorer(work_state)
        best_score = scorer.score()
        best_comps = {r: copy.deepcopy(c) for r, c in comps.items()}
        damping = 1.0
        stagnant = 0

        print(f"  Initial placement score: {best_score.total:.1f} "
              f"(nets={best_score.net_distance:.0f} "
              f"cross={best_score.crossover_score:.0f} "
              f"xovers={best_score.crossover_count})")

        for iteration in range(max_iterations):
            max_disp = self._force_step(comps, conn_graph, damping)
            self._resolve_overlaps(comps)
            damping *= self.cooling

            # Score every 5 iterations — revert to best if worse
            if iteration % 5 == 4:
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

            if max_disp < convergence_threshold and iteration > 30:
                print(f"  Displacement converged at iteration {iteration+1}")
                break

        # Step 6: Swap optimization — directly minimize crossovers
        comps = best_comps
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

        # Step 7: Snap to grid
        self._snap_to_grid(best_comps)

        # Step 8: Hard clamp — nothing outside the board
        self._clamp_to_board(best_comps)

        # Final score
        work_state.components = best_comps
        final = PlacementScorer(work_state).score()
        print(f"  Final placement score: {final.total:.1f} "
              f"(nets={final.net_distance:.0f} "
              f"cross={final.crossover_score:.0f} "
              f"xovers={final.crossover_count})")

        return best_comps

    def _pin_edge_components(self, comps: dict[str, Component]):
        """Lock connectors to nearest board edge, mounting holes to corners."""
        tl, br = self.state.board_outline
        margin = self.edge_margin

        for comp in comps.values():
            if comp.kind == "connector":
                # Find nearest edge and center on it
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
                comp.locked = True

            elif comp.kind == "mounting_hole":
                # Place at nearest corner
                cx = tl.x + margin if comp.pos.x < (tl.x + br.x) / 2 else br.x - margin
                cy = tl.y + margin if comp.pos.y < (tl.y + br.y) / 2 else br.y - margin
                comp.pos = Point(cx, cy)
                comp.locked = True

    def _place_clusters(self, comps: dict[str, Component],
                        clusters: list[set[str]],
                        conn_graph: AdjacencyGraph):
        """Place each cluster's components near their connectivity centroid."""
        tl, br = self.state.board_outline
        margin = self.edge_margin + 5.0  # keep away from edges

        # Find locked component positions for attraction
        locked_positions = {
            ref: comp.pos for ref, comp in comps.items() if comp.locked
        }

        for cluster in clusters:
            unlocked = [r for r in cluster if not comps[r].locked]
            if not unlocked:
                continue

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

            # Clamp to board interior
            cx = max(tl.x + margin, min(br.x - margin, cx))
            cy = max(tl.y + margin, min(br.y - margin, cy))

            # Spread components around centroid (with seeded jitter)
            n = len(unlocked)
            self.rng.shuffle(unlocked)  # randomize cluster member ordering
            radius = math.sqrt(n) * 3.0  # spread based on count
            for i, ref in enumerate(unlocked):
                angle = 2 * math.pi * i / max(n, 1) + self.rng.gauss(0, 0.3)
                r = radius * (0.5 + 0.5 * (i % 2)) * self.rng.uniform(0.8, 1.2)
                old_pos = Point(comps[ref].pos.x, comps[ref].pos.y)
                old_rot = comps[ref].rotation
                comps[ref].pos = Point(
                    cx + r * math.cos(angle),
                    cy + r * math.sin(angle),
                )
                _update_pad_positions(comps[ref], old_pos, old_rot)

    def _optimize_rotations(self, comps: dict[str, Component],
                            work_state: BoardState):
        """Try 0/90/180/270 rotations for each unlocked component, keep best."""
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
            best_cross = count_crossings(work_state)

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

                cross = count_crossings(work_state)
                if cross < best_cross:
                    best_cross = cross
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

        # Repulsion: push overlapping/close components apart
        ref_list = list(comps.keys())
        for i in range(len(ref_list)):
            if comps[ref_list[i]].locked:
                continue
            a = comps[ref_list[i]]
            for j in range(i + 1, len(ref_list)):
                b = comps[ref_list[j]]
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

    def _resolve_overlaps(self, comps: dict[str, Component]):
        """Push apart overlapping components."""
        refs = list(comps.keys())
        for _ in range(5):  # few iterations
            moved = False
            for i in range(len(refs)):
                a = comps[refs[i]]
                if a.locked:
                    continue
                for j in range(i + 1, len(refs)):
                    b = comps[refs[j]]
                    overlap = _bbox_overlap_amount(a, b)
                    if overlap <= 0:
                        continue
                    # Push apart along center-to-center axis
                    d = a.pos.dist(b.pos)
                    if d < 0.1:
                        d = 0.1
                    push = math.sqrt(overlap) + self.clearance
                    dx = (a.pos.x - b.pos.x) / d * push * 0.5
                    dy = (a.pos.y - b.pos.y) / d * push * 0.5
                    if not a.locked:
                        old = Point(a.pos.x, a.pos.y)
                        a.pos.x += dx
                        a.pos.y += dy
                        _update_pad_positions(a, old, a.rotation)
                    if not b.locked:
                        old = Point(b.pos.x, b.pos.y)
                        b.pos.x -= dx
                        b.pos.y -= dy
                        _update_pad_positions(b, old, b.rotation)
                    moved = True
            if not moved:
                break

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
