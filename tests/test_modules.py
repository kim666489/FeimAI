import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from FeimUI import DEFAULT_CONFIG, ToolBox, deepMerge
from feimtools import discover_module_files, load_module


class PythonModuleToolTests(unittest.TestCase):
    def make_module(self, directory, name="sample", runner="return {'answer': arguments['value']}"):
        path = Path(directory) / f"{name}.py"
        path.write_text(
            "TOOLS = [{'name': 'echo', 'description': 'Echo a value', "
            "'parameters': {'type': 'object', 'properties': "
            "{'value': {'type': 'string'}}, 'required': ['value']}}]\n"
            "def run(tool_name, arguments, context):\n"
            f"    {runner}\n",
            encoding="utf-8",
        )
        return path

    def test_discovery_skips_private_python_files(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_module(directory)
            self.make_module(directory, "__private")
            self.assertEqual([p.stem for p in discover_module_files(directory)], ["sample"])

    def test_toolbox_loads_and_executes_only_enabled_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            module_path = self.make_module(directory)
            config = deepMerge(DEFAULT_CONFIG, {
                "tools": {"enabled": True, "workspace": directory},
                "modules": {
                    "enabled": True,
                    "directory": directory,
                    "plugins": {"sample": True},
                },
            })
            toolbox = ToolBox(config, lambda *_: True)
            schemas = toolbox.schemas()
            registered = next(
                item for item in schemas
                if item["function"]["name"] == "sample__echo")
            self.assertEqual(registered["function"]["parameters"]["required"], ["value"])
            self.assertEqual(toolbox.call("sample__echo", {"value": "ok"}),
                             json.dumps({"answer": "ok"}))
            self.assertNotEqual(module_path.stem, "unrelated")

    def test_disabled_module_is_not_imported_or_advertised(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_module(directory, runner="raise AssertionError('should not run')")
            config = deepMerge(DEFAULT_CONFIG, {
                "modules": {
                    "enabled": True,
                    "directory": directory,
                    "plugins": {"sample": False},
                },
            })
            toolbox = ToolBox(config, lambda *_: True)
            schemas = toolbox.schemas()
            self.assertFalse(any(
                item["function"]["name"].startswith("sample__") for item in schemas))

    def test_invalid_module_contract_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.py"
            path.write_text("TOOLS = []\ndef run(*args): pass\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-empty TOOLS"):
                load_module(path)


if __name__ == "__main__":
    unittest.main()
