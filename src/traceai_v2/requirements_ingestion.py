from __future__ import annotations

import csv
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

from .csv_utils import configure_csv_field_limit


class IngestionError(Exception):
    pass


@dataclass(frozen=True)
class RequirementCandidate:
    text: str
    rule_used: str
    accepted: bool
    notes: str


class RequirementsIngestionPipeline:
    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
    NOISE_EXACT = {
        "introduction",
        "scope",
        "table of contents",
        "contents",
    }
    KEYWORDS = ("shall", "must", "should")
    MAX_FILE_SIZE_MB = 10
    MAX_CHUNK_LEN = 600

    def __init__(self, data_root: Union[str, Path]):
        self.data_root = Path(data_root).resolve()
        self.raw_root = self.data_root / "raw" / "uploads"
        self.interim_root = self.data_root / "interim" / "requirements"
        self.processed_root = self.data_root / "processed" / "projects"

    def ingest(
        self,
        project_id: str,
        input_file: Union[str, Path],
        source_doc: Optional[str] = None,
        version: Optional[int] = None,
    ) -> dict[str, Union[str, int]]:
        file_path = Path(input_file).resolve()
        self._validate_input_file(file_path)

        now = datetime.now(timezone.utc)
        source_doc_name = source_doc or file_path.name

        raw_project_dir = self.raw_root / project_id
        interim_project_dir = self.interim_root / project_id
        processed_project_dir = self.processed_root / project_id
        raw_project_dir.mkdir(parents=True, exist_ok=True)
        interim_project_dir.mkdir(parents=True, exist_ok=True)
        processed_project_dir.mkdir(parents=True, exist_ok=True)

        stamped_name = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{file_path.name}"
        raw_copy_path = raw_project_dir / stamped_name
        shutil.copy2(file_path, raw_copy_path)

        extracted_text = self._extract_text(file_path)
        normalized_text = self._normalize_text(extracted_text)
        if not normalized_text.strip():
            raise IngestionError("Uploaded file is empty.")

        candidates = self._generate_candidates(normalized_text)
        accepted_chunks = [candidate.text for candidate in candidates if candidate.accepted]
        if not accepted_chunks:
            raise IngestionError(
                "No requirement statements detected. Use sentences with shall/must/should or requirement IDs."
            )

        run_stamp = now.strftime("%Y%m%dT%H%M%SZ")
        interim_text_path = interim_project_dir / f"extracted_text_{run_stamp}.txt"
        interim_chunks_path = interim_project_dir / f"chunks_{run_stamp}.csv"
        interim_text_path.write_text(normalized_text, encoding="utf-8")
        self._write_interim_chunks(interim_chunks_path, project_id, candidates)

        next_version = version if version is not None else self._infer_next_version(processed_project_dir)
        processed_path = processed_project_dir / f"requirements_v{next_version}.csv"
        records_written = self._write_processed_requirements(
            project_id=project_id,
            source_doc=source_doc_name,
            version=next_version,
            accepted_chunks=accepted_chunks,
            processed_project_dir=processed_project_dir,
            output_csv_path=processed_path,
            created_at=now.isoformat(),
        )

        return {
            "project_id": project_id,
            "version": next_version,
            "requirements_written": records_written,
            "raw_file": str(raw_copy_path),
            "interim_text": str(interim_text_path),
            "interim_chunks": str(interim_chunks_path),
            "processed_csv": str(processed_path),
        }

    def _validate_input_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            raise IngestionError(f"Input file not found: {file_path}")
        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise IngestionError("Unsupported file type. Allowed: pdf, docx, txt, md")
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.MAX_FILE_SIZE_MB:
            raise IngestionError("File too large for Phase 1 limit.")

    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        try:
            if suffix in {".txt", ".md"}:
                return file_path.read_text(encoding="utf-8", errors="ignore")
            if suffix == ".pdf":
                try:
                    from pypdf import PdfReader
                except ImportError as exc:
                    raise IngestionError(
                        "PDF reader dependency missing. Install `pypdf` to ingest PDF files."
                    ) from exc
                reader = PdfReader(str(file_path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            if suffix == ".docx":
                try:
                    from docx import Document
                except ImportError as exc:
                    raise IngestionError(
                        "DOCX reader dependency missing. Install `python-docx` to ingest DOCX files."
                    ) from exc
                document = Document(str(file_path))
                return "\n".join(paragraph.text for paragraph in document.paragraphs)
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError(
                "Could not read text from file. Please upload text-based PDF/DOCX/TXT/MD."
            ) from exc
        raise IngestionError("Unsupported file type. Allowed: pdf, docx, txt, md")

    ACTION_VERBS = ("will", "can", "allows", "supports", "manages", "provides", "enables", "maintains", "records", "adjusts", "includes")

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        lines = [line.strip() for line in text.split("\n")]
        normalized_lines: list[str] = []
        for line in lines:
            if line:
                normalized_lines.append(line)
            elif normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
        return "\n".join(normalized_lines).strip()

    def _generate_candidates(self, normalized_text: str) -> list[RequirementCandidate]:
        lines = normalized_text.split("\n")
        candidates: list[RequirementCandidate] = []
        seen_text: set[str] = set()

        for line in lines:
            detected = self._detect_line(line)
            if detected is None:
                continue
            for chunk in self._apply_chunk_rules(detected.text):
                normalized_chunk = self._canonical_compare_text(chunk)
                if not normalized_chunk or normalized_chunk in seen_text:
                    continue
                seen_text.add(normalized_chunk)
                accepted, notes = self._quality_filter(chunk)
                candidates.append(
                    RequirementCandidate(
                        text=chunk,
                        rule_used=detected.rule_used,
                        accepted=accepted,
                        notes=notes,
                    )
                )

        if not [candidate for candidate in candidates if candidate.accepted]:
            fallback_chunks = self._fallback_paragraphs(normalized_text)
            for chunk in fallback_chunks:
                normalized_chunk = self._canonical_compare_text(chunk)
                if normalized_chunk in seen_text:
                    continue
                seen_text.add(normalized_chunk)
                accepted, notes = self._quality_filter(chunk)
                candidates.append(
                    RequirementCandidate(
                        text=chunk,
                        rule_used="fallback_paragraph",
                        accepted=accepted,
                        notes=notes,
                    )
                )
        return candidates

    def _detect_line(self, line: str) -> Optional[RequirementCandidate]:
        clean_line = line.strip()
        if not clean_line:
            return None
        if re.match(r"^(FR|NFR|REQ|R|UC|US|FEAT)[-_ ]?\d+", clean_line, flags=re.IGNORECASE):
            return RequirementCandidate(text=clean_line, rule_used="explicit_id", accepted=True, notes="")
        if re.match(r"^[-*+•]\s+", clean_line) or re.match(r"^\d+[\)\.\-: ]+", clean_line):
            return RequirementCandidate(text=clean_line, rule_used="list_rule", accepted=True, notes="")
        lowercase = clean_line.lower()
        if any(keyword in lowercase for keyword in self.KEYWORDS) or any(verb in lowercase for verb in self.ACTION_VERBS):
            return RequirementCandidate(text=clean_line, rule_used="keyword_rule", accepted=True, notes="")
        return None

    def _apply_chunk_rules(self, text: str) -> list[str]:
        chunks = [chunk.strip() for chunk in re.split(r"(?<=[.!?])\s+", text) if chunk.strip()]
        if not chunks:
            chunks = [text.strip()]

        merged: list[str] = []
        index = 0
        while index < len(chunks):
            current = chunks[index]
            if len(current) < 40 and index + 1 < len(chunks):
                current = f"{current} {chunks[index + 1]}".strip()
                index += 1
            merged.append(current)
            index += 1

        output: list[str] = []
        for item in merged:
            if len(item) <= self.MAX_CHUNK_LEN:
                output.append(item)
                continue
            output.extend(self._split_long_chunk(item))
        return output

    def _split_long_chunk(self, text: str) -> list[str]:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if not sentences:
            return [text[: self.MAX_CHUNK_LEN]]
        output: list[str] = []
        buffer = ""
        for sentence in sentences:
            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if len(candidate) <= self.MAX_CHUNK_LEN:
                buffer = candidate
            else:
                if buffer:
                    output.append(buffer)
                buffer = sentence
        if buffer:
            output.append(buffer)
        return output

    def _quality_filter(self, text: str) -> tuple[bool, str]:
        cleaned = text.strip()
        lower = cleaned.lower()
        if lower in self.NOISE_EXACT:
            return False, "heading_noise"
        if re.fullmatch(r"page\s+\d+", lower):
            return False, "page_noise"
        if len(cleaned) < 20:
            return False, "too_short"
        word_count = len(cleaned.split())
        if word_count < 5 and not any(kw in lower for kw in self.KEYWORDS) and not any(verb in lower for verb in self.ACTION_VERBS):
            return False, "likely_header"
        alpha_chars = [c for c in cleaned if c.isalpha()]
        if alpha_chars and sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) > 0.7:
            if word_count < 8:
                return False, "allcaps_heading"
        if re.match(r"^\d+[\.\)]\s*\w", cleaned) and word_count < 6:
            return False, "section_title"
        return True, "accepted"

    def _fallback_paragraphs(self, normalized_text: str) -> list[str]:
        blocks = [part.strip() for part in normalized_text.split("\n\n") if part.strip()]
        chunks: list[str] = []
        for block in blocks:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", block) if s.strip()]
            for s in sentences:
                if len(s) >= 20:
                    chunks.append(s)
                elif chunks:
                    chunks[-1] += " " + s
                else:
                    chunks.append(s)
        if not chunks:
            chunks = [line.strip() for line in normalized_text.split("\n") if line.strip()]
        return chunks

    def _write_interim_chunks(
        self,
        output_path: Path,
        project_id: str,
        candidates: Iterable[RequirementCandidate],
    ) -> None:
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "project_id",
                    "chunk_id",
                    "text",
                    "rule_used",
                    "accepted",
                    "notes",
                ]
            )
            for index, candidate in enumerate(candidates, start=1):
                writer.writerow(
                    [
                        project_id,
                        f"CHUNK-{index:03d}",
                        candidate.text,
                        candidate.rule_used,
                        "yes" if candidate.accepted else "no",
                        candidate.notes,
                    ]
                )

    def _infer_next_version(self, processed_project_dir: Path) -> int:
        existing = sorted(processed_project_dir.glob("requirements_v*.csv"))
        if not existing:
            return 1
        versions = []
        for file_path in existing:
            match = re.search(r"requirements_v(\d+)\.csv$", file_path.name)
            if match:
                versions.append(int(match.group(1)))
        return (max(versions) + 1) if versions else 1

    def _write_processed_requirements(
        self,
        project_id: str,
        source_doc: str,
        version: int,
        accepted_chunks: list[str],
        processed_project_dir: Path,
        output_csv_path: Path,
        created_at: str,
    ) -> int:
        existing_map, next_index = self._load_existing_key_map(processed_project_dir)
        rows: list[list[Union[str, int]]] = []
        for chunk in accepted_chunks:
            # Extract embedded key from text (e.g. "REQ-001: ..." or "REQ-001 | ...")
            display_text = chunk
            embedded_key_match = re.match(
                r"^(REQ-\d+)\s*[:|]\s*", chunk, re.IGNORECASE
            )
            if embedded_key_match:
                embedded_key = embedded_key_match.group(1).upper()
                display_text = chunk[embedded_key_match.end():].strip()
            else:
                embedded_key = None

            canonical_text = self._canonical_compare_text(chunk)
            req_key = existing_map.get(canonical_text)
            if embedded_key:
                # Always prefer the key from the requirement text
                req_key = embedded_key
                existing_map[canonical_text] = req_key
            elif req_key is None:
                req_key = f"REQ-{next_index:03d}"
                existing_map[canonical_text] = req_key
                next_index += 1
            rows.append(
                [
                    project_id,
                    str(uuid.uuid4()),
                    req_key,
                    display_text,
                    source_doc,
                    version,
                    created_at,
                ]
            )

        with output_csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "project_id",
                    "requirement_id",
                    "req_key",
                    "text",
                    "source_doc",
                    "version",
                    "created_at",
                ]
            )
            writer.writerows(rows)
        return len(rows)

    def _load_existing_key_map(self, processed_project_dir: Path) -> tuple[dict[str, str], int]:
        configure_csv_field_limit()
        existing = sorted(processed_project_dir.glob("requirements_v*.csv"))
        mapping: dict[str, str] = {}
        max_index = 0
        for file_path in existing:
            with file_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    text_value = (row.get("text") or "").strip()
                    req_key = (row.get("req_key") or "").strip()
                    if not text_value or not req_key:
                        continue
                    mapping[self._canonical_compare_text(text_value)] = req_key
                    key_match = re.search(r"REQ-(\d+)$", req_key)
                    if key_match:
                        max_index = max(max_index, int(key_match.group(1)))
        return mapping, max_index + 1

    def _canonical_compare_text(self, text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text
