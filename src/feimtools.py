"""Loading and invoking optional Python tool modules."""

import importlib.util
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any


_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def discover_module_files(directory: str | Path) -> list[Path]:
    module_dir = Path(directory).expanduser()
    if not module_dir.is_dir():
        return []
    return sorted(
        (path for path in module_dir.glob("*.py")
         if path.is_file() and not path.name.startswith("_")),
        key=lambda path: path.name.casefold(),
    )


def load_module(path: str | Path) -> tuple[Any, list[dict[str, Any]]]:
    module_path = Path(path).expanduser().resolve()
    if module_path.suffix.lower() != ".py" or not module_path.is_file():
        raise ValueError(f"Python module file not found: {module_path}")

    module_name = f"_feimai_module_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Python module: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    tools = getattr(module, "TOOLS", None)
    runner = getattr(module, "run", None)
    if not isinstance(tools, list) or not tools:
        sys.modules.pop(module_name, None)
        raise ValueError(f"{module_path.name} must define a non-empty TOOLS list")
    if not callable(runner):
        sys.modules.pop(module_name, None)
        raise ValueError(f"{module_path.name} must define run(tool_name, arguments, context)")

    validated = []
    names = set()
    try:
        if not _TOOL_NAME.fullmatch(module_path.stem):
            raise ValueError(f"Invalid module filename for a tool module: {module_path.name}")
        for tool in tools:
            if not isinstance(tool, dict):
                raise ValueError(f"Each tool in {module_path.name} must be an object")
            name = tool.get("name")
            description = tool.get("description")
            parameters = tool.get("parameters")
            if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name):
                raise ValueError(f"Invalid tool name in {module_path.name}: {name!r}")
            if name in names:
                raise ValueError(f"Duplicate tool name {name!r} in {module_path.name}")
            names.add(name)
            if not isinstance(description, str) or not description.strip():
                raise ValueError(f"Tool {name!r} in {module_path.name} needs a description")
            if (not isinstance(parameters, dict) or parameters.get("type") != "object"
                    or not isinstance(parameters.get("properties", {}), dict)
                    or not isinstance(parameters.get("required", []), list)
                    or not all(isinstance(key, str) for key in parameters.get("required", []))):
                raise ValueError(f"Tool {name!r} in {module_path.name} needs object parameters")
            try:
                json.dumps(parameters)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Tool {name!r} schema in {module_path.name} is not JSON serializable") from exc
            validated.append({
                "name": name,
                "description": description,
                "parameters": parameters,
            })
            if len(f"{module_path.stem}__{name}") > 64:
                raise ValueError(f"Tool name {name!r} in {module_path.name} exceeds 64 characters")
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    sys.modules.pop(module_name, None)

    return module, validated
