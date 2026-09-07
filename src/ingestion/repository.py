"""Persistência de telemetria em coleções MongoDB convencionais e Time Series."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

from .models import TelemetryMessage


class StorageMode(StrEnum):
    DOCUMENT = "document"
    TIMESERIES = "timeseries"
    DUAL = "dual"


@dataclass(frozen=True)
class MongoSettings:
    host: str
    port: int
    username: str
    password: str
    database: str
    auth_database: str
    document_collection: str
    timeseries_collection: str
    storage_mode: StorageMode


class MongoTelemetryRepository:
    """Inicializa as coleções e grava uma medição no modo configurado."""

    def __init__(self, settings: MongoSettings) -> None:
        self.settings = settings
        self.client = MongoClient(
            host=settings.host,
            port=settings.port,
            username=settings.username,
            password=settings.password,
            authSource=settings.auth_database,
            serverSelectionTimeoutMS=5_000,
            tz_aware=True,
        )
        self.database: Database = self.client[settings.database]

    def initialize(self) -> None:
        """Confirma a conexão e cria índices e coleção Time Series quando necessário."""
        self.client.admin.command("ping")
        self.database[self.settings.document_collection].create_index(
            [("message_id", ASCENDING)], unique=True, name="message_id_unique"
        )
        self.database[self.settings.document_collection].create_index(
            [("source.plant_id", ASCENDING), ("source.tank_id", ASCENDING), ("timestamp", ASCENDING)],
            name="source_and_timestamp",
        )

        existing_collections = self.database.list_collection_names()
        if self.settings.timeseries_collection not in existing_collections:
            self.database.create_collection(
                self.settings.timeseries_collection,
                timeseries={
                    "timeField": "timestamp",
                    "metaField": "source",
                    "granularity": "seconds",
                },
            )

    def persist(self, message: TelemetryMessage) -> dict[str, Any]:
        """Persiste a mesma estrutura lógica nas coleções selecionadas."""
        document = message.to_mongo_document()
        inserted: dict[str, str] = {}

        if self.settings.storage_mode in {StorageMode.DOCUMENT, StorageMode.DUAL}:
            result = self.database[self.settings.document_collection].insert_one(document)
            inserted["document"] = str(result.inserted_id)

        if self.settings.storage_mode in {StorageMode.TIMESERIES, StorageMode.DUAL}:
            result = self.database[self.settings.timeseries_collection].insert_one(document)
            inserted["timeseries"] = str(result.inserted_id)

        return inserted

    def close(self) -> None:
        self.client.close()
