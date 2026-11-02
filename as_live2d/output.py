"""Session-only fixed export root and per-JSON export subfolders.

This module performs validation and path composition only: no directory is
created until the actual EncodeWorker starts writing an export.
"""
from __future__ import annotations

from pathlib import Path
import re


def model_export_folder_name(model_json: Path) -> str:
    """Return the model JSON's filename without .json / .model3.json."""
    name = Path(model_json).name
    lower = name.lower()
    if lower.endswith(".model3.json"):
        stem = name[:-len(".model3.json")]
    elif lower.endswith(".json"):
        stem = name[:-len(".json")]
    else:
        raise ValueError("O modelo aberto precisa ser um arquivo .json.")

    # Keep accents and spaces; only exclude path-unsafe Windows characters.
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    if not stem or stem in (".", ".."):
        raise ValueError("O nome do arquivo JSON não pode formar uma pasta.")
    return stem


def fixed_output_for_model(base_directory: str, model_json: Path | None) -> Path:
    """Return <fixed base>/<model filename> without saving any preference."""
    text = str(base_directory).strip().strip('"').strip()
    if not text:
        raise ValueError("Pasta de saída fixa não definida. Escolha uma pasta antes de exportar.")
    if model_json is None:
        raise ValueError("Abra um modelo JSON antes de exportar.")

    root = Path(text).expanduser()
    if not root.is_dir():
        raise ValueError("A pasta de saída fixa não existe ou não é uma pasta:\n" + str(root))
    return root.resolve() / model_export_folder_name(Path(model_json))
