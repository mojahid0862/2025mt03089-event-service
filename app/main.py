"""Event catalogue. Booking inventory belongs exclusively to Booking Service."""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, Integer, String, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    venue: Mapped[str] = mapped_column(String(150))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int] = mapped_column(Integer)


class EventInput(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    venue: str = Field(min_length=1, max_length=150)
    starts_at: datetime
    capacity: int = Field(gt=0, le=100000)

    @field_validator("title", "venue")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value.strip()

    @field_validator("starts_at")
    @classmethod
    def future(cls, value):
        if value.tzinfo is None or value <= datetime.now(timezone.utc):
            raise ValueError("Use a future date with an explicit timezone")
        return value.astimezone(timezone.utc)


class EventOutput(BaseModel):
    model_config = {"from_attributes": True}
    id: str
    title: str
    venue: str
    starts_at: datetime
    capacity: int

    @field_validator("starts_at")
    @classmethod
    def utc_timestamp(cls, value):
        # SQLite drops timezone metadata; all stored values are normalized to UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def create_app(database_url: str | None = None):
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    engine = create_engine(url, pool_pre_ping=True)
    sessions = sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        # Lab bootstrap only. Production requires versioned migration Jobs.
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Campus Event Service", version="1.0.0", lifespan=lifespan)

    @app.get("/health/live")
    def live():
        return {"status": "ok", "service": "event-service"}

    @app.get("/health/ready")
    def ready():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ready"}

    @app.post("/events", response_model=EventOutput, status_code=201)
    def create_event(body: EventInput):
        with sessions.begin() as session:
            event = Event(id=str(uuid4()), **body.model_dump())
            session.add(event)
        return event

    @app.get("/events", response_model=list[EventOutput])
    def list_events(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        with sessions() as session:
            return session.scalars(select(Event).order_by(Event.starts_at, Event.id).offset(offset).limit(limit)).all()

    @app.get("/events/{event_id}", response_model=EventOutput)
    def get_event(event_id: str):
        with sessions() as session:
            event = session.get(Event, event_id)
            if event is None:
                raise HTTPException(404, "Event not found")
            return event

    return app
