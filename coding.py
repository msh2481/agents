#!/usr/bin/env python3
"""
Coding tools for agents: file ops, directory tree, shell commands with interactive confirmation.
"""
import os
import shlex
import shutil
import subprocess
from typing import Any, Dict, List

from agents import function_tool
from patching import apply_patch


def tree(path: str = ".", depth: int = 4) -> list[dict[str, Any]]:
    root = os.path.abspath(path)
    entries: list[dict[str, Any]] = []

    def _scan(current_path: str, rel_path: str, current_depth: int) -> int:
        if current_depth > depth:
            return 0
        total_size = 0
        try:
            with os.scandir(current_path) as it:
                for entry in it:
                    entry_path = entry.path
                    entry_rel = (
                        os.path.join(rel_path, entry.name) if rel_path else entry.name
                    )
                    if entry.is_file(follow_symlinks=False):
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            size = 0
                        entries.append(
                            {
                                "name": entry.name,
                                "path": entry_rel,
                                "is_dir": False,
                                "size": size,
                                "depth": current_depth,
                            }
                        )
                        total_size += size
                    elif entry.is_dir(follow_symlinks=False):
                        dir_size = _scan(entry_path, entry_rel, current_depth + 1)
                        entries.append(
                            {
                                "name": entry.name,
                                "path": entry_rel,
                                "is_dir": True,
                                "size": dir_size,
                                "depth": current_depth,
                            }
                        )
                        total_size += dir_size
        except OSError:
            pass
        return total_size

    _ = _scan(root, "", 1)
    lines = []
    for entry in entries:
        entry_path = entry["path"]
        path_parts = entry_path.split("/")
        if any(
            part.startswith(".") or part.startswith("__") or part.endswith(".log")
            for part in path_parts
        ):
            # Ignore hidden files and directories
            continue
        lines.append(f"{entry['path']} ({entry['size']} bytes)")
    return "\n".join(lines)


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write_file(path: str, content: str) -> str:
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote file: {path}"


def append_file(path: str, content: str) -> str:
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content)
    return f"Appended to file: {path}"


def delete_file(path: str) -> str:
    if os.path.isdir(path):
        raise IsADirectoryError(f"Path is a directory, not a file: {path}")
    os.remove(path)
    return f"Deleted file: {path}"


def rename_file(old_path: str, new_path: str) -> str:
    os.rename(old_path, new_path)
    return f"Renamed {old_path} -> {new_path}"


def make_directory(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return f"Created directory: {path}"


def remove_directory(path: str) -> str:
    shutil.rmtree(path)
    return f"Removed directory: {path}"


def run_shell(command: List[str], cwd: str = None) -> Dict[str, Any]:
    cmd_str = " ".join(shlex.quote(c) for c in command)
    cwd_display = cwd or os.getcwd()
    prompt = f"⚠️ About to run: {cmd_str}\nIn: {cwd_display}\nProceed? [y/N] "
    ans = input(prompt)
    if ans.lower() != "y":
        return {"cancelled": True, "message": "Command cancelled by user."}
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.returncode,
    }


# Tool wrappers calling the plain functions
@function_tool(
    name_override="tree",
    description_override="Recursively list files & directories (with sizes) up to a given depth.",
)
def tree_tool(path: str = ".", depth: int = 4) -> List[Dict[str, Any]]:
    return tree(path, depth)


@function_tool(
    name_override="read_file", description_override="Return the full text of a file."
)
def read_file_tool(path: str) -> str:
    return read_file(path)


@function_tool(
    name_override="write_file",
    description_override="Overwrite a file with the given contents (creates if missing).",
)
def write_file_tool(path: str, content: str) -> str:
    return write_file(path, content)


@function_tool(
    name_override="append_file",
    description_override="Append text to the end of a file (creates if missing).",
)
def append_file_tool(path: str, content: str) -> str:
    return append_file(path, content)


@function_tool(name_override="delete_file", description_override="Delete a file.")
def delete_file_tool(path: str) -> str:
    return delete_file(path)


@function_tool(
    name_override="rename_file",
    description_override="Rename or move a file or directory.",
)
def rename_file_tool(old_path: str, new_path: str) -> str:
    return rename_file(old_path, new_path)


@function_tool(
    name_override="make_directory",
    description_override="Create a directory (with parents as needed).",
)
def make_directory_tool(path: str) -> str:
    return make_directory(path)


@function_tool(
    name_override="remove_directory",
    description_override="Recursively delete a directory and its contents.",
)
def remove_directory_tool(path: str) -> str:
    return remove_directory(path)


@function_tool(
    name_override="run_shell",
    description_override="Interactively confirm, then run a shell command and return stdout/stderr/exit code.",
)
def run_shell_tool(command: List[str], cwd: str = None) -> Dict[str, Any]:
    return run_shell(command, cwd)


@function_tool(
    name_override="apply_patch",
    description_override="Parse and apply a patch string with create/delete/update file operations.",
)
def apply_patch_tool(patch: str) -> str:
    return apply_patch(patch, read_file, write_file, delete_file)


if __name__ == "__main__":
    print(tree("/Users/mike/Desktop/"))
