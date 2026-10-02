"""Generate package identity, preserving it when building a wheel from sdist."""

import importlib.util
import json
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        supplied = root / "app" / "_build_info.json"
        if supplied.exists():
            identity = json.loads(supplied.read_text(encoding="utf-8"))
        else:
            helper = root.parent / "scripts" / "build_identity.py"
            spec = importlib.util.spec_from_file_location("build_identity", helper)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            identity = module.build_identity(root.parent)
        if identity["version"].replace("-rc.", "rc") != self.metadata.version:
            raise ValueError("Package/product identity mismatch")
        if supplied.exists():
            return  # sdist already contains the identity; don't include it twice.
        generated = root / ".build" / "_build_info.json"
        generated.parent.mkdir(exist_ok=True)
        generated.write_text(json.dumps(identity) + "\n", encoding="utf-8")
        build_data.setdefault("force_include", {})[str(generated)] = "app/_build_info.json"
