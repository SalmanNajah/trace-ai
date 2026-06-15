"""Local repository ingestion pipeline with Tree-sitter AST extraction.

Extracts code units (functions, classes, methods) from supported languages
using Tree-sitter for precise boundary detection. Falls back to Python's
built-in ast module or regex for cases where Tree-sitter fails.

Supported languages: Python, JavaScript, TypeScript (JSX/TSX included).
"""

from __future__ import annotations

import ast
import csv
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


class RepoIngestionError(Exception):
    pass


@dataclass(frozen=True)
class CodeUnit:
    project_id: str
    code_unit_id: str
    code_key: str
    file_path: str
    symbol: Optional[str]
    start_line: int
    end_line: int
    language: str
    chunk_type: str
    content: str
    commit_sha: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Tree-sitter setup (lazy-loaded)
# ---------------------------------------------------------------------------

_ts_parsers: dict[str, Any] = {}
_ts_available: Optional[bool] = None


def _get_ts_parser(language: str):
    """Return a Tree-sitter Parser for the given language, or None."""
    global _ts_available
    if _ts_available is False:
        return None

    if language in _ts_parsers:
        return _ts_parsers[language]

    try:
        import tree_sitter

        if language == "python":
            import tree_sitter_python
            lang = tree_sitter.Language(tree_sitter_python.language())
        elif language == "javascript":
            import tree_sitter_javascript
            lang = tree_sitter.Language(tree_sitter_javascript.language())
        elif language == "typescript":
            import tree_sitter_typescript
            lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
        elif language == "tsx":
            import tree_sitter_typescript
            lang = tree_sitter.Language(tree_sitter_typescript.language_tsx())
        else:
            return None

        parser = tree_sitter.Parser(lang)
        _ts_parsers[language] = parser
        _ts_available = True
        logger.info("Tree-sitter parser loaded for %s", language)
        return parser
    except Exception as exc:
        logger.warning("Tree-sitter unavailable for %s: %s — using fallback", language, exc)
        _ts_available = False
        return None


# ---------------------------------------------------------------------------
# Tree-sitter extraction
# ---------------------------------------------------------------------------


def _ts_extract_python(source: str, relative_path: str) -> list[dict]:
    """Extract functions and classes from Python using Tree-sitter."""
    parser = _get_ts_parser("python")
    if parser is None:
        return []

    tree = parser.parse(source.encode("utf-8"))
    units = []
    _ts_walk_python(tree.root_node, source.splitlines(), units, relative_path)
    return units


def _ts_walk_python(node, lines: list[str], units: list[dict], path: str, depth: int = 0):
    """Recursively walk Python AST nodes to extract functions and classes."""
    target_types = {"function_definition", "class_definition"}

    if node.type in target_types:
        # Get the name from the first identifier child
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break

        if name_node:
            symbol = name_node.text.decode("utf-8")
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            chunk_type = "function" if "function" in node.type else "class"
            content = "\n".join(lines[start_line - 1 : end_line]).strip()

            units.append({
                "symbol": symbol,
                "start_line": start_line,
                "end_line": end_line,
                "chunk_type": chunk_type,
                "content": content,
            })

    # Recurse into children
    for child in node.children:
        _ts_walk_python(child, lines, units, path, depth + 1)


def _ts_extract_js_ts(source: str, relative_path: str, language: str) -> list[dict]:
    """Extract functions and classes from JS/TS using Tree-sitter."""
    ts_lang = language
    if relative_path.endswith(".tsx") or relative_path.endswith(".jsx"):
        ts_lang = "tsx"

    parser = _get_ts_parser(ts_lang)
    if parser is None:
        return []

    tree = parser.parse(source.encode("utf-8"))
    units = []
    lines = source.splitlines()
    _ts_walk_js(tree.root_node, lines, units)
    return units


def _ts_walk_js(node, lines: list[str], units: list[dict], depth: int = 0):
    """Recursively walk JS/TS AST to extract functions, classes, and arrow fns."""

    # Named function declarations: function foo() { ... }
    if node.type == "function_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            _add_unit(units, lines, name_node.text.decode("utf-8"), node, "function")

    # Class declarations: class Foo { ... }
    elif node.type == "class_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            _add_unit(units, lines, name_node.text.decode("utf-8"), node, "class")

    # Method definitions inside classes: method() { ... }
    elif node.type == "method_definition":
        name_node = node.child_by_field_name("name")
        if name_node:
            _add_unit(units, lines, name_node.text.decode("utf-8"), node, "method")

    # Arrow functions assigned to variables: const foo = () => { ... }
    elif node.type == "lexical_declaration" or node.type == "variable_declaration":
        for declarator in node.children:
            if declarator.type == "variable_declarator":
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                if name_node and value_node and value_node.type == "arrow_function":
                    _add_unit(units, lines, name_node.text.decode("utf-8"), node, "function")

    # Export declarations: export function foo() / export default class
    elif node.type == "export_statement":
        for child in node.children:
            _ts_walk_js(child, lines, units, depth + 1)
        return  # Already recursed

    # Recurse
    for child in node.children:
        _ts_walk_js(child, lines, units, depth + 1)


def _add_unit(units: list[dict], lines: list[str], symbol: str, node, chunk_type: str):
    """Helper to add an extracted unit."""
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    content = "\n".join(lines[start_line - 1 : end_line]).strip()
    units.append({
        "symbol": symbol,
        "start_line": start_line,
        "end_line": end_line,
        "chunk_type": chunk_type,
        "content": content,
    })


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class LocalRepoIngestionPipeline:
    SUPPORTED_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".rb": "ruby",
        ".go": "go",
        ".rs": "rust",
        ".cs": "csharp",
        ".php": "php",
    }
    EXCLUDED_DIRS = {
        ".git",
        ".next",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "out",
        "target",
        "venv",
    }
    EXCLUDED_FILE_PATTERNS = [
        re.compile(r".*\.min\.(js|css)$", re.IGNORECASE),
        re.compile(r".*\.map$", re.IGNORECASE),
        re.compile(r"^google[a-z0-9]+\.html$", re.IGNORECASE),
        re.compile(r"^sw\.js$", re.IGNORECASE),
        re.compile(r"^favicon\.ico$", re.IGNORECASE),
        # Framework config / boilerplate — no application logic
        re.compile(r"^next\.config\.(ts|js|mjs)$", re.IGNORECASE),
        re.compile(r"^next-env\.d\.ts$", re.IGNORECASE),
        re.compile(r"^tailwind\.config\.(ts|js)$", re.IGNORECASE),
        re.compile(r"^postcss\.config\.(ts|js|mjs|cjs)$", re.IGNORECASE),
        re.compile(r"^tsconfig.*\.json$", re.IGNORECASE),
        re.compile(r"^\.eslintrc.*$", re.IGNORECASE),
        re.compile(r"^eslint\.config\.(ts|js|mjs)$", re.IGNORECASE),
        re.compile(r"^prettier\.config\.(ts|js)$", re.IGNORECASE),
        re.compile(r"^\.prettierrc.*$", re.IGNORECASE),
        re.compile(r"^jest\.config\.(ts|js)$", re.IGNORECASE),
        re.compile(r"^vite\.config\.(ts|js)$", re.IGNORECASE),
        re.compile(r"^package-lock\.json$", re.IGNORECASE),
        re.compile(r"^yarn\.lock$", re.IGNORECASE),
        re.compile(r"^pnpm-lock\.yaml$", re.IGNORECASE),
        re.compile(r"^\.env.*$", re.IGNORECASE),
        re.compile(r"^Dockerfile$", re.IGNORECASE),
        re.compile(r"^docker-compose.*\.ya?ml$", re.IGNORECASE),
        re.compile(r"^Makefile$", re.IGNORECASE),
    ]
    MAX_FILE_SIZE_MB = 1
    MAX_FILE_CHUNK_LEN = 1200

    def __init__(self, data_root: Union[str, Path]):
        self.data_root = Path(data_root).resolve()
        self.interim_root = self.data_root / "interim" / "code_units"
        self.processed_root = self.data_root / "processed" / "projects"

    def ingest(
        self,
        project_id: str,
        repo_path: Union[str, Path],
        version: Optional[int] = None,
        commit_sha: Optional[str] = None,
    ) -> dict[str, Union[str, int]]:
        root = Path(repo_path).resolve()
        if not root.exists() or not root.is_dir():
            raise RepoIngestionError(f"Repository path not found: {root}")

        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        interim_project_dir = self.interim_root / project_id
        processed_project_dir = self.processed_root / project_id
        interim_project_dir.mkdir(parents=True, exist_ok=True)
        processed_project_dir.mkdir(parents=True, exist_ok=True)

        version_value = version if version is not None else self._infer_next_version(processed_project_dir)
        code_unit_rows = self._extract_code_units(
            project_id=project_id,
            repo_root=root,
            created_at=now.isoformat(),
            commit_sha=commit_sha,
        )
        if not code_unit_rows:
            raise RepoIngestionError("No supported code units found in repository.")

        interim_path = interim_project_dir / f"code_units_{stamp}.csv"
        processed_path = processed_project_dir / f"code_units_v{version_value}.csv"
        self._write_csv(interim_path, code_unit_rows)
        self._write_csv(processed_path, code_unit_rows)

        return {
            "project_id": project_id,
            "version": version_value,
            "code_units_written": len(code_unit_rows),
            "interim_csv": str(interim_path),
            "processed_csv": str(processed_path),
        }

    def _extract_code_units(
        self,
        project_id: str,
        repo_root: Path,
        created_at: str,
        commit_sha: Optional[str],
    ) -> list[CodeUnit]:
        units: list[CodeUnit] = []
        code_index = 1
        for file_path in repo_root.rglob("*"):
            if not file_path.is_file():
                continue
            if self._is_excluded(file_path, repo_root):
                continue
            extension = file_path.suffix.lower()
            language = self.SUPPORTED_EXTENSIONS.get(extension)
            if language is None:
                continue
            if (file_path.stat().st_size / (1024 * 1024)) > self.MAX_FILE_SIZE_MB:
                continue

            relative_path = str(file_path.relative_to(repo_root))
            source = file_path.read_text(encoding="utf-8", errors="ignore")
            extracted = self._extract_for_file(relative_path, language, source)
            for entry in extracted:
                units.append(
                    CodeUnit(
                        project_id=project_id,
                        code_unit_id=str(uuid.uuid4()),
                        code_key=f"CODE-{code_index:03d}",
                        file_path=relative_path,
                        symbol=entry["symbol"],
                        start_line=entry["start_line"],
                        end_line=entry["end_line"],
                        language=language,
                        chunk_type=entry["chunk_type"],
                        content=entry["content"],
                        commit_sha=commit_sha,
                        created_at=created_at,
                    )
                )
                code_index += 1
        return units

    def _extract_for_file(self, relative_path: str, language: str, source: str) -> list[dict]:
        """Extract code units using Tree-sitter, with fallback to built-in parsers."""
        if language == "python":
            ts_units = _ts_extract_python(source, relative_path)
            if ts_units:
                return ts_units
            # Fallback to Python ast module
            return self._extract_python_units_fallback(relative_path, source)

        if language in {"javascript", "typescript"}:
            ts_units = _ts_extract_js_ts(source, relative_path, language)
            if ts_units:
                return ts_units
            return self._extract_js_ts_units_fallback(relative_path, source)

        if language in {"java", "c", "cpp"}:
            return self._extract_java_c_units(relative_path, source, language)

        if language in {"ruby", "go", "rust", "csharp", "php"}:
            return self._extract_generic_units(relative_path, source, language)

        return [self._file_chunk(relative_path, source, language)]

    # --- Fallback extractors (kept for resilience) ---

    def _extract_python_units_fallback(self, relative_path: str, source: str) -> list[dict]:
        lines = source.splitlines()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return [self._file_chunk(relative_path, source, "python")]

        units = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start_line = int(getattr(node, "lineno", 1))
                end_line = int(getattr(node, "end_lineno", start_line))
                content = self._line_slice(lines, start_line, end_line)
                units.append({
                    "symbol": node.name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "chunk_type": "function",
                    "content": content,
                })
            elif isinstance(node, ast.ClassDef):
                start_line = int(getattr(node, "lineno", 1))
                end_line = int(getattr(node, "end_lineno", start_line))
                content = self._line_slice(lines, start_line, end_line)
                units.append({
                    "symbol": node.name,
                    "start_line": start_line,
                    "end_line": end_line,
                    "chunk_type": "class",
                    "content": content,
                })
        if units:
            return units
        return [self._file_chunk(relative_path, source, "python")]

    def _extract_js_ts_units_fallback(self, relative_path: str, source: str) -> list[dict]:
        lines = source.splitlines()
        patterns = [
            re.compile(r"^\s*function\s+([A-Za-z0-9_$]+)\s*\(", re.MULTILINE),
            re.compile(r"^\s*class\s+([A-Za-z0-9_$]+)\s*", re.MULTILINE),
            re.compile(r"^\s*(const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*\([^)]*\)\s*=>", re.MULTILINE),
        ]
        units = []
        for pattern in patterns:
            for match in pattern.finditer(source):
                symbol = match.group(1) if len(match.groups()) == 1 else match.group(2)
                start_line = source[: match.start()].count("\n") + 1
                end_line = min(start_line + 20, max(1, len(lines)))
                units.append({
                    "symbol": symbol,
                    "start_line": start_line,
                    "end_line": end_line,
                    "chunk_type": "function" if "class" not in pattern.pattern else "class",
                    "content": self._line_slice(lines, start_line, end_line),
                })
        if units:
            return units
        return [self._file_chunk(relative_path, source, "typescript")]

    def _extract_java_c_units(self, relative_path: str, source: str, language: str) -> list[dict]:
        """Extract classes and methods from Java/C/C++ using regex."""
        lines = source.splitlines()
        patterns = [
            # Java/C++ class declarations
            re.compile(r"^\s*(?:public|private|protected)?\s*(?:abstract|final)?\s*class\s+([A-Za-z0-9_]+)", re.MULTILINE),
            # Java/C++ method declarations (with return type)
            re.compile(r"^\s*(?:public|private|protected)?\s*(?:static)?\s*(?:final)?\s*[A-Za-z0-9_<>\[\]]+\s+([A-Za-z0-9_]+)\s*\(", re.MULTILINE),
        ]
        units = []
        for pattern in patterns:
            for match in pattern.finditer(source):
                symbol = match.group(1)
                if symbol in {"if", "for", "while", "switch", "catch", "return", "new", "class"}:
                    continue
                start_line = source[: match.start()].count("\n") + 1
                end_line = min(start_line + 30, len(lines))
                chunk_type = "class" if "class" in match.group(0) else "method"
                units.append({
                    "symbol": symbol,
                    "start_line": start_line,
                    "end_line": end_line,
                    "chunk_type": chunk_type,
                    "content": self._line_slice(lines, start_line, end_line),
                })
        if units:
            return units
        return [self._file_chunk(relative_path, source, language)]

    def _extract_generic_units(self, relative_path: str, source: str, language: str) -> list[dict]:
        """Extract logical blocks like classes, structs, methods, or functions using regular expressions."""
        lines = source.splitlines()
        patterns_map = {
            "ruby": [
                re.compile(r"^\s*class\s+([A-Za-z0-9_:]+)", re.MULTILINE),
                re.compile(r"^\s*def\s+([A-Za-z0-9_?!]+)", re.MULTILINE),
            ],
            "go": [
                re.compile(r"^\s*type\s+([A-Za-z0-9_]+)\s+struct", re.MULTILINE),
                re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\s*\(", re.MULTILINE),
            ],
            "rust": [
                re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z0-9_]+)", re.MULTILINE),
                re.compile(r"^\s*(?:pub\s+)?(?:const\s+)?fn\s+([A-Za-z0-9_]+)", re.MULTILINE),
            ],
            "csharp": [
                re.compile(r"^\s*(?:public|private|internal|protected)?\s*(?:static|readonly)?\s*class\s+([A-Za-z0-9_]+)", re.MULTILINE),
                re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static|async)?\s*[A-Za-z0-9_<>\[\]]+\s+([A-Za-z0-9_]+)\s*\(", re.MULTILINE),
            ],
            "php": [
                re.compile(r"^\s*(?:abstract)?\s*class\s+([A-Za-z0-9_]+)", re.MULTILINE),
                re.compile(r"^\s*(?:public|private|protected)?\s*(?:static)?\s*function\s+([A-Za-z0-9_]+)", re.MULTILINE),
            ],
        }

        patterns = patterns_map.get(language, [])
        units = []
        for pattern in patterns:
            for match in pattern.finditer(source):
                symbol = match.group(1)
                if symbol in {"if", "for", "while", "switch", "catch", "return", "new", "class", "fn", "def", "func"}:
                    continue
                start_line = source[: match.start()].count("\n") + 1
                end_line = min(start_line + 30, len(lines))
                chunk_type = "class" if "class" in match.group(0) or "struct" in match.group(0) else "method"
                units.append({
                    "symbol": symbol,
                    "start_line": start_line,
                    "end_line": end_line,
                    "chunk_type": chunk_type,
                    "content": self._line_slice(lines, start_line, end_line),
                })
        if units:
            return units
        return [self._file_chunk(relative_path, source, language)]

    # --- Helpers ---

    def _file_chunk(self, relative_path: str, source: str, _language: str) -> dict:
        line_count = max(1, len(source.splitlines()))
        return {
            "symbol": Path(relative_path).name,
            "start_line": 1,
            "end_line": min(40, line_count),
            "chunk_type": "file",
            "content": source[: self.MAX_FILE_CHUNK_LEN],
        }

    def _line_slice(self, lines: list[str], start_line: int, end_line: int) -> str:
        start_index = max(1, start_line) - 1
        end_index = min(len(lines), max(start_line, end_line))
        return "\n".join(lines[start_index:end_index]).strip()

    def _is_excluded(self, file_path: Path, repo_root: Path) -> bool:
        relative = file_path.relative_to(repo_root)
        parts = {part.lower() for part in relative.parts}
        if parts & self.EXCLUDED_DIRS:
            return True
        file_name = file_path.name
        for pattern in self.EXCLUDED_FILE_PATTERNS:
            if pattern.match(file_name):
                return True
        return False

    def _write_csv(self, path: Path, units: list[CodeUnit]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "project_id",
                    "code_unit_id",
                    "code_key",
                    "file_path",
                    "symbol",
                    "start_line",
                    "end_line",
                    "language",
                    "chunk_type",
                    "content",
                    "commit_sha",
                    "created_at",
                ]
            )
            for unit in units:
                writer.writerow(
                    [
                        unit.project_id,
                        unit.code_unit_id,
                        unit.code_key,
                        unit.file_path,
                        unit.symbol or "",
                        unit.start_line,
                        unit.end_line,
                        unit.language,
                        unit.chunk_type,
                        unit.content,
                        unit.commit_sha or "",
                        unit.created_at,
                    ]
                )

    def _infer_next_version(self, processed_project_dir: Path) -> int:
        existing = sorted(processed_project_dir.glob("code_units_v*.csv"))
        if not existing:
            return 1
        versions = []
        for file_path in existing:
            match = re.search(r"code_units_v(\d+)\.csv$", file_path.name)
            if match:
                versions.append(int(match.group(1)))
        return (max(versions) + 1) if versions else 1
