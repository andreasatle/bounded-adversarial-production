from __future__ import annotations

import json
import shutil
from difflib import unified_diff
from pathlib import Path

from baps.schemas import Artifact, ArtifactAdapterResult, ArtifactChange, ArtifactVersion


class ArtifactAdapter:
    def create(self, artifact: Artifact) -> ArtifactAdapterResult:
        raise NotImplementedError

    def snapshot(self, artifact: Artifact) -> ArtifactVersion:
        raise NotImplementedError

    def propose_change(self, artifact: Artifact, description: str, new_content: str) -> ArtifactChange:
        raise NotImplementedError

    def apply_change(self, artifact: Artifact, change_id: str) -> ArtifactVersion:
        raise NotImplementedError

    def rollback(self, artifact: Artifact, version_id: str) -> ArtifactVersion:
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

    def propose_change(self, artifact: Artifact, description: str, new_content: str) -> ArtifactChange:
        adapter = self.adapters.get(artifact.type)
        if adapter is None:
            raise ValueError(f"no adapter registered for artifact type: {artifact.type}")
        return adapter.propose_change(artifact, description, new_content)

    def apply_change(self, artifact: Artifact, change_id: str) -> ArtifactVersion:
        adapter = self.adapters.get(artifact.type)
        if adapter is None:
            raise ValueError(f"no adapter registered for artifact type: {artifact.type}")
        return adapter.apply_change(artifact, change_id)

    def rollback(self, artifact: Artifact, version_id: str) -> ArtifactVersion:
        adapter = self.adapters.get(artifact.type)
        if adapter is None:
            raise ValueError(f"no adapter registered for artifact type: {artifact.type}")
        return adapter.rollback(artifact, version_id)


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
        changes_dir = artifact_dir / "changes"
        main_file = current_dir / "main.md"
        metadata_path = artifact_dir / "metadata.json"

        current_dir.mkdir(parents=True)
        versions_dir.mkdir(parents=True)
        changes_dir.mkdir(parents=True)
        main_file.touch(exist_ok=True)
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

    def propose_change(self, artifact: Artifact, description: str, new_content: str) -> ArtifactChange:
        if artifact.type != "document":
            raise ValueError("artifact.type must be 'document'")

        artifact_dir = self.root / artifact.id
        current_main = artifact_dir / "current" / "main.md"
        changes_dir = artifact_dir / "changes"
        if not current_main.exists():
            raise FileNotFoundError(f"missing current/main.md for {artifact.id}")

        changes_dir.mkdir(parents=True, exist_ok=True)
        existing_changes = sorted(
            child.name
            for child in changes_dir.iterdir()
            if child.is_dir() and child.name.startswith("c") and child.name[1:].isdigit()
        )
        next_index = len(existing_changes) + 1
        change_id = f"c{next_index:03d}"
        change_dir = changes_dir / change_id
        if change_dir.exists():
            raise FileExistsError(f"change directory already exists: {change_dir}")

        current_content = current_main.read_text(encoding="utf-8")
        diff = "".join(
            unified_diff(
                current_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile="current/main.md",
                tofile="proposed/main.md",
            )
        )

        base_version = artifact.current_version if artifact.current_version is not None else "unversioned"
        change = ArtifactChange(
            artifact_id=artifact.id,
            change_id=change_id,
            base_version=base_version,
            description=description,
            diff=diff,
        )

        change_dir.mkdir(parents=True)
        (change_dir / "proposed.md").write_text(new_content, encoding="utf-8")
        (change_dir / "change.json").write_text(
            json.dumps(change.model_dump(mode="json")),
            encoding="utf-8",
        )
        return change

    def apply_change(self, artifact: Artifact, change_id: str) -> ArtifactVersion:
        artifact_dir = self.root / artifact.id
        change_dir = artifact_dir / "changes" / change_id
        proposed_file = change_dir / "proposed.md"
        current_main = artifact_dir / "current" / "main.md"

        if not proposed_file.exists():
            raise FileNotFoundError(f"change does not exist: {change_id}")

        current_main.parent.mkdir(parents=True, exist_ok=True)
        current_main.write_text(proposed_file.read_text(encoding="utf-8"), encoding="utf-8")
        return self.snapshot(artifact)

    def rollback(self, artifact: Artifact, version_id: str) -> ArtifactVersion:
        artifact_dir = self.root / artifact.id
        version_dir = artifact_dir / "versions" / version_id
        current_dir = artifact_dir / "current"

        if not version_dir.exists():
            raise FileNotFoundError(f"version does not exist: {version_id}")

        if current_dir.exists():
            shutil.rmtree(current_dir)
        shutil.copytree(version_dir, current_dir)
        return ArtifactVersion(artifact_id=artifact.id, version_id=version_id, path=str(version_dir))
