"""Modèle de données.

Principes :
- Identifiants internes = UUID aléatoires, jamais dérivés d'informations personnelles.
- AUCUNE colonne pour nom / téléphone / adresse / n° national de la patiente.
- Les champs médicaux sont stockés en lignes (ExtractedField) : chaque champ porte
  sa valeur, son statut, sa confiance, sa source et son historique de corrections.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Enum as SAEnum, Float, ForeignKey, Index,
                        Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stocke en UTC et relit TOUJOURS une date avec fuseau (SQLite les perd sinon)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def _enum(e):  # stocké en VARCHAR -> portable SQLite / PostgreSQL
    return SAEnum(e, native_enum=False, length=40, validate_strings=True)


# --------------------------------------------------------------------------- énumérations
class RecordStatus(str, enum.Enum):
    """Cycle de vie (identifiants ASCII ; libellés FR dans l'UI)."""
    CAPTURE = "CAPTURE"
    EN_ATTENTE_IA = "EN_ATTENTE_IA"
    TRAITE_IA = "TRAITE_IA"
    A_REVISER = "A_REVISER"
    VALIDE = "VALIDE"
    PATIENTE_LIEE = "PATIENTE_LIEE"
    ENREGISTRE = "ENREGISTRE"
    SYNCHRONISE = "SYNCHRONISE"
    # états d'échec
    ECHEC_TRAITEMENT = "ECHEC_TRAITEMENT"
    ECHEC_SYNCHRO = "ECHEC_SYNCHRO"
    DOUBLON_SUSPECT = "DOUBLON_SUSPECT"
    REVISION_MANUELLE_REQUISE = "REVISION_MANUELLE_REQUISE"
    ANNULE = "ANNULE"


class FieldStatus(str, enum.Enum):
    CONNU = "CONNU"
    INCONNU = "INCONNU"
    NON_FOURNI = "NON_FOURNI"
    ILLISIBLE = "ILLISIBLE"
    NON_APPLICABLE = "NON_APPLICABLE"
    A_REVISER = "A_REVISER"


class FieldSource(str, enum.Enum):
    IA = "IA"
    SAGE_FEMME = "SAGE_FEMME"
    SYSTEME = "SYSTEME"


class InboundStatus(str, enum.Enum):
    RECU = "RECU"          # persisté, pas encore traité
    EN_COURS = "EN_COURS"  # réservé par UN traitement (tâche de fond du webhook OU worker)
    TRAITE = "TRAITE"
    IGNORE = "IGNORE"
    ECHEC = "ECHEC"        # sera retenté par le worker


class OutboundStatus(str, enum.Enum):
    EN_ATTENTE = "EN_ATTENTE"
    ENVOI_EN_COURS = "ENVOI_EN_COURS"   # réservé par UN envoi (anti double envoi)
    ENVOYE = "ENVOYE"
    ECHEC = "ECHEC"        # abandon après N tentatives


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    SUPERVISEUR = "SUPERVISEUR"
    SAGE_FEMME = "SAGE_FEMME"


# --------------------------------------------------------------------------- acteurs
class Midwife(Base):
    __tablename__ = "midwives"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # wa_id de la SAGE-FEMME (nécessaire pour lui répondre) — jamais celui d'une patiente
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(5), default="fr")
    # état conversationnel courant (utilisé au bloc 4), JSON sérialisé
    conversation_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    midwife_id: Mapped[str] = mapped_column(ForeignKey("midwives.id"), index=True)
    # code aléatoire attribué par la sage-femme et écrit sur le registre
    code: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    records: Mapped[list["Record"]] = relationship(back_populates="patient")


# --------------------------------------------------------------------------- dossier / visite
class Record(Base):
    """Un registre photographié (1..n pages) = une visite / un document."""
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    midwife_id: Mapped[str] = mapped_column(ForeignKey("midwives.id"), index=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    status: Mapped[RecordStatus] = mapped_column(_enum(RecordStatus), default=RecordStatus.CAPTURE, index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_open: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # « Je ne sais pas » à la liaison patiente : reste VALIDE et non rattaché (bloc 4)
    link_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    last_page_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    patient: Mapped[Patient | None] = relationship(back_populates="records")
    pages: Mapped[list["Page"]] = relationship(back_populates="record", order_by="Page.page_number",
                                               cascade="all, delete-orphan")
    fields: Mapped[list["ExtractedField"]] = relationship(back_populates="record", cascade="all, delete-orphan")
    events: Mapped[list["RecordEvent"]] = relationship(back_populates="record", order_by="RecordEvent.id",
                                                       cascade="all, delete-orphan")


class Page(Base):
    """Image d'origine (chiffrée sur disque) liée au dossier."""
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("record_id", "page_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)   # nom de fichier opaque
    sha256: Mapped[str] = mapped_column(String(64), index=True)         # intégrité + détection doublon
    mime_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime())  # horodatage WhatsApp (heure de prise)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    # contrôle qualité de l'IA (JSON : {"ok", "raisons", "flou", "luminosite"...}) ; None = pas encore lue
    quality_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # « Reprendre la photo » (bloc 4) : l'ancienne page est conservée mais marquée remplacée
    replaced: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    replaces_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON : clés des identifiants NON enregistrés pour cette page (ex. ["nom_parturiente"]),
    # pour dire à la sage-femme ce qui a été volontairement écarté — jamais la valeur
    identifiers_excluded: Mapped[str | None] = mapped_column(Text, nullable=True)

    record: Mapped[Record] = relationship(back_populates="pages")


class ExtractedField(Base):
    """Valeur d'un champ du schéma registre, versionnée (is_current)."""
    __tablename__ = "extracted_fields"
    __table_args__ = (Index("ix_field_current", "record_id", "field_key", "is_current"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), index=True)
    section: Mapped[str] = mapped_column(String(40))
    field_key: Mapped[str] = mapped_column(String(80))
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON (nombre, texte, liste...)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)     # ce que l'IA a lu
    # JSON {"candidates": [...], "flags": [...]} : lectures concurrentes et contrôles échoués (bloc 4)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[FieldStatus] = mapped_column(_enum(FieldStatus))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[FieldSource] = mapped_column(_enum(FieldSource))
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    record: Mapped[Record] = relationship(back_populates="fields")


class RecordEvent(Base):
    """Journal d'audit de toutes les transitions d'état."""
    __tablename__ = "record_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(40))   # "system", "ia", "midwife:<id>", "staff:<id>"
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    record: Mapped[Record] = relationship(back_populates="events")


# --------------------------------------------------------------------------- files d'attente
class InboundMessage(Base):
    """Boîte de réception idempotente : chaque wamid n'est traité qu'une fois.

    On ne stocke PAS le payload brut (il contient le nom de profil WhatsApp et
    d'éventuelles légendes de photo pouvant contenir des identifiants).
    """
    __tablename__ = "inbound_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True)
    wa_from: Mapped[str] = mapped_column(String(32), index=True)
    msg_type: Mapped[str] = mapped_column(String(20))
    wa_timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)            # texte / id de réponse interactive
    status: Mapped[InboundStatus] = mapped_column(_enum(InboundStatus), default=InboundStatus.RECU, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class OutboundMessage(Base):
    """Outbox : un message n'est jamais perdu si l'envoi échoue (réseau coupé)."""
    __tablename__ = "outbound_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    to_wa_id: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[OutboundStatus] = mapped_column(_enum(OutboundStatus), default=OutboundStatus.EN_ATTENTE, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


# --------------------------------------------------------------------------- synchronisation
class SystemFlag(Base):
    """Drapeaux système clé/valeur (ex. "reseau_central" = "on" / "off" pour la démo)."""
    __tablename__ = "system_flags"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(80))


class CentralRecord(Base):
    """Serveur central SIMULÉ (ministère) : reçoit les dossiers anonymisés synchronisés."""
    __tablename__ = "central_records"
    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)   # idempotent par dossier
    payload_json: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)


# --------------------------------------------------------------------------- accès restreint
class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    label: Mapped[str] = mapped_column(String(80))
    role: Mapped[Role] = mapped_column(_enum(Role))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    midwife_id: Mapped[str | None] = mapped_column(ForeignKey("midwives.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AccessLog(Base):
    __tablename__ = "access_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staff_id: Mapped[str] = mapped_column(ForeignKey("staff.id"))
    record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    page_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    allowed: Mapped[bool] = mapped_column(Boolean)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
