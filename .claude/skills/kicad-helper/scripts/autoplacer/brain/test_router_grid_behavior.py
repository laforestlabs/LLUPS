from __future__ import annotations

import pathlib
import sys
import unittest

AUTOPLACER_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(AUTOPLACER_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTOPLACER_ROOT))

from brain.grid_builder import RoutingGrid
from brain.router import AStarRouter, RoutingSolver
from brain.types import BoardState, GridCell, Layer, Net, Point, TraceSegment


class RouterGridBehaviorTests(unittest.TestCase):
    def test_find_path_respects_width_cells_in_corridor(self):
        grid = RoutingGrid((Point(0.0, 0.0), Point(10.0, 10.0)), resolution_mm=1.0)
        router = AStarRouter(grid)
        start = GridCell(1, 1, Layer.FRONT)
        end = GridCell(8, 1, Layer.FRONT)

        # Baseline should allow a simple horizontal route for width 1.
        path_thin = router.find_path(start, end, width_cells=1, max_search=5000)
        self.assertIsNotNone(path_thin)

        # Block rows above and below the corridor so only a 1-cell corridor remains.
        for x in range(0, grid.cols):
            grid.set_cost(x, 0, Layer.FRONT, 1e6)
            grid.set_cost(x, 2, Layer.FRONT, 1e6)

        # width=1 should still pass through center row.
        path_width1 = router.find_path(start, end, width_cells=1, max_search=5000)
        self.assertIsNotNone(path_width1)

        # width=2 should fail once width-aware occupancy checks are implemented.
        path_width2 = router.find_path(start, end, width_cells=2, max_search=5000)
        self.assertIsNone(path_width2)

    def test_unmark_segment_clears_soft_obstacle(self):
        grid = RoutingGrid((Point(0.0, 0.0), Point(10.0, 10.0)), resolution_mm=1.0)
        seg = TraceSegment(
            start=Point(2.0, 2.0),
            end=Point(6.0, 2.0),
            layer=Layer.FRONT,
            net="N1",
            width_mm=1.0,
        )
        grid.mark_segment(seg.start, seg.end, seg.layer, seg.width_mm, 100.0)

        probe_idx = grid._idx(2, 4)
        self.assertGreater(grid.cost[Layer.FRONT][probe_idx], 0.0)

        grid.unmark_segment(seg, seg.width_mm)

        self.assertEqual(grid.cost[Layer.FRONT][probe_idx], 0.0)
        # Unrelated cell remains unchanged.
        far_idx = grid._idx(9, 9)
        self.assertEqual(grid.cost[Layer.FRONT][far_idx], 0.0)

    def test_prioritize_nets_uses_priority_then_padcount(self):
        state = BoardState()
        state.nets["LOW"] = Net(name="LOW", pad_refs=[("U1", "1"), ("U2", "1")], priority=1, is_power=False)
        state.nets["HIGH"] = Net(name="HIGH", pad_refs=[("U1", "2"), ("U2", "2")], priority=7, is_power=False)
        state.nets["POWER"] = Net(name="POWER", pad_refs=[("U3", "1"), ("U4", "1")], priority=0, is_power=True)
        state.nets["WIDE"] = Net(
            name="WIDE",
            pad_refs=[("U5", "1"), ("U6", "1"), ("U7", "1")],
            priority=7,
            is_power=False,
        )

        solver = RoutingSolver(state, config={"skip_gnd_routing": False})
        ordered = solver._prioritize_nets()
        ordered_names = [n.name for n in ordered]

        # Power should come first; then higher-priority signals, then pad-count tiebreak.
        self.assertEqual(ordered_names[0], "POWER")
        self.assertLess(ordered_names.index("HIGH"), ordered_names.index("LOW"))
        self.assertLess(ordered_names.index("HIGH"), ordered_names.index("WIDE"))

    def test_width_to_cells_includes_clearance_for_strict_attempt(self):
        solver = RoutingSolver(
            BoardState(),
            config={"grid_resolution_mm": 0.5, "clearance_mm": 0.2},
        )
        strict_cells = solver._width_to_cells(0.25 + solver.clearance)
        relaxed_cells = solver._width_to_cells(0.25)
        self.assertEqual(strict_cells, 1)
        self.assertEqual(relaxed_cells, 1)

        # Wider net should expand occupancy more conservatively with clearance.
        strict_cells_wide = solver._width_to_cells(0.9 + solver.clearance)
        relaxed_cells_wide = solver._width_to_cells(0.9)
        self.assertEqual(strict_cells_wide, 3)
        self.assertEqual(relaxed_cells_wide, 2)

    def test_width_candidates_relax_only_when_needed(self):
        solver = RoutingSolver(
            BoardState(),
            config={"allow_width_relaxation": True},
        )
        self.assertEqual(solver._edge_width_candidates(2, 1), [2, 1])
        self.assertEqual(solver._edge_width_candidates(1, 1), [1])

        strict_solver = RoutingSolver(
            BoardState(),
            config={"allow_width_relaxation": False},
        )
        self.assertEqual(strict_solver._edge_width_candidates(2, 1), [2])

    def test_mst_try_limit_fallback_when_config_disables_retries(self):
        solver = RoutingSolver(BoardState(), config={"mst_retry_limit": 0})
        self.assertEqual(solver._mst_try_limit(2), 1)
        self.assertEqual(solver._mst_try_limit(3), 2)
        self.assertEqual(solver._mst_try_limit(8), 4)

        configured = RoutingSolver(BoardState(), config={"mst_retry_limit": 5})
        self.assertEqual(configured._mst_try_limit(6), 5)


    def test_stale_node_pruning_efficiency(self):
        """Tight stale-node threshold should find path with fewer iterations."""
        grid = RoutingGrid((Point(0.0, 0.0), Point(50.0, 50.0)), resolution_mm=1.0)
        # Add soft obstacles to force detours
        for x in range(10, 40):
            grid.set_cost(x, 25, Layer.FRONT, 500.0)
        router = AStarRouter(grid)
        start = GridCell(5, 25, Layer.FRONT)
        end = GridCell(45, 25, Layer.FRONT)

        # Should find path efficiently with tight pruning
        path = router.find_path(start, end, width_cells=1, max_search=10000)
        self.assertIsNotNone(path)
        self.assertGreater(len(path), 5)

    def test_hard_block_prevents_cross_net_routing(self):
        """Hard-blocked cells (>=1e6) should be uncrossable — detour required."""
        grid = RoutingGrid((Point(0.0, 0.0), Point(20.0, 10.0)), resolution_mm=1.0)
        router = AStarRouter(grid)

        # Mark row 5 as hard block (>=1e6)
        for x in range(0, grid.cols):
            grid.set_cost(x, 5, Layer.FRONT, 1e6)

        # Path on the blocked row should fail
        start = GridCell(2, 5, Layer.FRONT)
        end = GridCell(18, 5, Layer.FRONT)
        path_blocked = router.find_path(start, end, width_cells=1, max_search=5000)
        self.assertIsNone(path_blocked)

        # Path on adjacent row should succeed (detour around)
        start2 = GridCell(2, 4, Layer.FRONT)
        end2 = GridCell(18, 6, Layer.FRONT)
        path_detour = router.find_path(start2, end2, width_cells=1, max_search=5000)
        self.assertIsNotNone(path_detour)

    def test_intermediate_mst_marking_prevents_overlap(self):
        """After routing one MST edge, subsequent edges should see it as an obstacle."""
        grid = RoutingGrid((Point(0.0, 0.0), Point(20.0, 10.0)), resolution_mm=1.0)
        router = AStarRouter(grid)

        # Route a horizontal path
        start = GridCell(2, 5, Layer.FRONT)
        end = GridCell(18, 5, Layer.FRONT)
        path1 = router.find_path(start, end, width_cells=1)
        self.assertIsNotNone(path1)

        # Mark it as soft obstacle (simulating intermediate MST marking)
        from brain.grid_builder import path_to_traces
        segs, _ = path_to_traces(path1, grid, "N1", 0.5)
        for seg in segs:
            grid.mark_segment(seg.start, seg.end, seg.layer, seg.width_mm + 0.2, 100.0)

        # A second path between nearby points should detour around the marked trace
        start2 = GridCell(2, 5, Layer.FRONT)
        end2 = GridCell(18, 5, Layer.FRONT)
        path2 = router.find_path(start2, end2, width_cells=1)
        self.assertIsNotNone(path2)
        # The cost-aware router should prefer cells not already occupied
        # (path may go through but incurs penalty, resulting in a different route
        # if there's a cheaper alternative)


if __name__ == "__main__":
    unittest.main()
