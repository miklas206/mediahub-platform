import asyncio
import json

from sqlalchemy import select

from mediahub.db import Activity, Event, Notification


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

    def record(
        self,
        kind: str,
        source: str,
        message: str,
        severity: str = "info",
        notify: bool = False,
    ):
        with self.sessions.begin() as db:
            event = Event(type=kind, source=source, message=message, severity=severity, payload={})
            db.add(event)
            db.flush()
            db.add(Activity(event_id=event.id))
            if notify:
                db.add(Notification(event_id=event.id, state="pending"))
            data = {
                "id": event.id,
                "timestamp": event.created_at,
                "source": source,
                "event": kind,
                "message": message,
                "severity": severity,
            }
        self.publish(kind, data)
        return data

    def notifications(self, pending_only=True, limit=25):
        with self.sessions() as db:
            query = (
                select(Notification, Event)
                .join(Event, Event.id == Notification.event_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
            if pending_only:
                query = query.where(Notification.state == "pending")
            rows = db.execute(query).all()
            return [
                {
                    "id": notification.id,
                    "timestamp": event.created_at,
                    "event": event.type,
                    "source": event.source,
                    "severity": event.severity,
                    "message": event.message,
                    "state": notification.state,
                }
                for notification, event in rows
            ]

    def read_notification(self, notification_id):
        with self.sessions.begin() as db:
            row = db.get(Notification, notification_id)
            if row is None:
                return False
            row.state = "read"
        return True

    def read_notifications(self, *, event_type=None, source=None):
        """Resolve matching pending notifications without deleting their audit events."""

        with self.sessions.begin() as db:
            query = (
                select(Notification)
                .join(Event, Event.id == Notification.event_id)
                .where(Notification.state == "pending")
            )
            if event_type:
                query = query.where(Event.type == event_type)
            if source:
                query = query.where(Event.source == source)
            rows = db.scalars(query).all()
            for row in rows:
                row.state = "read"
            return len(rows)

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
