"""Tree-sitter AST parsing for Python code chunk extraction.

Parses Python source into AST nodes (functions, classes, methods) and
produces ``CodeChunk`` objects with metadata for indexing and retrieval.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# tree-sitter imports are optional at module level — the parser is lazily initialized
_TS_AVAILABLE = False
try:
    import tree_sitter_python  # noqa: F401
    from tree_sitter import Language, Parser
    _TS_AVAILABLE = True
except ImportError:
    pass


@dataclass
class Symbol:
    """A named code symbol (function, class, method)."""
    name: str
    kind: str  # "function" | "class" | "method"
    start_line: int
    end_line: int
    params: str = ""


@dataclass
class CodeChunk:
    """A chunk of code extracted from a file, suitable for embedding."""
    file_path: str
    symbol_name: str
    symbol_kind: str  # "function" | "class" | "method" | "module"
    start_line: int
    end_line: int
    content: str
    content_hash: str = ""
    # Metadata for retrieval
    qualified_name: str = ""  # e.g. "ClassName.method_name"
    docstring: str = ""
    calls: list[str] = field(default_factory=list)

    def to_metadata(self) -> dict:
        return {
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "symbol_kind": self.symbol_kind,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "qualified_name": self.qualified_name,
            "content_hash": self.content_hash,
            "docstring": self.qualified_name,  # ChromaDB uses this for display
        }


# Node types that map to named symbols
_SYMBOL_NODE_TYPES = {
    "function_definition": "function",
    "class_definition": "class",
}

# For extracting parameters from function definitions
_PARAM_TYPES = {"parameters", "default_parameter", "typed_parameter", "identifier"}


class CodeParser:
    """Parse Python source files using tree-sitter and extract code chunks."""

    def __init__(self) -> None:
        self._parser: Parser | None = None
        self._language: Language | None = None
        if _TS_AVAILABLE:
            self._init_parser()

    def _init_parser(self) -> None:
        try:
            py_lang = tree_sitter_python.language()
            self._language = Language(py_lang)
            self._parser = Parser(self._language)
        except Exception:
            # Different tree-sitter versions have different APIs
            try:
                self._language = Language(tree_sitter_python.language())
                self._parser = Parser()
                self._parser.set_language(self._language)
            except Exception:
                self._parser = None

    @property
    def available(self) -> bool:
        return self._parser is not None

    def parse_file(self, file_path: str | Path) -> list[CodeChunk]:
        """Parse a file and return all code chunks."""
        file_path = Path(file_path)
        try:
            source = file_path.read_bytes()
        except OSError:
            return []

        rel_path = str(file_path)
        return self.parse_source(source, rel_path)

    def parse_source(self, source: bytes, file_path: str) -> list[CodeChunk]:
        """Parse source bytes and return code chunks."""
        if not self._parser:
            # Fallback: simple line-based chunking without AST
            return self._fallback_chunk(source, file_path)

        tree = self._parser.parse(source)
        root = tree.root_node

        chunks: list[CodeChunk] = []
        visited_nodes: set[int] = set()

        for node in self._walk(root):
            if node.id in visited_nodes:
                continue
            if node.type in _SYMBOL_NODE_TYPES:
                chunk = self._node_to_chunk(node, source, file_path)
                if chunk:
                    chunks.append(chunk)
                    visited_nodes.add(node.id)

        # If no symbols found, create a module-level chunk
        if not chunks:
            text = source.decode("utf-8", errors="replace")
            chunks.append(self._make_chunk(
                file_path, "<module>", "module",
                1, text.count("\n") + 1, text,
            ))

        return chunks

    def get_symbols(self, file_path: str | Path) -> list[Symbol]:
        """Extract symbol list from a file (for get_symbols tool)."""
        file_path = Path(file_path)
        try:
            source = file_path.read_bytes()
        except OSError:
            return []

        if not self._parser:
            return self._fallback_symbols(source)

        tree = self._parser.parse(source)
        root = tree.root_node
        symbols: list[Symbol] = []

        for node in self._walk(root):
            if node.type in _SYMBOL_NODE_TYPES:
                name_node = node.child_by_field_name("name")
                name = source[name_node.start_byte:name_node.end_byte].decode(
                    "utf-8", errors="replace"
                ) if name_node else "<anonymous>"
                kind = _SYMBOL_NODE_TYPES[node.type]
                params = self._extract_params(node, source)
                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    params=params,
                ))

        return symbols

    def _node_to_chunk(
        self, node, source: bytes, file_path: str
    ) -> CodeChunk | None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None

        name = source[name_node.start_byte:name_node.end_byte].decode(
            "utf-8", errors="replace"
        )
        kind = _SYMBOL_NODE_TYPES[node.type]
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        # Extract the source text for this node
        content = source[node.start_byte:node.end_byte].decode(
            "utf-8", errors="replace"
        )

        # Determine qualified name (for methods inside classes)
        qualified_name = name
        parent = node.parent
        while parent:
            if parent.type == "class_definition":
                parent_name_node = parent.child_by_field_name("name")
                if parent_name_node:
                    parent_name = source[
                        parent_name_node.start_byte:parent_name_node.end_byte
                    ].decode("utf-8", errors="replace")
                    qualified_name = f"{parent_name}.{name}"
                    kind = "method"
                break
            parent = parent.parent

        # Extract docstring (first string expression in body)
        docstring = self._extract_docstring(node, source)

        # Extract function/class calls (heuristic)
        calls = self._extract_calls(node, source)

        chunk = self._make_chunk(
            file_path, name, kind, start_line, end_line, content,
        )
        chunk.qualified_name = qualified_name
        chunk.docstring = docstring
        chunk.calls = calls
        return chunk

    def _make_chunk(
        self,
        file_path: str,
        symbol_name: str,
        symbol_kind: str,
        start_line: int,
        end_line: int,
        content: str,
    ) -> CodeChunk:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return CodeChunk(
            file_path=file_path,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            start_line=start_line,
            end_line=end_line,
            content=content,
            content_hash=content_hash,
            qualified_name=symbol_name,
        )

    def _extract_docstring(self, node, source: bytes) -> str:
        """Extract docstring from function/class body."""
        body = node.child_by_field_name("body")
        if not body:
            return ""
        for child in body.children:
            if child.type == "expression_statement":
                for expr_child in child.children:
                    if expr_child.type == "string":
                        raw = source[expr_child.start_byte:expr_child.end_byte].decode(
                            "utf-8", errors="replace"
                        )
                        return raw.strip().strip('"').strip("'").strip()
        return ""

    def _extract_calls(self, node, source: bytes) -> list[str]:
        """Heuristically extract function/method call names from a node."""
        calls: list[str] = []
        for child in self._walk(node):
            if child.type == "call":
                func = child.child_by_field_name("function")
                if func:
                    call_name = source[func.start_byte:func.end_byte].decode(
                        "utf-8", errors="replace"
                    )
                    if call_name not in calls:
                        calls.append(call_name)
        return calls

    def _extract_params(self, node, source: bytes) -> str:
        """Extract parameter list from a function node."""
        params_node = node.child_by_field_name("parameters")
        if not params_node:
            return ""
        params_text = source[params_node.start_byte:params_node.end_byte].decode(
            "utf-8", errors="replace"
        )
        return params_text.strip()

    def _walk(self, node):
        """Depth-first walk of tree-sitter nodes."""
        cursor = node.walk()
        if cursor.node is not None:
            yield cursor.node
        if cursor.goto_first_child():
            while True:
                yield from self._walk(cursor.node)
                if not cursor.goto_next_sibling():
                    break
            cursor.goto_parent()

    def _fallback_chunk(self, source: bytes, file_path: str) -> list[CodeChunk]:
        """Simple line-based chunking when tree-sitter is unavailable."""
        text = source.decode("utf-8", errors="replace")
        lines = text.split("\n")
        chunks: list[CodeChunk] = []
        chunk_size = 50
        for i in range(0, len(lines), chunk_size):
            chunk_lines = lines[i:i + chunk_size]
            content = "\n".join(chunk_lines)
            chunk = self._make_chunk(
                file_path, f"lines_{i+1}", "module",
                i + 1, min(i + chunk_size, len(lines)),
                content,
            )
            chunks.append(chunk)
        return chunks

    def _fallback_symbols(self, source: bytes) -> list[Symbol]:
        """Regex-based symbol extraction when tree-sitter is unavailable."""
        import re
        text = source.decode("utf-8", errors="replace")
        symbols: list[Symbol] = []
        for m in re.finditer(r"^(class|def)\s+(\w+)", text, re.MULTILINE):
            kind = "class" if m.group(1) == "class" else "function"
            line_num = text[:m.start()].count("\n") + 1
            symbols.append(Symbol(
                name=m.group(2), kind=kind,
                start_line=line_num, end_line=line_num,
            ))
        return symbols
