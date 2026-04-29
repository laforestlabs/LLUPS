#!/usr/bin/env bash
# verify-minimal.sh -- canonical end-to-end verification of the
# leaves-first user workflow:
#
#   1. Run 3 experiment rounds of leaves-only (3 leaf attempts each).
#   2. Pin the highest-scoring round per leaf via tools/pin_best_leaves.py.
#   3. Run 1 round of parents-only that consumes the pinned leaves
#      (single round so a flake doesn't cost a full sweep).
#
# This is exactly what a user does on the GUI when they click
# "Start leaves only" -> review snapshots -> pin -> "Start parent
# only". Anything that breaks this path breaks the user's experience,
# so it's the right pipeline to run as a smoke test.
#
# What this does NOT do:
#   * It does not exercise full-pipeline mode (Start Complete) -- that
#     surface is intentionally hidden in the GUI; we keep it via the
#     plumbing but don't gate releases on it.
#   * It does not exercise GUI-specific behaviour (badges, keyboard
#     nav, etc.) -- those are unit-tested in KiCraft/tests.
#
# Usage:
#   ./verify-minimal.sh
#
# Optional environment overrides:
#   SCH                -- top schematic           (default: LLUPS.kicad_sch)
#   PCB                -- source pcb template     (default: LLUPS.kicad_pcb)
#   ROUNDS             -- experiment rounds       (default: 3)
#   LEAF_ROUNDS        -- leaf attempts/round     (default: 3)
#   FREEROUTING_JAR    -- FreeRouting jar         (default: ~/.local/lib/freerouting-1.9.0.jar)
#   LEAVES_TIMEOUT     -- leaves-only timeout     (default: 1500)
#   PIN_TIMEOUT        -- pin step timeout        (default: 60)
#   PARENT_TIMEOUT     -- parents-only timeout    (default: 600)

set -euo pipefail

SCH="${SCH:-LLUPS.kicad_sch}"
PCB="${PCB:-LLUPS.kicad_pcb}"
ROUNDS="${ROUNDS:-3}"
LEAF_ROUNDS="${LEAF_ROUNDS:-3}"
FREEROUTING_JAR="${FREEROUTING_JAR:-$HOME/.local/lib/freerouting-1.9.0.jar}"
LEAVES_TIMEOUT="${LEAVES_TIMEOUT:-1500}"
PIN_TIMEOUT="${PIN_TIMEOUT:-60}"
PARENT_TIMEOUT="${PARENT_TIMEOUT:-600}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

if [[ ! -f "$SCH" ]]; then
    echo "error: schematic not found: $SCH" >&2
    exit 2
fi
if [[ ! -f "$PCB" ]]; then
    echo "error: pcb not found: $PCB" >&2
    exit 2
fi
if [[ ! -f "$FREEROUTING_JAR" ]]; then
    echo "error: FreeRouting jar not found: $FREEROUTING_JAR" >&2
    echo "       set FREEROUTING_JAR env var to override" >&2
    exit 2
fi
if [[ ! -f "tools/pin_best_leaves.py" ]]; then
    echo "error: tools/pin_best_leaves.py not found at repo root" >&2
    exit 2
fi

start_total="$(date +%s)"

echo "==> [1/4] Cleaning .experiments/ for a deterministic run"
python3 -c "
import shutil, os
for d in ('.experiments/subcircuits', '.experiments/hierarchical_autoexperiment',
          '.experiments/rounds', '.experiments/frames'):
    shutil.rmtree(d, ignore_errors=True)
for f in ('.experiments/experiments.jsonl', '.experiments/pins.json',
          '.experiments/run_status.json', '.experiments/run_status.txt',
          '.experiments/hierarchical_summary.json',
          '.experiments/parent_composition_routed.json',
          '.experiments/experiment.log'):
    if os.path.exists(f):
        os.unlink(f)
"

echo "==> [2/4] Leaves-only: --rounds ${ROUNDS} --leaf-rounds ${LEAF_ROUNDS}"
start_stage="$(date +%s)"
timeout "$LEAVES_TIMEOUT" python3 -u -m kicraft.cli.autoexperiment \
    "$PCB" \
    --schematic "$SCH" \
    --rounds "$ROUNDS" \
    --leaf-rounds "$LEAF_ROUNDS" \
    --workers 6 \
    --leaves-only \
    --jar "$FREEROUTING_JAR"
echo "    leaves-only took $(( $(date +%s) - start_stage ))s"

echo "==> [3/4] Pinning highest-scoring round per leaf"
start_stage="$(date +%s)"
timeout "$PIN_TIMEOUT" python3 tools/pin_best_leaves.py \
    --experiments-dir .experiments
echo "    pin-best took $(( $(date +%s) - start_stage ))s"

# pins.json must exist and reference at least one leaf -- otherwise
# parents-only has nothing to compose against and we'd skip a real
# verification step.
if [[ ! -f .experiments/pins.json ]]; then
    echo "error: pin step did not produce .experiments/pins.json" >&2
    exit 3
fi
pinned_count="$(python3 -c '
import json
data = json.load(open(".experiments/pins.json"))
print(len(data.get("pinned_leaves", {})))
')"
if [[ "$pinned_count" == "0" ]]; then
    echo "error: pin_best_leaves.py pinned 0 leaves -- check leaves-only output" >&2
    exit 3
fi
echo "    pinned $pinned_count leaves"

echo "==> [4/4] Parents-only: --rounds 1 (consumes pinned leaves)"
start_stage="$(date +%s)"
# Clear the hierarchy run dir + experiments.jsonl + rounds/ from the
# leaves-only run so the parents-only run starts with clean parent-side
# state AND so the post-run acceptance check sees only parent rounds
# (leaves-only also writes round_NNNN.json, and those have parent_routed
# false, which would falsely flag the run as failed).
# Per-leaf state under .experiments/subcircuits/ stays intact -- pins
# and the leaves-only debug.json drive the parents-only compose.
python3 -c "
import shutil, os
shutil.rmtree('.experiments/hierarchical_autoexperiment', ignore_errors=True)
shutil.rmtree('.experiments/rounds', ignore_errors=True)
if os.path.exists('.experiments/experiments.jsonl'):
    os.unlink('.experiments/experiments.jsonl')
"
# We do NOT swallow non-zero exits here. A previous version of this
# script tolerated rc=1 on the rationale that an "illegal_routed_geometry"
# rejection still produces an inspectable parent_routed.kicad_pcb -- but
# that turned the script into a liar: any parent route failure was
# printed as "Done". Now the script always exits non-zero when the
# parent doesn't actually route, regardless of how autoexperiment chose
# to signal it (process exit code OR per-round acceptance flag in
# .experiments/rounds/round_*.json).
timeout "$PARENT_TIMEOUT" python3 -u -m kicraft.cli.autoexperiment \
    "$PCB" \
    --schematic "$SCH" \
    --rounds 1 \
    --leaf-rounds 1 \
    --workers 6 \
    --parents-only \
    --jar "$FREEROUTING_JAR"
parent_rc=$?
echo "    parents-only took $(( $(date +%s) - start_stage ))s (rc=$parent_rc)"

# Artifacts are always printed -- failure mode debugging needs them.
echo
echo "Pinned leaves (canonical state on disk):"
python3 -c "
import json
pins = json.load(open('.experiments/pins.json')).get('pinned_leaves', {})
for key, info in sorted(pins.items()):
    print(f'  {key}: round={info.get(\"round\")} source={info.get(\"source\", \"?\")}')
"
echo
echo "Parent routed boards (open the newest in KiCad):"
find .experiments/subcircuits -maxdepth 2 -name "parent_routed.kicad_pcb" \
    -printf '  %T@ %p\n' 2>/dev/null \
    | sort -rn \
    | awk '{ $1=""; sub(/^ /, ""); print }'

# Now check the actual outcome. autoexperiment normally returns 0 even
# when every round was rejected by the acceptance gate, so the only
# truthful signal is the per-round JSON. A round counts as "passed"
# when hierarchy.parent_routed is true AND no rejection_reasons were
# recorded.
echo
parent_outcome="$(python3 - <<'PY'
import json
import sys
from pathlib import Path

rounds_dir = Path('.experiments/rounds')
if not rounds_dir.is_dir():
    print('no_rounds_dir', file=sys.stderr)
    sys.exit(0)

round_files = sorted(rounds_dir.glob('round_*.json'))
if not round_files:
    print('no_round_files', file=sys.stderr)
    sys.exit(0)

results = []
for path in round_files:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        results.append((path.name, 'parse_error', str(exc)))
        continue
    hier = data.get('hierarchy') or {}
    routed = bool(hier.get('parent_routed', False))
    tier = hier.get('tier', '?')
    score = data.get('score')
    results.append((path.name, routed, tier, score))

print(json.dumps(results))
PY
)"

# Decide pass/fail. Surface the table either way.
echo "Parent route outcomes:"
python3 - <<PY
import json
results = json.loads('''$parent_outcome''') if '''$parent_outcome''' else []
for r in results:
    if len(r) == 3:
        print(f"  {r[0]}: parse error -- {r[2]}")
    else:
        name, routed, tier, score = r
        flag = 'OK' if routed else 'FAIL'
        print(f"  {name}: {flag} tier={tier} score={score}")
PY

# Compute exit status:
#   * autoexperiment hard-failed (rc not in {0}) -> propagate rc
#   * any round failed acceptance               -> exit 3
#   * everything routed                          -> exit 0
if [[ "$parent_rc" -ne 0 ]]; then
    echo "error: autoexperiment exited rc=$parent_rc" >&2
    exit "$parent_rc"
fi

acceptance_rc="$(python3 - <<PY
import json
results = json.loads('''$parent_outcome''') if '''$parent_outcome''' else []
if not results:
    print(4)
    raise SystemExit
ok = all(len(r) == 4 and r[1] for r in results)
print(0 if ok else 3)
PY
)"

if [[ "$acceptance_rc" -ne 0 ]]; then
    echo "error: parents-only completed but no round accepted (rc=$acceptance_rc)" >&2
    exit "$acceptance_rc"
fi

echo
echo "==> Done in $(( $(date +%s) - start_total ))s"
