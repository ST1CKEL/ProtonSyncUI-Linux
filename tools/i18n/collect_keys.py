"""Collect every tr() key: literal arguments plus module-level constants passed by name."""
import ast, sys
from pathlib import Path

def collect(root: Path) -> dict[str, str]:
    keys: dict[str, str] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        consts = {}
        for node in tree.body:
            target = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                target, value = node.target.id, node.value
            if target is None:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                consts[target] = [value.value]
            elif isinstance(value, ast.Dict):
                consts[target] = [v.value for v in value.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr" and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.setdefault(arg.value, str(path))
                elif isinstance(arg, ast.Name):
                    for value in consts.get(arg.id, []):
                        keys.setdefault(value, str(path))
                elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "get":
                    owner = arg.func.value
                    if isinstance(owner, ast.Name):
                        for value in consts.get(owner.id, []):
                            keys.setdefault(value, str(path))
    return keys

if __name__ == "__main__":
    keys = collect(Path(sys.argv[1]))
    for key in keys:
        print(repr(key))
    print(len(keys), file=sys.stderr)
