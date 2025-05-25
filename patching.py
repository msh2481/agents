#!/usr/bin/env python3
"""
Patch parsing and application system with sophisticated diff handling.
Based on reference implementation from OpenAI's apply_patch.
"""
import os
import unicodedata
from enum import Enum
from typing import TypedDict


class ActionType(Enum):
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"


class FileChange(TypedDict, total=False):
    type: ActionType
    old_content: str | None
    new_content: str | None
    move_path: str | None


class Commit(TypedDict):
    changes: dict[str, FileChange]


class Chunk(TypedDict):
    orig_index: int
    del_lines: list[str]
    ins_lines: list[str]


class PatchAction(TypedDict, total=False):
    type: ActionType
    new_file: str | None
    chunks: list[Chunk]
    move_path: str | None


class Patch(TypedDict):
    actions: dict[str, PatchAction]


class DiffError(Exception):
    pass


PATCH_PREFIX = "*** Begin Patch\n"
PATCH_SUFFIX = "\n*** End Patch"
ADD_FILE_PREFIX = "*** Add File: "
DELETE_FILE_PREFIX = "*** Delete File: "
UPDATE_FILE_PREFIX = "*** Update File: "
MOVE_FILE_TO_PREFIX = "*** Move File To: "
END_OF_FILE_PREFIX = "*** End of File"
HUNK_ADD_LINE_PREFIX = "+"

# Unicode punctuation normalization mapping
PUNCT_EQUIV = {
    "-": "-",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
    "\u0022": '"',
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u0027": "'",
    "\u2018": "'",
    "\u2019": "'",
    "\u201b": "'",
    "\u00a0": " ",
    "\u202f": " ",
}


def canon(s: str) -> str:
    """Canonicalize string by normalizing Unicode and replacing punctuation look-alikes."""
    return unicodedata.normalize("NFC", s).translate(str.maketrans(PUNCT_EQUIV))


def find_context_core(
    lines: list[str], context: list[str], start: int
) -> tuple[int, int]:
    """Find context in lines starting from start index. Returns (index, fuzz_level)."""
    if not context:
        return start, 0

    canonical_context = canon("\n".join(context))

    # Pass 1: exact equality after canonicalization
    for i in range(start, len(lines)):
        if i + len(context) > len(lines):
            break
        segment = canon("\n".join(lines[i : i + len(context)]))
        if segment == canonical_context:
            return i, 0

    # Pass 2: ignore trailing whitespace
    for i in range(start, len(lines)):
        if i + len(context) > len(lines):
            break
        segment = canon(
            "\n".join(line.rstrip() for line in lines[i : i + len(context)])
        )
        ctx = canon("\n".join(line.rstrip() for line in context))
        if segment == ctx:
            return i, 1

    # Pass 3: ignore all surrounding whitespace
    for i in range(start, len(lines)):
        if i + len(context) > len(lines):
            break
        segment = canon("\n".join(line.strip() for line in lines[i : i + len(context)]))
        ctx = canon("\n".join(line.strip() for line in context))
        if segment == ctx:
            return i, 100

    return -1, 0


def find_context(
    lines: list[str], context: list[str], start: int, eof: bool
) -> tuple[int, int]:
    """Find context with EOF handling."""
    if eof:
        new_index, fuzz = find_context_core(lines, context, len(lines) - len(context))
        if new_index != -1:
            return new_index, fuzz
        new_index, fuzz = find_context_core(lines, context, start)
        return new_index, fuzz + 10000
    return find_context_core(lines, context, start)


def peek_next_section(
    lines: list[str], initial_index: int
) -> tuple[list[str], list[Chunk], int, bool]:
    """Parse next section and return context, chunks, end index, and eof flag."""
    index = initial_index
    old = []
    del_lines = []
    ins_lines = []
    chunks = []
    mode = "keep"

    end_prefixes = [
        "@@",
        PATCH_SUFFIX.strip(),
        UPDATE_FILE_PREFIX,
        DELETE_FILE_PREFIX,
        ADD_FILE_PREFIX,
        END_OF_FILE_PREFIX,
    ]

    while index < len(lines):
        s = lines[index]
        if any(s.startswith(p.strip()) for p in end_prefixes) or s == "***":
            break
        if s.startswith("***"):
            raise DiffError(f"Invalid Line: {s}")

        index += 1
        last_mode = mode
        line = s

        if line.startswith(HUNK_ADD_LINE_PREFIX):
            mode = "add"
        elif line.startswith("-"):
            mode = "delete"
        elif line.startswith(" "):
            mode = "keep"
        else:
            # Tolerate missing leading whitespace
            mode = "keep"
            line = " " + line

        line = line[1:]

        if mode == "keep" and last_mode != mode:
            if ins_lines or del_lines:
                chunks.append(
                    {
                        "orig_index": len(old) - len(del_lines),
                        "del_lines": del_lines,
                        "ins_lines": ins_lines,
                    }
                )
            del_lines = []
            ins_lines = []

        if mode == "delete":
            del_lines.append(line)
            old.append(line)
        elif mode == "add":
            ins_lines.append(line)
        else:
            old.append(line)

    if ins_lines or del_lines:
        chunks.append(
            {
                "orig_index": len(old) - len(del_lines),
                "del_lines": del_lines,
                "ins_lines": ins_lines,
            }
        )

    if index < len(lines) and lines[index] == END_OF_FILE_PREFIX:
        index += 1
        return old, chunks, index, True

    return old, chunks, index, False


class Parser:
    def __init__(self, current_files: dict[str, str], lines: list[str]):
        self.current_files = current_files
        self.lines = lines
        self.index = 0
        self.patch: Patch = {"actions": {}}
        self.fuzz = 0

    def is_done(self, prefixes: list[str] = None) -> bool:
        if self.index >= len(self.lines):
            return True
        if prefixes and any(
            self.lines[self.index].startswith(p.strip()) for p in prefixes
        ):
            return True
        return False

    def startswith(self, prefix: str | list[str]) -> bool:
        prefixes = prefix if isinstance(prefix, list) else [prefix]
        return any(self.lines[self.index].startswith(p) for p in prefixes)

    def read_str(self, prefix: str = "", return_everything: bool = False) -> str:
        if self.index >= len(self.lines):
            raise DiffError(f"Index: {self.index} >= {len(self.lines)}")
        if self.lines[self.index].startswith(prefix):
            text = (
                self.lines[self.index]
                if return_everything
                else self.lines[self.index][len(prefix) :]
            )
            self.index += 1
            return text or ""
        return ""

    def parse(self) -> None:
        while not self.is_done([PATCH_SUFFIX]):
            path = self.read_str(UPDATE_FILE_PREFIX)
            if path:
                if path in self.patch["actions"]:
                    raise DiffError(f"Update File Error: Duplicate Path: {path}")
                move_to = self.read_str(MOVE_FILE_TO_PREFIX)
                if path not in self.current_files:
                    raise DiffError(f"Update File Error: Missing File: {path}")
                text = self.current_files[path]
                action = self.parse_update_file(text)
                if move_to:
                    action["move_path"] = move_to
                self.patch["actions"][path] = action
                continue

            path = self.read_str(DELETE_FILE_PREFIX)
            if path:
                if path in self.patch["actions"]:
                    raise DiffError(f"Delete File Error: Duplicate Path: {path}")
                if path not in self.current_files:
                    raise DiffError(f"Delete File Error: Missing File: {path}")
                self.patch["actions"][path] = {"type": ActionType.DELETE, "chunks": []}
                continue

            path = self.read_str(ADD_FILE_PREFIX)
            if path:
                if path in self.patch["actions"]:
                    raise DiffError(f"Add File Error: Duplicate Path: {path}")
                if path in self.current_files:
                    raise DiffError(f"Add File Error: File already exists: {path}")
                self.patch["actions"][path] = self.parse_add_file()
                continue

            raise DiffError(f"Unknown Line: {self.lines[self.index]}")

        if not self.startswith(PATCH_SUFFIX.strip()):
            raise DiffError("Missing End Patch")
        self.index += 1

    def parse_update_file(self, text: str) -> PatchAction:
        action: PatchAction = {"type": ActionType.UPDATE, "chunks": []}
        file_lines = text.split("\n")
        index = 0

        end_prefixes = [
            PATCH_SUFFIX,
            UPDATE_FILE_PREFIX,
            DELETE_FILE_PREFIX,
            ADD_FILE_PREFIX,
            END_OF_FILE_PREFIX,
        ]

        while not self.is_done(end_prefixes):
            def_str = self.read_str("@@ ")
            section_str = ""
            if (
                not def_str
                and self.index < len(self.lines)
                and self.lines[self.index] == "@@"
            ):
                section_str = self.lines[self.index]
                self.index += 1

            if not (def_str or section_str or index == 0):
                raise DiffError(f"Invalid Line:\n{self.lines[self.index]}")

            if def_str.strip():
                found = False
                canonical_def = canon(def_str)

                # Try exact match first
                for i in range(index, len(file_lines)):
                    if canon(file_lines[i]) == canonical_def:
                        index = i + 1
                        found = True
                        break

                # Try trimmed match if exact fails
                if not found:
                    canonical_def_trimmed = canon(def_str.strip())
                    for i in range(index, len(file_lines)):
                        if canon(file_lines[i].strip()) == canonical_def_trimmed:
                            index = i + 1
                            self.fuzz += 1
                            found = True
                            break

            next_chunk_context, chunks, end_patch_index, eof = peek_next_section(
                self.lines, self.index
            )
            new_index, fuzz = find_context(file_lines, next_chunk_context, index, eof)

            if new_index == -1:
                ctx_text = "\n".join(next_chunk_context)
                error_type = "Invalid EOF Context" if eof else "Invalid Context"
                raise DiffError(f"{error_type} {index}:\n{ctx_text}")

            self.fuzz += fuzz
            for ch in chunks:
                ch["orig_index"] += new_index
                action["chunks"].append(ch)

            index = new_index + len(next_chunk_context)
            self.index = end_patch_index

        return action

    def parse_add_file(self) -> PatchAction:
        lines = []
        end_prefixes = [
            PATCH_SUFFIX,
            UPDATE_FILE_PREFIX,
            DELETE_FILE_PREFIX,
            ADD_FILE_PREFIX,
        ]

        while not self.is_done(end_prefixes):
            s = self.read_str()
            if not s.startswith(HUNK_ADD_LINE_PREFIX):
                raise DiffError(f"Invalid Add File Line: {s}")
            lines.append(s[1:])

        return {
            "type": ActionType.ADD,
            "new_file": "\n".join(lines),
            "chunks": [],
        }


def text_to_patch(text: str, orig: dict[str, str]) -> tuple[Patch, int]:
    """Parse patch text into Patch object."""
    lines = text.strip().split("\n")
    if (
        len(lines) < 2
        or not lines[0].startswith(PATCH_PREFIX.strip())
        or lines[-1] != PATCH_SUFFIX.strip()
    ):
        raise DiffError("Invalid patch format")

    parser = Parser(orig, lines)
    parser.index = 1
    parser.parse()
    return parser.patch, parser.fuzz


def get_updated_file(text: str, action: PatchAction, path: str) -> str:
    """Apply chunks to get updated file content."""
    if action["type"] != ActionType.UPDATE:
        raise ValueError("Expected UPDATE action")

    orig_lines = text.split("\n")
    dest_lines = []
    orig_index = 0

    for chunk in action["chunks"]:
        if chunk["orig_index"] > len(orig_lines):
            raise DiffError(
                f"{path}: chunk.orig_index {chunk['orig_index']} > len(lines) {len(orig_lines)}"
            )
        if orig_index > chunk["orig_index"]:
            raise DiffError(
                f"{path}: orig_index {orig_index} > chunk.orig_index {chunk['orig_index']}"
            )

        # Add lines before this chunk
        dest_lines.extend(orig_lines[orig_index : chunk["orig_index"]])
        orig_index = chunk["orig_index"]

        # Add inserted lines
        dest_lines.extend(chunk["ins_lines"])

        # Skip deleted lines
        orig_index += len(chunk["del_lines"])

    # Add remaining lines
    dest_lines.extend(orig_lines[orig_index:])
    return "\n".join(dest_lines)


def patch_to_commit(patch: Patch, orig: dict[str, str]) -> Commit:
    """Convert patch to commit with file changes."""
    commit: Commit = {"changes": {}}

    for path, action in patch["actions"].items():
        if action["type"] == ActionType.DELETE:
            commit["changes"][path] = {
                "type": ActionType.DELETE,
                "old_content": orig[path],
            }
        elif action["type"] == ActionType.ADD:
            commit["changes"][path] = {
                "type": ActionType.ADD,
                "new_content": action.get("new_file", ""),
            }
        elif action["type"] == ActionType.UPDATE:
            new_content = get_updated_file(orig[path], action, path)
            change: FileChange = {
                "type": ActionType.UPDATE,
                "old_content": orig[path],
                "new_content": new_content,
            }
            if action.get("move_path"):
                change["move_path"] = action["move_path"]
            commit["changes"][path] = change

    return commit


def identify_files_needed(text: str) -> list[str]:
    """Identify files that need to be read for the patch."""
    lines = text.strip().split("\n")
    result = set()
    for line in lines:
        if line.startswith(UPDATE_FILE_PREFIX):
            result.add(line[len(UPDATE_FILE_PREFIX) :])
        elif line.startswith(DELETE_FILE_PREFIX):
            result.add(line[len(DELETE_FILE_PREFIX) :])
    return list(result)


def identify_files_added(text: str) -> list[str]:
    """Identify files that will be added by the patch."""
    lines = text.strip().split("\n")
    result = set()
    for line in lines:
        if line.startswith(ADD_FILE_PREFIX):
            result.add(line[len(ADD_FILE_PREFIX) :])
    return list(result)


def load_files(paths: list[str], read_fn) -> dict[str, str]:
    """Load files into memory using provided read function."""
    orig = {}
    for p in paths:
        try:
            orig[p] = read_fn(p)
        except FileNotFoundError:
            raise DiffError(f"File not found: {p}")
    return orig


def apply_commit(commit: Commit, write_fn, delete_fn) -> str:
    """Apply commit changes using provided write and delete functions."""
    results = []

    for path, change in commit["changes"].items():
        if change["type"] == ActionType.DELETE:
            result = delete_fn(path)
            results.append(result)
        elif change["type"] == ActionType.ADD:
            result = write_fn(path, change.get("new_content", ""))
            results.append(result)
        elif change["type"] == ActionType.UPDATE:
            if change.get("move_path"):
                result = write_fn(change["move_path"], change.get("new_content", ""))
                results.append(result)
                result = delete_fn(path)
                results.append(result)
            else:
                result = write_fn(path, change.get("new_content", ""))
                results.append(result)

    return "\n".join(results)


def apply_patch(patch: str, read_fn, write_fn, delete_fn) -> str:
    """Parse and apply a patch string using provided file operation functions."""
    if not patch.startswith(PATCH_PREFIX):
        raise DiffError("Patch must start with *** Begin Patch\\n")

    # Load files needed for UPDATE/DELETE operations
    paths = identify_files_needed(patch)
    orig = load_files(paths, read_fn)

    # Check that ADD files don't already exist
    add_paths = identify_files_added(patch)
    for path in add_paths:
        try:
            read_fn(path)
            raise DiffError(f"Add File Error: File already exists: {path}")
        except FileNotFoundError:
            pass  # This is what we want - file doesn't exist

    patch_obj, _fuzz = text_to_patch(patch, orig)
    commit = patch_to_commit(patch_obj, orig)
    return apply_commit(commit, write_fn, delete_fn)
