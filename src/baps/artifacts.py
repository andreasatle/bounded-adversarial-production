from __future__ import annotations

import json
import shutil
from pathlib import Path

from baps.schemas import Artifact, ArtifactAdapterResult, ArtifactVersion


class ArtifactAdapter:
    def create(self, artifact: Artifact) -> ArtifactAdapterResult:
        raise NotImplementedError

    def snapshot(self, artifact: Artifact) -> ArtifactVersion:
        raise NotImplementedError


class ArtifactHandler:
    def __init__(self, adapters: dict[str, ArtifactAdapter]):
        self.adapters = adapters

    def create(self, artifact: Artifact) -> ArtifactAdapterResult:
        adapter = self.adapters.get(artifact.type)
        if adapter is None:
            raise ValueError(f"no adapter registered for artifact type: {artifact.type}")
        return adapter.create(artifact)

    def snapshot(self, artifact: Artifact) -> ArtifactVersion:
        adapter = self.adapters.get(artifact.type)
        if adapter is None:
            raise ValueError(f"no adapter registered for artifact type: {artifact.type}")
        return adapter.snapshot(artifact)


class DocumentArtifactAdapter(ArtifactAdapter):
    def __init__(self, root: Path):
        self.root = root

    def create(self, artifact: Artifact) -> ArtifactAdapterResult:
        if artifact.type != "document":
            raise ValueError("artifact.type must be 'document'")

        artifact_dir = self.root / artifact.id
        if artifact_dir.exists():
            raise FileExistsError(f"artifact directory already exists: {artifact_dir}")

        current_dir = artifact_dir / "current"
        versions_dir = artifact_dir / "versions"
        metadata_path = artifact_dir / "metadata.json"

        current_dir.mkdir(parents=True)
        versions_dir.mkdir(parents=True)
        metadata_path.write_text(
            json.dumps(artifact.model_dump(mode="json")),
            encoding="utf-8",
        )

        return ArtifactAdapterResult(artifact_id=artifact.id, message="artifact created")

    def snapshot(self, artifact: Artifact) -> ArtifactVersion:
        artifact_dir = self.root / artifact.id
        current_dir = artifact_dir / "current"
        versions_dir = artifact_dir / "versions"

        if not artifact_dir.exists() or not current_dir.exists():
            raise FileNotFoundError(f"missing artifact/current directory for {artifact.id}")

        versions_dir.mkdir(parents=True, exist_ok=True)
        existing_versions = sorted(
            child.name
            for child in versions_dir.iterdir()
            if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit()
        )
        next_index = len(existing_versions) + 1
        version_id = f"v{next_index:03d}"
        version_dir = versions_dir / version_id

        if version_dir.exists():
            raise FileExistsError(f"version directory already exists: {version_dir}")

        shutil.copytree(current_dir, version_dir)
        return ArtifactVersion(artifact_id=artifact.id, version_id=version_id, path=str(version_dir))
