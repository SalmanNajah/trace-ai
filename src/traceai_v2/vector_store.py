from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest


@dataclass
class VectorCollections:
    requirements: str
    code_units: str
    size: int


class VectorStore:
    def __init__(self, url: str, collections: VectorCollections):
        self.client = QdrantClient(url=url)
        self.collections = collections

    def ensure_collections(self) -> None:
        self._ensure_collection(self.collections.requirements)
        self._ensure_collection(self.collections.code_units)

    def upsert_requirement(self, requirement_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self.client.upsert(
            collection_name=self.collections.requirements,
            points=[rest.PointStruct(id=requirement_id, vector=vector, payload=payload)],
            wait=True,
        )

    def upsert_code_unit(self, code_unit_id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self.client.upsert(
            collection_name=self.collections.code_units,
            points=[rest.PointStruct(id=code_unit_id, vector=vector, payload=payload)],
            wait=True,
        )

    def delete_requirement_vectors(self, project_id: str) -> None:
        self._delete_by_project(self.collections.requirements, project_id)

    def delete_code_vectors(self, project_id: str) -> None:
        self._delete_by_project(self.collections.code_units, project_id)

    def delete_code_units_by_file(self, project_id: str, file_path: str) -> None:
        self.client.delete(
            collection_name=self.collections.code_units,
            points_selector=rest.FilterSelector(
                filter=rest.Filter(
                    must=[
                        rest.FieldCondition(key="project_id", match=rest.MatchValue(value=project_id)),
                        rest.FieldCondition(key="file_path", match=rest.MatchValue(value=file_path)),
                    ]
                )
            ),
            wait=True,
        )

    def search_code_units(self, *, project_id: str, query_vector: list[float], limit: int) -> list[dict[str, Any]]:
        query_filter = self._project_filter(project_id)
        try:
            points = self.client.query_points(
                collection_name=self.collections.code_units,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            ).points
        except (AttributeError, TypeError):
            points = self.client.search(
                collection_name=self.collections.code_units,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        return [
            {
                "id": str(point.id),
                "score": float(point.score),
                "payload": dict(point.payload or {}),
            }
            for point in points
        ]

    def sample_vectors(
        self,
        *,
        project_id: str,
        kind: str,
        limit: int = 3,
        preview_dims: int = 8,
    ) -> list[dict[str, Any]]:
        collection = self.collections.requirements if kind == "requirements" else self.collections.code_units
        points, _ = self.client.scroll(
            collection_name=collection,
            scroll_filter=self._project_filter(project_id),
            limit=limit,
            with_payload=True,
            with_vectors=True,
        )
        items: list[dict[str, Any]] = []
        for point in points:
            vector = list(point.vector or [])
            items.append(
                {
                    "id": str(point.id),
                    "payload": dict(point.payload or {}),
                    "vector_size": len(vector),
                    "vector_preview": vector[:preview_dims],
                }
            )
        return items

    def count_points(self, project_id: str) -> dict[str, int]:
        requirements_count = self.client.count(
            collection_name=self.collections.requirements,
            count_filter=self._project_filter(project_id),
            exact=True,
        ).count
        code_count = self.client.count(
            collection_name=self.collections.code_units,
            count_filter=self._project_filter(project_id),
            exact=True,
        ).count
        return {
            "requirements_vectors": requirements_count,
            "code_unit_vectors": code_count,
        }

    def _ensure_collection(self, name: str) -> None:
        existing = self.client.collection_exists(collection_name=name)
        if existing:
            info = self.client.get_collection(collection_name=name)
            current_size = info.config.params.vectors.size
            if current_size != self.collections.size:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    "Collection %s has vector size %d but expected %d — recreating.",
                    name,
                    current_size,
                    self.collections.size,
                )
                self.client.delete_collection(collection_name=name)
            else:
                return
        self.client.create_collection(
            collection_name=name,
            vectors_config=rest.VectorParams(size=self.collections.size, distance=rest.Distance.COSINE),
        )

    def _delete_by_project(self, collection_name: str, project_id: str) -> None:
        self.client.delete(
            collection_name=collection_name,
            points_selector=rest.FilterSelector(filter=self._project_filter(project_id)),
            wait=True,
        )

    def _project_filter(self, project_id: str) -> rest.Filter:
        return rest.Filter(
            must=[rest.FieldCondition(key="project_id", match=rest.MatchValue(value=project_id))]
        )
