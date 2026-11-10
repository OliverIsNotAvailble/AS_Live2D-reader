"""Individual Cubism ArtMesh visibility, applied only to copied MOC3 files."""
from pathlib import Path


def visibility_map(moc):
    ids = list(moc["art_mesh.ids"])
    flags = list(moc["art_mesh.visibles"])
    if len(ids) != len(flags) or len(ids) != len(set(ids)):
        raise ValueError("ArtMesh ID and visibility arrays disagree")
    return {str(k): bool(v) for k, v in zip(ids, flags)}


def apply_visibility(moc, overrides: dict[str, bool]):
    current = visibility_map(moc)
    for mesh_id, enabled in overrides.items():
        if mesh_id not in current:
            raise ValueError(f"ArtMesh desconhecida: {mesh_id}")
        if type(enabled) is not bool:
            raise ValueError(f"Visibilidade inválida para ArtMesh {mesh_id}")
    indices = {name: i for i, name in enumerate(current)}
    visible = moc["art_mesh.visibles"]
    for mesh_id, enabled in overrides.items():
        visible[indices[mesh_id]] = enabled


def write_visibility_copy(source: Path, output: Path, overrides: dict[str, bool]):
    """Save and verify a MOC3 COPY without altering keyforms/draw depth."""
    from moc3 import Moc3

    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or not overrides:
        raise ValueError("Não é permitido sobrescrever o MOC3 de origem.")
    moc = Moc3.from_file(source)
    original_flags = visibility_map(moc)
    stable_sections = (
        "art_mesh.texture_indices",
        "art_mesh_keyform.draw_orders",
        "art_mesh_keyform.opacities",
        "art_mesh.keyform_begin_indices",
        "art_mesh.keyform_counts",
        "art_mesh.uv_begin_indices",
    )
    stable = {key: tuple(moc[key]) for key in stable_sections}
    apply_visibility(moc, overrides)
    moc.to_file(output)
    result = Moc3.from_file(output)
    original_flags.update(overrides)
    if visibility_map(result) != original_flags:
        raise ValueError("Visibilidade do arquivo mod não foi preservada.")
    if any(tuple(result[key]) != value for key, value in stable.items()):
        raise ValueError("Outros dados do MOC3 mudaram durante a gravação.")
