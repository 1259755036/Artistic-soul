import json
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

try:
    from pydantic import BaseModel, create_model

    HAS_PYDANTIC = True
except ModuleNotFoundError:  # pragma: no cover - only during lightweight testing
    BaseModel = object  # type: ignore[assignment]

    def create_model(*args: Any, **kwargs: Any) -> Type[BaseModel]:  # type: ignore[override]
        raise RuntimeError("Pydantic is required to build models. Install dependencies via requirements.txt.")

    HAS_PYDANTIC = False

from .utils.yaml_loader import safe_load


@dataclass
class FieldDefinition:
    name: str
    type: str
    required: bool
    patterns: List[str] = field(default_factory=list)
    normalize: List[str] = field(default_factory=list)
    allowed: Optional[List[str]] = None
    default: Any = None
    synonyms_from: Optional[str] = None


class ConfigLoader:
    """Loads YAML configuration for fields and synonyms with hot reload support."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.fields_config_path = base_dir / "fields.yaml"
        self._lock = threading.RLock()
        self._field_definitions: List[FieldDefinition] = []
        self._synonyms: Dict[str, Dict[str, str]] = {}
        self._pydantic_model: Optional[Type[BaseModel]] = None
        self._schema_json: Optional[str] = None
        self._watch_files: Dict[Path, float] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            data = safe_load(self.fields_config_path.read_text())
            fields_raw = data.get("fields", [])
            definitions: List[FieldDefinition] = []
            synonyms: Dict[str, Dict[str, str]] = {}
            watch_files: Dict[Path, float] = {self.fields_config_path: self.fields_config_path.stat().st_mtime}

            for entry in fields_raw:
                field_def = FieldDefinition(
                    name=entry["name"],
                    type=entry.get("type", "string"),
                    required=bool(entry.get("required", False)),
                    patterns=entry.get("patterns", []) or [],
                    normalize=entry.get("normalize", []) or [],
                    allowed=entry.get("allowed"),
                    default=entry.get("default"),
                    synonyms_from=entry.get("synonyms_from"),
                )
                definitions.append(field_def)

                if field_def.synonyms_from:
                    syn_path = self.base_dir / field_def.synonyms_from
                    if syn_path.exists():
                        watch_files[syn_path] = syn_path.stat().st_mtime
                        syn_dict = safe_load(syn_path.read_text()) or {}
                        synonyms[field_def.name] = self._build_synonyms_map(syn_dict)
                    else:
                        synonyms[field_def.name] = {}
                else:
                    synonyms[field_def.name] = {}

            self._field_definitions = definitions
            self._synonyms = synonyms
            self._watch_files = watch_files
            if HAS_PYDANTIC:
                self._pydantic_model = self._build_pydantic_model()
                self._schema_json = json.dumps(self._pydantic_model.schema(), sort_keys=True)
            else:
                self._pydantic_model = None
                self._schema_json = None

    def _build_synonyms_map(self, syn_dict: Dict[str, List[str]]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for canonical, synonyms in syn_dict.items():
            mapping[canonical.lower()] = canonical
            for synonym in synonyms:
                mapping[str(synonym).lower()] = canonical
        return mapping

    def _build_pydantic_model(self) -> Type[BaseModel]:
        annotations: Dict[str, Tuple[Any, Any]] = {}
        for field_def in self._field_definitions:
            py_type: Any
            default: Any
            if field_def.type == "date":
                py_type = date if field_def.required else Optional[date]
                default = ... if field_def.required else None
            elif field_def.type == "number":
                py_type = float if field_def.required else Optional[float]
                default = ... if field_def.required else None
            elif field_def.type == "enum":
                if not field_def.allowed:
                    raise ValueError(f"Enum field {field_def.name} requires 'allowed' list")
                py_type = str if field_def.required else Optional[str]
                default = ... if field_def.required else (field_def.default if field_def.default is not None else None)
            else:
                py_type = str if field_def.required else Optional[str]
                default = ... if field_def.required else (field_def.default if field_def.default is not None else None)

            annotations[field_def.name] = (py_type, default)

        model = create_model("ParsedRecord", **annotations)  # type: ignore[arg-type]
        model.__config__.extra = "forbid"
        return model

    def get_model(self) -> Type[BaseModel]:
        with self._lock:
            if not HAS_PYDANTIC:
                raise RuntimeError("Pydantic is required. Install dependencies before calling get_model().")
            if not self._pydantic_model:
                self._pydantic_model = self._build_pydantic_model()
            return self._pydantic_model

    def get_field_definitions(self) -> List[FieldDefinition]:
        with self._lock:
            return list(self._field_definitions)

    def get_synonyms(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            return {k: dict(v) for k, v in self._synonyms.items()}

    def get_schema_json(self) -> str:
        with self._lock:
            if self._schema_json is None:
                if not HAS_PYDANTIC:
                    raise RuntimeError("Pydantic is required. Install dependencies before requesting schema JSON.")
                self._schema_json = json.dumps(self.get_model().schema(), sort_keys=True)
            return self._schema_json

    def needs_reload(self) -> bool:
        for path, mtime in self._watch_files.items():
            if not path.exists() or path.stat().st_mtime > mtime:
                return True
        return False

    def reload_if_needed(self) -> bool:
        if self.needs_reload():
            self.load()
            return True
        return False


config_loader = ConfigLoader(Path(__file__).resolve().parent.parent / "config")


__all__ = ["config_loader", "ConfigLoader", "FieldDefinition"]
