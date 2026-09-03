"""Guard the retain-only policy at the production call-site level."""

import ast
from pathlib import Path


def test_production_sync_contains_no_delete_calls():
    package = Path(__file__).parents[1] / 'netbox_pve_sync'
    delete_calls = []

    for path in package.glob('*.py'):
        tree = ast.parse(
            path.read_text(encoding='utf-8'),
            filename=str(path),
        )

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'delete'
            ):
                delete_calls.append(
                    f'{path.name}:{node.lineno}'
                )

    assert delete_calls == []
