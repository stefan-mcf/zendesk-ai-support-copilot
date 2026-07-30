from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, String, Text, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from copilot.domain import (
    AuditEvent,
    EngineeringHandoff,
    KnowledgeDocument,
    Suggestion,
    SupportCase,
)
from copilot.retrieval import chunk_document
from copilot.storage import Store


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "knowledge_documents"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class CaseRow(Base):
    __tablename__ = "support_cases"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ChunkRow(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(80), index=True)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(128))


class SuggestionRow(Base):
    __tablename__ = "suggestions"
    case_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class HandoffRow(Base):
    __tablename__ = "engineering_handoffs"
    case_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider_ticket_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuditRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class PostgresStore(Store):
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> "PostgresStore":
        return cls(create_async_engine(url, pool_pre_ping=True))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def seed(
        self,
        documents: Iterable[KnowledgeDocument],
        cases: Iterable[SupportCase],
    ) -> None:
        document_list = list(documents)
        case_list = list(cases)
        chunks = [chunk for item in document_list for chunk in chunk_document(item)]
        async with self.session() as session, session.begin():
            if document_list:
                await session.execute(
                    insert(DocumentRow)
                    .values(
                        [
                            {
                                "id": item.id,
                                "payload": item.model_dump(mode="json"),
                            }
                            for item in document_list
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )
            if chunks:
                await session.execute(
                    insert(ChunkRow)
                    .values(
                        [
                            {
                                "id": chunk.id,
                                "document_id": chunk.document_id,
                                "text": chunk.text,
                                "embedding": chunk.vector,
                            }
                            for chunk in chunks
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )
            if case_list:
                await session.execute(
                    insert(CaseRow)
                    .values(
                        [
                            {
                                "id": item.id,
                                "subject": item.subject,
                                "body": item.body,
                                "payload": item.model_dump(mode="json"),
                            }
                            for item in case_list
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["id"])
                )

    async def replace_seed(
        self,
        documents: Iterable[KnowledgeDocument],
        cases: Iterable[SupportCase],
    ) -> None:
        document_list = list(documents)
        case_list = list(cases)
        async with self.session() as session, session.begin():
            await session.execute(delete(HandoffRow))
            await session.execute(delete(SuggestionRow))
            await session.execute(delete(AuditRow))
            await session.execute(delete(CaseRow))
            await session.execute(delete(ChunkRow))
            await session.execute(delete(DocumentRow))
            session.add_all(
                [
                    DocumentRow(id=item.id, payload=item.model_dump(mode="json"))
                    for item in document_list
                ]
            )
            session.add_all(
                [
                    ChunkRow(
                        id=chunk.id,
                        document_id=chunk.document_id,
                        text=chunk.text,
                        embedding=chunk.vector,
                    )
                    for item in document_list
                    for chunk in chunk_document(item)
                ]
            )
            session.add_all(
                [
                    CaseRow(
                        id=item.id,
                        subject=item.subject,
                        body=item.body,
                        payload=item.model_dump(mode="json"),
                    )
                    for item in case_list
                ]
            )

    async def list_cases(self) -> list[SupportCase]:
        async with self.session() as session:
            rows = (await session.scalars(select(CaseRow).order_by(CaseRow.id))).all()
            return [SupportCase.model_validate(row.payload) for row in rows]

    async def get_case(self, case_id: str) -> SupportCase | None:
        async with self.session() as session:
            row = await session.get(CaseRow, case_id)
            return SupportCase.model_validate(row.payload) if row else None

    async def upsert_case(self, case: SupportCase) -> None:
        async with self.session() as session, session.begin():
            await session.execute(
                insert(CaseRow)
                .values(
                    id=case.id,
                    subject=case.subject,
                    body=case.body,
                    payload=case.model_dump(mode="json"),
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "subject": case.subject,
                        "body": case.body,
                        "payload": case.model_dump(mode="json"),
                    },
                )
            )

    async def save_suggestion(self, suggestion: Suggestion) -> None:
        async with self.session() as session, session.begin():
            await session.merge(
                SuggestionRow(
                    case_id=suggestion.case_id,
                    payload=suggestion.model_dump(mode="json"),
                )
            )

    async def get_suggestion(self, case_id: str) -> Suggestion | None:
        async with self.session() as session:
            row = await session.get(SuggestionRow, case_id)
            return Suggestion.model_validate(row.payload) if row else None

    async def save_handoff(self, handoff: EngineeringHandoff) -> None:
        async with self.session() as session, session.begin():
            await session.execute(
                insert(HandoffRow)
                .values(
                    case_id=handoff.case_id,
                    provider_ticket_id=handoff.provider_ticket_id,
                    payload=handoff.model_dump(mode="json"),
                )
                .on_conflict_do_update(
                    index_elements=["case_id"],
                    set_={
                        "provider_ticket_id": handoff.provider_ticket_id,
                        "payload": handoff.model_dump(mode="json"),
                    },
                )
            )

    async def claim_handoff(self, handoff: EngineeringHandoff) -> bool:
        async with self.session() as session, session.begin():
            claimed_case_id = await session.scalar(
                insert(HandoffRow)
                .values(
                    case_id=handoff.case_id,
                    provider_ticket_id=handoff.provider_ticket_id,
                    payload=handoff.model_dump(mode="json"),
                )
                .on_conflict_do_nothing()
                .returning(HandoffRow.case_id)
            )
            return claimed_case_id is not None

    async def transition_handoff(
        self,
        handoff: EngineeringHandoff,
        *,
        expected_statuses: frozenset[str],
    ) -> EngineeringHandoff | None:
        async with self.session() as session, session.begin():
            payload = await session.scalar(
                update(HandoffRow)
                .where(HandoffRow.case_id == handoff.case_id)
                .where(HandoffRow.payload["status"].as_string().in_(expected_statuses))
                .values(
                    provider_ticket_id=handoff.provider_ticket_id,
                    payload=handoff.model_dump(mode="json"),
                )
                .returning(HandoffRow.payload)
            )
            return EngineeringHandoff.model_validate(payload) if payload is not None else None

    async def get_handoff(self, case_id: str) -> EngineeringHandoff | None:
        async with self.session() as session:
            row = await session.get(HandoffRow, case_id)
            return EngineeringHandoff.model_validate(row.payload) if row else None

    async def append_audit(self, event: AuditEvent) -> None:
        async with self.session() as session, session.begin():
            session.add(
                AuditRow(
                    id=event.id,
                    subject_id=event.subject_id,
                    created_at=event.created_at,
                    payload=event.model_dump(mode="json"),
                )
            )

    async def list_audit(self, case_id: str) -> list[AuditEvent]:
        async with self.session() as session:
            rows = (
                await session.scalars(
                    select(AuditRow)
                    .where(AuditRow.subject_id == case_id)
                    .order_by(AuditRow.created_at)
                )
            ).all()
            return [AuditEvent.model_validate(row.payload) for row in rows]
