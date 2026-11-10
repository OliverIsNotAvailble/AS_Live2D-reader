"""Read-only Cubism Part > sub-Part > ArtMesh mapping from MOC3."""
from dataclasses import dataclass
from pathlib import Path

from .model import read_json, reference_path


@dataclass(frozen=True)
class PartHierarchy:
    parts: tuple[str, ...]
    parents: tuple[int, ...]
    meshes_by_part: dict[str, tuple[str, ...]]
    ungrouped: tuple[str, ...]
    mesh_count: int
    mesh_visibility: dict[str, bool]

    def descendants_count(self, part_id: str) -> int:
        positions = {part: i for i, part in enumerate(self.parts)}
        if part_id not in positions:
            return 0
        seen = set()

        def count(index):
            if index in seen:
                return 0
            seen.add(index)
            n = len(self.meshes_by_part.get(self.parts[index], ()))
            for child, parent in enumerate(self.parents):
                if child != index and parent == index:
                    n += count(child)
            return n
        return count(positions[part_id])


def build_part_hierarchy(parts, parents, meshes, mesh_parents,
                         mesh_deformers=(), deformer_parts=(),
                         deformer_parents=(), mesh_visibles=None) -> PartHierarchy:
    parts, parents = tuple(map(str, parts)), tuple(map(int, parents))
    meshes, mesh_parents = tuple(map(str, meshes)), tuple(map(int, mesh_parents))
    mesh_deformers = tuple(map(int, mesh_deformers))
    deformer_parts = tuple(map(int, deformer_parts))
    deformer_parents = tuple(map(int, deformer_parents))
    if (len(parts) != len(parents) or len(meshes) != len(mesh_parents)
            or len(set(parts)) != len(parts)):
        raise ValueError("Seções Parts/ArtMeshes inconsistentes no MOC3.")
    if (mesh_deformers or deformer_parts or deformer_parents) and (
            len(mesh_deformers) != len(meshes) or
            len(deformer_parts) != len(deformer_parents)):
        raise ValueError("Seções de deformers inconsistentes no MOC3.")

    def inherited_part(index):
        seen = set()
        while 0 <= index < len(deformer_parts) and index not in seen:
            seen.add(index)
            part = deformer_parts[index]
            if 0 <= part < len(parts):
                return part
            index = deformer_parents[index]
        return -1

    mapping = {part: [] for part in parts}
    ungrouped = []
    for i, mesh in enumerate(meshes):
        part = mesh_parents[i]
        if not 0 <= part < len(parts) and mesh_deformers:
            part = inherited_part(mesh_deformers[i])
        if 0 <= part < len(parts):
            mapping[parts[part]].append(mesh)
        else:
            ungrouped.append(mesh)
    if mesh_visibles is None:
        mesh_visibles = [True] * len(meshes)
    if len(mesh_visibles) != len(meshes):
        raise ValueError("ArtMesh visibility array size mismatch")
    return PartHierarchy(parts, parents,
                         {p: tuple(ids) for p, ids in mapping.items()},
                         tuple(ungrouped), len(meshes),
                         dict(zip(meshes, map(bool, mesh_visibles))))


def read_part_hierarchy(manifest: Path) -> PartHierarchy:
    try:
        from moc3 import Moc3
    except ImportError as exc:
        raise RuntimeError("Instale py-moc3==0.1.0") from exc
    manifest = Path(manifest)
    moc_ref = (read_json(manifest).get("FileReferences") or {}).get("Moc")
    if not moc_ref:
        raise ValueError("O .model3.json não informou o MOC3.")
    moc_file = reference_path(manifest.parent, moc_ref)
    moc = Moc3.from_file(moc_file)
    return build_part_hierarchy(
        moc["part.ids"], moc["part.parent_part_indices"],
        moc["art_mesh.ids"], moc["art_mesh.parent_part_indices"],
        moc["art_mesh.parent_deformer_indices"],
        moc["deformer.parent_part_indices"],
        moc["deformer.parent_deformer_indices"],
        mesh_visibles=moc["art_mesh.visibles"])
