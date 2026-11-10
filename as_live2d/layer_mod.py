"""Experimental draw-depth changes for self-contained Cubism MOC3 mod copies.

Only the selected ArtMesh keyform draw-order values are altered; this is not
a renderer override, nor a geometry/UV rewrite. Cubism draw-order groups and
parameter-driven behavior can change visible results. Original files stay intact.
"""
from __future__ import annotations

from pathlib import Path


def set_artmesh_draw_depths(moc, overrides: dict[str, int]) -> dict[str, int]:
    """Patch every draw-order keyform for each named ArtMesh in a MOC3 object.

    A constant value across keyforms is intentional: an animation cannot
    immediately restore the original draw depth for the selected ArtMesh.
    """
    ids = list(moc["art_mesh.ids"])
    starts = moc["art_mesh.keyform_begin_indices"]
    counts = moc["art_mesh.keyform_counts"]
    values = moc["art_mesh_keyform.draw_orders"]
    if len(ids) != len(starts) or len(ids) != len(counts):
        raise ValueError("Seções de ArtMesh/keyforms inconsistentes no MOC3.")
    if len(set(ids)) != len(ids):
        raise ValueError("IDs de ArtMesh duplicados no MOC3.")
    touched = {}
    index_by_id = {name: i for i, name in enumerate(ids)}
    for mesh_id, order in overrides.items():
        if not isinstance(mesh_id, str) or mesh_id not in index_by_id:
            raise ValueError(f"ArtMesh desconhecida no MOC3: {mesh_id}")
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 1000:
            raise ValueError(f"Camada inválida para {mesh_id}: {order}")
        index = index_by_id[mesh_id]
        start = int(starts[index])
        count = int(counts[index])
        if count <= 0 or start < 0 or start + count > len(values):
            raise ValueError(f"Keyforms de camada inválidas para {mesh_id}")
        for keyframe in range(start, start + count):
            values[keyframe] = float(order)
        touched[mesh_id] = count
    return touched


def write_moc_with_draw_depths(source: Path, target: Path,
                               overrides: dict[str, int]) -> None:
    """Write a modified copy and verify keyforms by opening it again.

    Call only with the MOC already COPIED to a temporary staging directory.
    Never pass original user paths as target.
    """
    from moc3 import Moc3

    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        raise ValueError("Não é permitido sobrescrever o MOC3 original.")
    if not overrides:
        raise ValueError("Nenhuma camada alterada.")
    moc = Moc3.from_file(source)
    expected = set_artmesh_draw_depths(moc, overrides)
    moc.to_file(target)

    verified = Moc3.from_file(target)
    if list(verified["art_mesh.ids"]) != list(moc["art_mesh.ids"]):
        raise ValueError("O MOC3 regravado perdeu IDs de ArtMesh.")
    starts = verified["art_mesh.keyform_begin_indices"]
    counts = verified["art_mesh.keyform_counts"]
    values = verified["art_mesh_keyform.draw_orders"]
    id_positions = {mesh_id: i for i, mesh_id
                    in enumerate(verified["art_mesh.ids"])}
    for mesh_id, expected_count in expected.items():
        i = id_positions[mesh_id]
        start, count = int(starts[i]), int(counts[i])
        if count != expected_count or start < 0 or start + count > len(values):
            raise ValueError(f"Camada do MOC3 não foi preservada: {mesh_id}")
        if any(abs(float(values[k]) - float(overrides[mesh_id])) > 0.001
               for k in range(start, start + count)):
            raise ValueError(f"Falha na verificação da camada: {mesh_id}")
