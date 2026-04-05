"""DRC marker analysis check."""
import pcbnew
from .base import LayoutCheck, CheckResult, Issue


class DRCCheck(LayoutCheck):
    name = "drc_markers"
    display_name = "DRC Violations"
    weight = 0.20

    def run(self, board, config: dict) -> CheckResult:
        markers = list(board.Markers())
        issues = []
        errors = 0
        warnings = 0
        exclusions = 0

        for marker in markers:
            pos = marker.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            rc = marker.GetRCItem()
            msg = rc.GetErrorMessage() if rc else "Unknown"
            sev = marker.GetSeverity()

            if sev == 0:
                errors += 1
                issues.append(Issue("error", msg, {"x": round(x, 2), "y": round(y, 2)}))
            elif sev == 1:
                warnings += 1
                issues.append(Issue("warning", msg, {"x": round(x, 2), "y": round(y, 2)}))
            else:
                exclusions += 1

        score = max(0, 100 - errors * 20 - warnings * 5)

        caveat = ""
        if not markers:
            caveat = "No DRC markers found -- run DRC in KiCad and save before scoring for accurate results"

        return CheckResult(
            score=score,
            issues=issues,
            metrics={
                "errors": errors,
                "warnings": warnings,
                "exclusions": exclusions,
                "total_markers": len(markers),
                "caveat": caveat,
            },
            summary=caveat if caveat else f"{errors} errors, {warnings} warnings, {exclusions} exclusions",
        )
