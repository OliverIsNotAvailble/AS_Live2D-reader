"""Live ArtMesh opacity overrides in an ephemeral Cubism MOC3 copy."""
from pathlib import Path


def _tables(moc):
    names = list(moc["art_mesh.ids"])
    visible = moc["art_mesh.visibles"]
    offsets = list(moc["art_mesh.keyform_begin_indices"])
    counts = list(moc["art_mesh.keyform_counts"])
    opacity = moc["art_mesh_keyform.opacities"]
    if (len(set(names)) != len(names) or
            any(len(a) != len(names) for a in (visible, offsets, counts))):
        raise ValueError("Tabelas de ArtMesh inconsistentes no MOC3")
    spans, used = {}, set()
    for i, name in enumerate(names):
        a, n = int(offsets[i]), int(counts[i])
        if a < 0 or n <= 0 or a + n > len(opacity):
            raise ValueError(f"Keyforms inválidas para {name}")
        indices = set(range(a, a + n))
        if used & indices:
            raise ValueError("Keyforms de ArtMesh sobrepostas")
        used.update(indices)
        spans[str(name)] = i, a, n
    return names, visible, opacity, spans


def visibility_map(moc):
    names, visible, _, _ = _tables(moc)
    return {str(name): bool(visible[i]) for i, name in enumerate(names)}


def apply_visibility(moc, overrides: dict[str, bool]):
    """Hide = force all selected mesh opacity keyforms to 0; Show = 1."""
    _, flags, opacities, spans = _tables(moc)
    for mesh_id, show in overrides.items():
        if mesh_id not in spans or type(show) is not bool:
            raise ValueError(f"Estado de ArtMesh inválido: {mesh_id}")
    for mesh_id, show in overrides.items():
        i, start, n = spans[mesh_id]
        flags[i] = show
        for j in range(start, start + n):
            opacities[j] = 1.0 if show else 0.0


def write_visibility_copy(source: Path, output: Path,
                          overrides: dict[str, bool]):
    """Modify and verify a TEMPORARY model file, never the original."""
    from moc3 import Moc3
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or not overrides:
        raise ValueError("O MOC3 original não pode ser sobrescrito")
    model = Moc3.from_file(source)
    names, flags, opacities, spans = _tables(model)
    before_flags = tuple(flags)
    before_opacities = tuple(opacities)
    protected = ("art_mesh.texture_indices", "art_mesh_keyform.draw_orders",
                 "art_mesh.keyform_begin_indices", "art_mesh.keyform_counts",
                 "art_mesh.uv_begin_indices")
    initial = {key: tuple(model[key]) for key in protected}
    apply_visibility(model, overrides)
    target_flags, target_opacities = tuple(flags), tuple(opacities)
    permitted_flags = {spans[name][0] for name in overrides}
    permitted_opacities = {
        pos for name in overrides
        for pos in range(spans[name][1], spans[name][1] + spans[name][2])
    }
    for i, (a, b) in enumerate(zip(before_flags, target_flags)):
        if i not in permitted_flags and a != b:
            raise ValueError("Outra ArtMesh teve a visibilidade alterada")
    for i, (a, b) in enumerate(zip(before_opacities, target_opacities)):
        if i not in permitted_opacities and a != b:
            raise ValueError("Outra ArtMesh teve a opacidade alterada")
    model.to_file(output)
    verified = Moc3.from_file(output)
    if list(verified["art_mesh.ids"]) != names:
        raise ValueError("O arquivo temporário perdeu IDs")
    if tuple(verified["art_mesh.visibles"]) != target_flags:
        raise ValueError("Flags de visibilidade não persistiram")
    result = tuple(verified["art_mesh_keyform.opacities"])
    if len(result) != len(target_opacities) or any(
            abs(float(x) - float(y)) > 1e-5
            for x, y in zip(result, target_opacities)):
        raise ValueError("Opacidades não persistiram no modelo temporário")
    for key, values in initial.items():
        if tuple(verified[key]) != values:
            raise ValueError(f"Campo indevido alterado: {key}")
