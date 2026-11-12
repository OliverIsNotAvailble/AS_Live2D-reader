"""VLote-style Live2D project discovery and safe classification.

Only immediate child folders of the selected root are movable projects.
Never move the root itself or accidentally rescan _Done/_Null/_EXT.
"""
from __future__ import annotations

import os
from pathlib import Path

from .model import read_json
from .output import model_export_folder_name

CATEGORY_FOLDERS = frozenset({"_done", "_null", "_ext"})


def discover_models(root: str | Path) -> list[Path]:
    """Find model manifests in project folders, recursively and predictably.

    Models placed directly in root are deliberately ignored: moving root
    inside itself would be destructive, while all assets in a project subfolder
    can safely be classified together.
    """
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"Pasta raiz inválida: {base}")
    files: list[Path] = []
    for directory, subdirs, filenames in os.walk(base, followlinks=False):
        directory = Path(directory)
        depth = len(directory.relative_to(base).parts)
        subdirs[:] = sorted(
            (name for name in subdirs
             if not (directory / name).is_symlink()
             and (depth > 0 or name.casefold() not in CATEGORY_FOLDERS)),
            key=str.casefold,
        )
        if depth == 0:
            continue
        for name in sorted(filenames, key=str.casefold):
            low = name.casefold()
            if not low.endswith(".json") or low.endswith(".as-reader.json"):
                continue
            candidate = directory / name
            if not candidate.is_file() or candidate.is_symlink():
                continue
            if low.endswith(".model3.json"):
                files.append(candidate.resolve())
                continue
            if low.endswith((".motion3.json", ".physics3.json", ".pose3.json",
                             ".exp3.json", ".cdi3.json", ".userdata3.json")):
                continue
            try:
                info = read_json(candidate)
            except (OSError, ValueError, TypeError):
                continue
            refs = info.get("FileReferences")
            if isinstance(refs, dict) and isinstance(refs.get("Moc"), str):
                files.append(candidate.resolve())
    return sorted(
        files, key=lambda p: (
            p.relative_to(base).parts[0].casefold(),
            str(p.relative_to(base)).casefold(),
        ),
    )


def project_folder(root: str | Path, model: str | Path) -> Path:
    """Resolve an input model's top-level project folder under the batch root."""
    base = Path(root).expanduser().resolve()
    path = Path(model).expanduser().resolve()
    rel = path.relative_to(base)
    if len(rel.parts) < 2 or rel.parts[0].casefold() in CATEGORY_FOLDERS:
        raise ValueError("Modelos do lote precisam estar dentro de subpastas da raiz.")
    project = base / rel.parts[0]
    # Earlier queue entries may already have been moved into _Done/_Null.
    # Their original project path still needs to identify the project group,
    # so grouping must not require the directory to keep existing.
    if project.is_symlink() or (project.exists() and not project.is_dir()):
        raise ValueError(f"Pasta do projeto inválida: {project}")
    return project


def batch_model_output(
    root: str | Path, model: str | Path, *, multiple_in_project: bool = False,
) -> Path:
    """_EXT/project for a single manifest, _EXT/project/manifest for many."""
    base = Path(root).expanduser().resolve()
    path = Path(model).expanduser().resolve()
    group = project_folder(base, path)
    output = base / "_EXT" / group.name
    if multiple_in_project:
        relative = path.relative_to(group)
        output = (output / relative.parent /
                  model_export_folder_name(relative))
    return output


def available_destination(parent: Path, name: str) -> Path:
    """Never overwrite previously exported/classified source folders."""
    dest = parent / name
    index = 2
    while dest.exists():
        dest = parent / f"{name} ({index})"
        index += 1
    return dest


def move_project(root: str | Path, model: str | Path, decision: str) -> Path:
    """Atomically move one complete project into _Done or _Null.

    Both destinations live on the SAME filesystem as source; no copying,
    deleting or replacing existing folders. Failure leaves source untouched.
    """
    if decision not in ("done", "null"):
        raise ValueError("Classificação inválida.")
    base = Path(root).expanduser().resolve()
    source = project_folder(base, model)
    if source.parent != base:
        raise ValueError("Não é seguro mover pastas fora da raiz.")
    if not source.is_dir():
        raise FileNotFoundError(f"Pasta original ausente: {source}")
    target_dir = base / ("_Done" if decision == "done" else "_Null")
    if target_dir.is_symlink():
        raise ValueError(f"Destino é um link/junction: {target_dir}")
    target_dir.mkdir(exist_ok=True)
    destination = available_destination(target_dir, source.name)
    source.rename(destination)
    return destination
