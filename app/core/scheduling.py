
"""Regras de negócio para agendamentos."""
from datetime import datetime, timedelta
from typing import Optional
from flask import current_app
from ..extensions import db
from ..models.tables import Appointment

def has_conflict(start: datetime, duration_minutes: int, ignore_id: Optional[int] = None) -> bool:
    """Verifica conflito simples: se houver outro agendamento que sobreponha o período."""
    end = start + timedelta(minutes=duration_minutes)
    q = Appointment.query
    if ignore_id:
        q = q.filter(Appointment.id != ignore_id)
    for ap in q.all():
        ap_end = ap.start_time + timedelta(minutes=ap.duration_minutes)
        if not (end <= ap.start_time or start >= ap_end):
            return True
    return False

def create_appointment(name: str, phone: str, start_time: datetime, duration_minutes: int = 30, notes: str = "") -> Appointment:
    if has_conflict(start_time, duration_minutes):
        raise ValueError('Conflito de horário com outro agendamento.')
    ap = Appointment(name=name, phone=phone, start_time=start_time, duration_minutes=duration_minutes, notes=notes)
    db.session.add(ap)
    db.session.commit()
    current_app.logger.info('Agendamento criado: %s - %s', name, start_time.isoformat())
    return ap

def list_appointments(limit: int = 100):
    return Appointment.query.order_by(Appointment.start_time.asc()).limit(limit).all()
