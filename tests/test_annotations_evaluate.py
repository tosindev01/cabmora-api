"""Annotations that work on 3.14 here and crash on 3.12 in the container.

Local Python is 3.14, where PEP 649 defers annotation evaluation; the
Dockerfile is 3.12, where annotations are evaluated as each `def` runs. Code
that reads fine in development therefore dies at import in production, and the
only symptom is a crashed container.

This has now cost three outages:

* a provider in `deps.py` placed above the repository alias it named
* the same again after a refactor moved one
* `ManageAccessGroups.list` shadowing the builtin, so a later method annotated
  `-> list[UUID]` tried to subscript the method

`test_deps_resolve` catches none of them: it runs after the module has already
imported successfully. These are static checks, so they fail in the suite
rather than on a deploy.
"""

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parent.parent / "app"


def _modules() -> list[tuple[pathlib.Path, ast.Module]]:
    return [(f, ast.parse(f.read_text())) for f in sorted(APP.rglob("*.py"))]


def test_no_annotation_names_a_module_level_name_defined_later():
    """`def f(x: Dep)` where `Dep = ...` comes further down the file.

    Fine on 3.14, `NameError` at import on 3.12.
    """
    problems = []
    for path, tree in _modules():
        bound: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.setdefault(target.id, node.lineno)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.setdefault(node.name, node.lineno)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound.setdefault(alias.asname or alias.name.split(".")[0], node.lineno)

        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            annotations = [a.annotation for a in node.args.args if a.annotation]
            if node.returns:
                annotations.append(node.returns)
            for annotation in annotations:
                for name in ast.walk(annotation):
                    if (
                        isinstance(name, ast.Name)
                        and bound.get(name.id, 0) > node.lineno
                    ):
                        problems.append(
                            f"{path.name}:{node.lineno} {node.name}() names "
                            f"`{name.id}`, which is defined at line {bound[name.id]}"
                        )
    assert not problems, "\n".join(problems)


def test_every_name_in_an_annotation_exists_in_its_module():
    """`Annotated[ConfirmConsultation, ...]` with no import for it.

    The previous check only caught names bound *later* in the file, so a name
    bound nowhere at all slipped through and took production down a second
    time on 2026-10-03. On 3.14 the annotation is never evaluated and the
    missing import is invisible; on 3.12 it is a NameError at import.

    Compiles each annotation against the names the module actually has:
    its imports, its own definitions, and the builtins.
    """
    import builtins

    problems = []
    for path, tree in _modules():
        available = set(dir(builtins))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    available.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                available.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        available.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                available.add(node.target.id)
            elif isinstance(node, (ast.arg,)):
                available.add(node.arg)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            annotations = [
                a.annotation
                for a in node.args.args + node.args.kwonlyargs
                if a.annotation
            ]
            if node.returns:
                annotations.append(node.returns)
            for annotation in annotations:
                for name in ast.walk(annotation):
                    # String annotations are never evaluated eagerly, so a
                    # forward reference in quotes is fine and is skipped.
                    if isinstance(name, ast.Constant):
                        break
                    if isinstance(name, ast.Name) and name.id not in available:
                        problems.append(
                            f"{path.name}:{node.lineno} {node.name}() annotates "
                            f"`{name.id}`, which this module never defines or imports"
                        )
    assert not problems, "\n".join(problems)


def test_no_class_shadows_a_name_its_own_annotations_subscript():
    """`def list(...)` then `-> list[UUID]` on a later method.

    Inside the class body `list` is the method by then, so 3.12 raises
    `TypeError: 'function' object is not subscriptable` while building the
    class. This is what took production down on 2026-10-02.
    """
    problems = []
    for path, tree in _modules():
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            rebound: set[str] = set()
            for stmt in cls.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    annotations = [
                        a.annotation
                        for a in stmt.args.args + stmt.args.kwonlyargs
                        if a.annotation
                    ]
                    if stmt.returns:
                        annotations.append(stmt.returns)
                    for annotation in annotations:
                        for node in ast.walk(annotation):
                            if (
                                isinstance(node, ast.Subscript)
                                and isinstance(node.value, ast.Name)
                                and node.value.id in rebound
                            ):
                                problems.append(
                                    f"{path.name}:{stmt.lineno} "
                                    f"{cls.name}.{stmt.name} annotates "
                                    f"`{node.value.id}[...]` after the class "
                                    f"rebinds `{node.value.id}`"
                                )
                    rebound.add(stmt.name)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            rebound.add(target.id)
    assert not problems, "\n".join(problems)
