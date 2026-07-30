import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from copilot.domain import GoldenCase, KnowledgeDocument, SupportCase


class FixtureDataset(BaseModel):
    schema_version: str
    dataset_id: str
    classification: str
    articles: list[KnowledgeDocument]
    cases: list[GoldenCase]


def load_dataset(path: Path) -> FixtureDataset:
    data = path.read_bytes()
    payload = json.loads(data)
    dataset = FixtureDataset.model_validate(payload)
    if dataset.classification != "synthetic_only":
        raise ValueError("fixture loader accepts synthetic_only datasets")
    return dataset


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def support_cases(dataset: FixtureDataset) -> list[SupportCase]:
    return [
        SupportCase(
            id=case.id,
            subject=case.subject,
            body=case.body,
            source="fixture",
            source_ref=f"{dataset.dataset_id}:{case.id}",
        )
        for case in dataset.cases
    ]
