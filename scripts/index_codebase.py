#!/usr/bin/env python3
"""Generate compact markdown indexes for src/baps and tests using AST only."""

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "baps"
TESTS = ROOT / "tests"
API_INDEX = ROOT / "CODEBASE_API_INDEX.md"
TEST_INDEX = ROOT / "CODEBASE_TEST_INDEX.md"
IMPORTANT_FIELD_CLASSES = {
    "GameSpec",
    "State",
    "RuntimeContext",
    "RunConfig",
    "RoleConfig",
    "PlayGameContext",
    "VerificationResult",
    "SummarizationContext",
    "ToolDefinition",
    "ToolCall",
    "ToolCallRecord",
}


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


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = base
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ast.unparse(base)


def _is_dataclass(cls: ast.ClassDef) -> bool:
    for dec in cls.decorator_list:
        if _base_name(dec).endswith("dataclass"):
            return True
    return False


def _is_protocol_class(cls: ast.ClassDef) -> bool:
    return any(_base_name(base).endswith("Protocol") for base in cls.bases)


def _class_fields(cls: ast.ClassDef) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for item in cls.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            fields.append((item.target.id, ast.unparse(item.annotation)))
    return fields


def _should_show_fields(cls: ast.ClassDef, fields: list[tuple[str, str]]) -> bool:
    if not fields:
        return False
    if cls.name in IMPORTANT_FIELD_CLASSES:
        return True
    if _is_protocol_class(cls):
        return True
    base_leafs = {_base_name(base).split(".")[-1] for base in cls.bases}
    if "BaseModel" in base_leafs:
        return True
    if _is_dataclass(cls):
        return True
    return False


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

    def append_inline_doc(entry: str, node: ast.AST) -> str:
        doc = _first_doc_line(node)
        if doc is None:
            return entry
        return f'{entry} — "{doc}"'

    if classes:
        out.append("- Classes:")
        for cls in classes:
            bases = ", ".join(ast.unparse(b) for b in cls.bases) if cls.bases else ""
            header = f"{cls.name}({bases})" if bases else cls.name
            entry = append_inline_doc(f"  - {header}", cls)
            out.append(entry)
            fields = _class_fields(cls)
            if _should_show_fields(cls, fields):
                out.append("    - Fields:")
                for field_name, field_type in fields:
                    out.append(f"      - {field_name}: {field_type}")
            for item in cls.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _skip_init(item):
                    continue
                sig = f"{item.name}({_fmt_args(item.args)}){_fmt_return(item)}"
                mentry = append_inline_doc(f"    - {sig}", item)
                out.append(mentry)

    if functions:
        out.append("- Functions:")
        for fn in functions:
            sig = f"{fn.name}({_fmt_args(fn.args)}){_fmt_return(fn)}"
            entry = append_inline_doc(f"  - {sig}", fn)
            out.append(entry)

    if imports:
        out.append(f"- Imports: {', '.join(sorted(imports))}")

    return out


def _is_fixture_fn(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        name = _base_name(dec)
        if name.endswith("fixture") or name.endswith("pytest.fixture"):
            return True
        if isinstance(dec, ast.Call):
            called = _base_name(dec.func)
            if called.endswith("fixture") or called.endswith("pytest.fixture"):
                return True
    return False


def _index_test_module(path: Path) -> list[str]:
    source = path.read_text()
    line_count = len(source.splitlines())
    rel = path.relative_to(ROOT)
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"### {rel} ({line_count} lines)", f"- (parse error: {exc.msg})"]

    imports: set[str] = set()
    classes: list[ast.ClassDef] = []
    test_functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    fixtures: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

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
            if _is_fixture_fn(node):
                fixtures.append(node)
            elif node.name.startswith("test_"):
                test_functions.append(node)

    out = [f"### {rel} ({line_count} lines)"]

    def append_inline_doc(entry: str, node: ast.AST) -> str:
        doc = _first_doc_line(node)
        if doc is None:
            return entry
        return f'{entry} — "{doc}"'

    if classes:
        out.append("- Classes:")
        for cls in classes:
            bases = ", ".join(ast.unparse(b) for b in cls.bases) if cls.bases else ""
            header = f"{cls.name}({bases})" if bases else cls.name
            out.append(append_inline_doc(f"  - {header}", cls))
            fields = _class_fields(cls)
            if _should_show_fields(cls, fields):
                out.append("    - Fields:")
                for field_name, field_type in fields:
                    out.append(f"      - {field_name}: {field_type}")
            for item in cls.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _is_fixture_fn(item) or item.name.startswith("test_"):
                    sig = f"{item.name}({_fmt_args(item.args)}){_fmt_return(item)}"
                    out.append(append_inline_doc(f"    - {sig}", item))

    if test_functions:
        out.append("- Test Functions:")
        for fn in test_functions:
            sig = f"{fn.name}({_fmt_args(fn.args)}){_fmt_return(fn)}"
            out.append(append_inline_doc(f"  - {sig}", fn))

    if fixtures:
        out.append("- Fixtures:")
        for fx in fixtures:
            sig = f"{fx.name}({_fmt_args(fx.args)}){_fmt_return(fx)}"
            out.append(append_inline_doc(f"  - {sig}", fx))

    if imports:
        out.append(f"- Imports: {', '.join(sorted(imports))}")

    return out


def _is_substantive_source_file(path: Path) -> bool:
    if path.name != "__init__.py":
        return True
    source = path.read_text().strip()
    if not source:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return True
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign,
                                 ast.AnnAssign, ast.Expr)):
            return True
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id != "__all__":
                    return True
    return False


def _build_api_index_lines(source_files: list[Path]) -> list[str]:
    lines: list[str] = ["# Codebase API Index — src/baps", ""]
    protocol_entries: list[tuple[str, str]] = []
    for path in source_files:
        if not _is_substantive_source_file(path):
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and _is_protocol_class(node):
                protocol_entries.append((node.name, str(path.relative_to(ROOT))))

    if protocol_entries:
        lines.append("## Protocols")
        for name, rel in sorted(protocol_entries):
            lines.append(f"- {name} — {rel}")
        lines.append("")

    for path in source_files:
        if not _is_substantive_source_file(path):
            continue
        lines.extend(_index_source_file(path))
        lines.append("")
    return lines


def _build_test_index_lines(test_files: list[Path]) -> list[str]:
    lines: list[str] = ["# Codebase Test Index — tests", ""]
    for path in test_files:
        lines.extend(_index_test_module(path))
        lines.append("")
    return lines


def main() -> None:
    source_files = sorted(SRC.rglob("*.py"))
    test_files = sorted(TESTS.rglob("*.py")) if TESTS.exists() else []
    api_lines = _build_api_index_lines(source_files)
    test_lines = _build_test_index_lines(test_files)

    API_INDEX.write_text("\n".join(api_lines).rstrip() + "\n", encoding="utf-8")
    TEST_INDEX.write_text("\n".join(test_lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {API_INDEX.relative_to(ROOT)}")
    print(f"Wrote {TEST_INDEX.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
