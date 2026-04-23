from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass

class RequirementRecord(Base):
    __tablename__ = "requirements_v2"
    __table_args__ = (UniqueConstraint("project_id", "requirement_id", name="uq_requirements_v2_project_req"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    requirement_id: Mapped[str] = mapped_column(String(64), index=True)
    req_key: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    source_doc: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CodeUnitRecord(Base):
    __tablename__ = "code_units_v2"
    __table_args__ = (UniqueConstraint("project_id", "code_unit_id", name="uq_code_units_v2_project_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    code_unit_id: Mapped[str] = mapped_column(String(64), index=True)
    code_key: Mapped[str] = mapped_column(String(64), index=True)
    file_path: Mapped[str] = mapped_column(String(1024), index=True)
    symbol: Mapped[str] = mapped_column(String(255))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(64), index=True)
    chunk_type: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TraceLinkRecord(Base):
    __tablename__ = "trace_links_v2"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "requirement_id",
            "code_unit_id",
            name="uq_trace_links_v2_project_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    requirement_id: Mapped[str] = mapped_column(String(64), index=True)
    req_key: Mapped[str] = mapped_column(String(64), index=True)
    code_unit_id: Mapped[str] = mapped_column(String(64), index=True)
    code_key: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[float] = mapped_column(Float, index=True)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(32), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@dataclass
class Database:
    engine: object
    SessionLocal: object


def build_database(database_url: str) -> Database:
    engine = create_engine(database_url, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return Database(engine=engine, SessionLocal=session_factory)


def init_db(database: Database) -> None:
    Base.metadata.create_all(bind=database.engine)
