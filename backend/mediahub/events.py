import asyncio
import json

from sqlalchemy import select

from mediahub.db import Activity, Event


class EventBus:
    def __init__(self, sessions):
        self.sessions = sessions
        self.subscribers: set[asyncio.Queue] = set()

    def publish(self, kind: str, data: dict):
        envelope = {"type": kind, "data": data}
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()  # bounded live stream; activity remains in SQLite
            queue.put_nowait(envelope)

    def record(self, kind: str, source: str, message: str, severity: str = "info"):
        with self.sessions.begin() as db:
            event = Event(type=kind, source=source, message=message, severity=severity, payload={})
            db.add(event)
            db.flush()
            db.add(Activity(event_id=event.id))
            data = {
                "id": event.id,
                "timestamp": event.created_at,
                "source": source,
                "event": kind,
                "message": message,
                "severity": severity,
            }
        self.publish(kind, data)

    def activity(self, limit: int = 50):
        with self.sessions() as db:
            events = db.scalars(select(Event).order_by(Event.created_at.desc()).limit(limit)).all()
            return [
                {
                    "id": e.id,
                    "timestamp": e.created_at,
                    "source": e.source,
                    "event": e.type,
                    "message": e.message,
                    "severity": e.severity,
                }
                for e in events
            ]

    @staticmethod
    def encode(event: dict) -> str:
        return "event: " + event["type"] + "\ndata: " + json.dumps(event["data"]) + "\n\n"
