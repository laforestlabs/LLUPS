"""SQLite database layer for experiment tracking."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text,
    create_engine, event,
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


class ExperimentRun(Base):
    """Top-level experiment run (one per autoexperiment invocation)."""
    __tablename__ = "experiment_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String(20), default="idle")  # idle, running, done, error
    pcb_file = Column(String(500))
    total_rounds = Column(Integer, default=0)
    completed_rounds = Column(Integer, default=0)
    best_score = Column(Float, default=0.0)
    config_json = Column(Text, default="{}")
    source_jsonl = Column(String(500))  # original JSONL file if imported
    notes = Column(Text, default="")


class Round(Base):
    """One round within an experiment run."""
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(Integer, nullable=False, index=True)
    round_num = Column(Integer, nullable=False)
    seed = Column(Integer)
    mode = Column(String(20))  # minor, major, explore, elite
    score = Column(Float, default=0.0)
    kept = Column(Boolean, default=False)
    # Score breakdown
    placement_score = Column(Float)
    route_completion = Column(Float)
    trace_efficiency = Column(Float)
    via_score = Column(Float)
    courtyard_overlap = Column(Float)
    board_containment = Column(Float)
    # DRC
    drc_shorts = Column(Integer, default=0)
    drc_unconnected = Column(Integer, default=0)
    drc_clearance = Column(Integer, default=0)
    drc_courtyard = Column(Integer, default=0)
    drc_total = Column(Integer, default=0)
    # Timing
    duration_s = Column(Float)
    placement_ms = Column(Float)
    routing_ms = Column(Float)
    # Routing
    nets_routed = Column(Integer)
    failed_net_names_json = Column(Text, default="[]")
    # Config delta
    config_delta_json = Column(Text, default="{}")
    # Board dimensions (for future board-size search)
    board_width_mm = Column(Float)
    board_height_mm = Column(Float)
    # Details string
    details = Column(Text)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def config_delta(self) -> dict:
        return json.loads(self.config_delta_json or "{}")

    @property
    def failed_net_names(self) -> list:
        return json.loads(self.failed_net_names_json or "[]")


class Preset(Base):
    """Saved configuration preset."""
    __tablename__ = "presets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True)
    config_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, default="")


class Database:
    """Manages SQLite connection and provides query helpers."""

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = self._default_path()
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        # Enable WAL mode for concurrent reads
        @event.listens_for(self.engine, "connect")
        def _set_wal(dbapi_conn, _rec):
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(self.engine)
        self._Session = sessionmaker(bind=self.engine)

    @staticmethod
    def _default_path() -> Path:
        return Path(__file__).resolve().parent.parent / ".experiments" / "llups.db"

    def session(self) -> Session:
        return self._Session()

    # -- Experiment runs ---------------------------------------------------

    def create_experiment(self, name: str, pcb_file: str = "",
                          total_rounds: int = 0, config: dict | None = None,
                          source_jsonl: str = "") -> ExperimentRun:
        with self.session() as s:
            exp = ExperimentRun(
                name=name,
                pcb_file=pcb_file,
                total_rounds=total_rounds,
                config_json=json.dumps(config or {}),
                source_jsonl=source_jsonl,
            )
            s.add(exp)
            s.commit()
            s.refresh(exp)
            return exp

    def get_experiments(self) -> list[ExperimentRun]:
        with self.session() as s:
            return s.query(ExperimentRun).order_by(ExperimentRun.created_at.desc()).all()

    def get_experiment(self, exp_id: int) -> ExperimentRun | None:
        with self.session() as s:
            return s.get(ExperimentRun, exp_id)

    def update_experiment(self, exp_id: int, **kwargs) -> None:
        with self.session() as s:
            exp = s.get(ExperimentRun, exp_id)
            if exp:
                for k, v in kwargs.items():
                    setattr(exp, k, v)
                s.commit()

    # -- Rounds ------------------------------------------------------------

    def add_round(self, experiment_id: int, data: dict) -> Round:
        with self.session() as s:
            r = Round(
                experiment_id=experiment_id,
                round_num=data.get("round_num", 0),
                seed=data.get("seed"),
                mode=data.get("mode"),
                score=data.get("score", 0),
                kept=data.get("kept", False),
                placement_score=data.get("placement_score"),
                route_completion=data.get("route_completion"),
                trace_efficiency=data.get("trace_efficiency"),
                via_score=data.get("via_score"),
                courtyard_overlap=data.get("courtyard_overlap"),
                board_containment=data.get("board_containment"),
                drc_shorts=data.get("drc_shorts", 0),
                drc_unconnected=data.get("drc_unconnected", 0),
                drc_clearance=data.get("drc_clearance", 0),
                drc_courtyard=data.get("drc_courtyard", 0),
                drc_total=data.get("drc_total", 0),
                duration_s=data.get("duration_s"),
                placement_ms=data.get("placement_ms"),
                routing_ms=data.get("routing_ms"),
                nets_routed=data.get("nets_routed"),
                failed_net_names_json=json.dumps(data.get("failed_net_names", [])),
                config_delta_json=json.dumps(data.get("config_delta", {})),
                board_width_mm=data.get("board_width_mm"),
                board_height_mm=data.get("board_height_mm"),
                details=data.get("details"),
            )
            s.add(r)
            s.commit()
            s.refresh(r)
            return r

    def get_rounds(self, experiment_id: int) -> list[Round]:
        with self.session() as s:
            return (s.query(Round)
                    .filter(Round.experiment_id == experiment_id)
                    .order_by(Round.round_num)
                    .all())

    def get_round_dicts(self, experiment_id: int) -> list[dict]:
        """Return rounds as plain dicts for charting."""
        rounds = self.get_rounds(experiment_id)
        result = []
        for r in rounds:
            result.append({
                "round_num": r.round_num,
                "seed": r.seed,
                "mode": r.mode,
                "score": r.score,
                "kept": r.kept,
                "placement_score": r.placement_score,
                "route_completion": r.route_completion,
                "via_score": r.via_score,
                "drc_shorts": r.drc_shorts,
                "drc_total": r.drc_total,
                "duration_s": r.duration_s,
                "config_delta": r.config_delta,
                "details": r.details,
            })
        return result

    # -- Presets ------------------------------------------------------------

    def save_preset(self, name: str, config: dict, notes: str = "") -> Preset:
        with self.session() as s:
            existing = s.query(Preset).filter(Preset.name == name).first()
            if existing:
                existing.config_json = json.dumps(config)
                existing.notes = notes
                s.commit()
                s.refresh(existing)
                return existing
            p = Preset(name=name, config_json=json.dumps(config), notes=notes)
            s.add(p)
            s.commit()
            s.refresh(p)
            return p

    def get_presets(self) -> list[Preset]:
        with self.session() as s:
            return s.query(Preset).order_by(Preset.name).all()

    def load_preset(self, name: str) -> dict | None:
        with self.session() as s:
            p = s.query(Preset).filter(Preset.name == name).first()
            return json.loads(p.config_json) if p else None

    def delete_preset(self, name: str) -> bool:
        with self.session() as s:
            p = s.query(Preset).filter(Preset.name == name).first()
            if p:
                s.delete(p)
                s.commit()
                return True
            return False
