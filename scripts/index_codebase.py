#!/usr/bin/env python3
"""Walk src/baps/**/*.py and emit a compact markdown index to stdout."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "baps"
TESTS = ROOT / "tests"


def _fmt_args(args: ast.arguments) -> str:
    parts: list[str] = []
    all_positional = args.posonlyargs + args.args
    n_defaults = len(args.defaults)
    default_offset = len(all_positional) - n_defaults

    for i, arg in enumerate(args.posonlyargs):
        s = arg.arg
        if arg.annotation:
            s += f": {ast.unparse(arg.annotation)}"
        if i >= default_offset:
            s += f" = {ast.unparse(args.defaults[i - default_offset])}"
        parts.append(s)
    if args.posonlyargs:
        parts.append("/")

    for i, arg in enumerate(args.args):
        idx = len(args.posonlyargs) + i
        s = arg.arg
        if arg.annotation:
            s += f": {ast.unparse(arg.annotation)}"
        if idx >= default_offset:
            s += f" = {ast.unparse(args.defaults[idx - default_offset])}"
        parts.append(s)

    if args.vararg:
        s = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            s += f": {ast.unparse(args.vararg.annotation)}"
        parts.append(s)
    elif args.kwonlyargs:
        parts.append("*")

    for i, arg in enumerate(args.kwonlyargs):
        s = arg.arg
        if arg.annotation:
            s += f": {ast.unparse(arg.annotation)}"
        if args.kw_defaults[i] is not None:
            s += f" = {ast.unparse(args.kw_defaults[i])}"
        parts.append(s)

    if args.kwarg:
        s = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            s += f": {ast.unparse(args.kwarg.annotation)}"
        parts.append(s)

    return ", ".join(parts)


def _fmt_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return f" -> {ast.unparse(node.returns)}" if node.returns else ""


def _first_doc_line(node: ast.AST) -> str | None:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return doc.strip().splitlines()[0]


def _skip_init(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if node.name != "__init__":
        return False
    if ast.get_docstring(node):
        return False
    args = node.args
    non_self = [a for a in args.posonlyargs + args.args if a.arg != "self"]
    return not (non_self or args.vararg or args.kwonlyargs or args.kwarg)


def _index_source_file(path: Path) -> list[str]:
    source = path.read_text()
    line_count = len(source.splitlines())
    rel = path.relative_to(ROOT)

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"### {rel} ({line_count} lines)", f"- (parse error: {exc.msg})"]

    imports: set[str] = set()
    classes: list[ast.ClassDef] = []
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.ClassDef):
            classes.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node)

    out = [f"### {rel} ({line_count} lines)"]

    if classes:
        out.append("- Classes:")
        for cls in classes:
            bases = ", ".join(ast.unparse(b) for b in cls.bases) if cls.bases else ""
            header = f"{cls.name}({bases})" if bases else cls.name
            doc = _first_doc_line(cls)
            entry = f"  - {header}"
            if doc:
                entry += f" — {doc}"
            out.append(entry)
            for item in cls.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _skip_init(item):
                    continue
                sig = f"{item.name}({_fmt_args(item.args)}){_fmt_return(item)}"
                mdoc = _first_doc_line(item)
                mentry = f"    - {sig}"
                if mdoc:
                    mentry += f" — {mdoc}"
                out.append(mentry)

    if functions:
        out.append("- Functions:")
        for fn in functions:
            sig = f"{fn.name}({_fmt_args(fn.args)}){_fmt_return(fn)}"
            doc = _first_doc_line(fn)
            entry = f"  - {sig}"
            if doc:
                entry += f" — {doc}"
            out.append(entry)

    if imports:
        out.append(f"- Imports: {', '.join(sorted(imports))}")

    return out


def _index_test_file(path: Path) -> list[str]:
    source = path.read_text()
    rel = path.relative_to(ROOT)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [f"- {rel.name} (parse error)"]

    test_fns: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                test_fns.append(node.name)

    out = [f"- **{rel.name}**"]
    for fn in test_fns:
        out.append(f"  - {fn}")
    return out


def main() -> None:
    source_files = sorted(SRC.rglob("*.py"))
    test_files = sorted(TESTS.rglob("*.py")) if TESTS.exists() else []

    # Filter out __init__.py that are empty or have only __all__
    def is_substantive(path: Path) -> bool:
        if path.name != "__init__.py":
            return True
        source = path.read_text().strip()
        if not source:
            return False
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return True
        # Only substantive if there's more than just imports and __all__
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign,
                                     ast.AnnAssign, ast.Expr)):
                return True
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id != "__all__":
                        return True
        return False

    lines: list[str] = ["# Codebase Index — src/baps", ""]

    for path in source_files:
        if not is_substantive(path):
            continue
        file_lines = _index_source_file(path)
        lines.extend(file_lines)
        lines.append("")

    if test_files:
        lines.append("## Tests")
        lines.append("")
        for path in test_files:
            lines.extend(_index_test_file(path))
            lines.append("")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
