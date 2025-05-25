#!/usr/bin/env python3
"""
Tests for the patching module.
"""
import os
import tempfile
from unittest.mock import Mock

from patching import (
    ActionType,
    apply_patch,
    canon,
    DiffError,
    find_context_core,
    identify_files_needed,
    PATCH_PREFIX,
    PATCH_SUFFIX,
    text_to_patch,
)


class TestCanonFunction:
    def test_canon_unicode_normalization(self):
        # Test Unicode punctuation normalization
        assert canon("hello—world") == "hello-world"  # em dash to hyphen
        assert canon("\u201chello\u201d") == '"hello"'  # smart quotes to regular
        assert canon("it\u2019s") == "it's"  # smart apostrophe
        assert canon("hello\u00a0world") == "hello world"  # non-breaking space

    def test_canon_multiple_substitutions(self):
        text = "—\u201csmart quotes\u201d—\u2019apostrophe\u2019 test"
        expected = "-\"smart quotes\"-'apostrophe' test"
        assert canon(text) == expected


class TestFindContextCore:
    def test_exact_match(self):
        lines = ["line1", "line2", "line3", "line4"]
        context = ["line2", "line3"]
        index, fuzz = find_context_core(lines, context, 0)
        assert index == 1
        assert fuzz == 0

    def test_whitespace_tolerance(self):
        lines = ["line1", "line2  ", "line3", "line4"]
        context = ["line2", "line3"]
        index, fuzz = find_context_core(lines, context, 0)
        assert index == 1
        assert fuzz == 1

    def test_full_whitespace_tolerance(self):
        lines = ["line1", "  line2  ", "  line3  ", "line4"]
        context = ["line2", "line3"]
        index, fuzz = find_context_core(lines, context, 0)
        assert index == 1
        assert fuzz == 100

    def test_no_match(self):
        lines = ["line1", "line2", "line3", "line4"]
        context = ["notfound", "alsomissing"]
        index, fuzz = find_context_core(lines, context, 0)
        assert index == -1
        assert fuzz == 0

    def test_empty_context(self):
        lines = ["line1", "line2"]
        context = []
        index, fuzz = find_context_core(lines, context, 1)
        assert index == 1
        assert fuzz == 0


class TestIdentifyFilesNeeded:
    def test_identify_update_files(self):
        patch = """*** Begin Patch
*** Update File: file1.py
*** Update File: file2.py
*** End Patch"""
        files = identify_files_needed(patch)
        assert set(files) == {"file1.py", "file2.py"}

    def test_identify_delete_files(self):
        patch = """*** Begin Patch
*** Delete File: old_file.py
*** End Patch"""
        files = identify_files_needed(patch)
        assert files == ["old_file.py"]

    def test_identify_mixed_operations(self):
        patch = """*** Begin Patch
*** Update File: update_me.py
*** Delete File: delete_me.py
*** Add File: new_file.py
*** End Patch"""
        files = identify_files_needed(patch)
        assert set(files) == {"update_me.py", "delete_me.py"}


class TestPatchOperations:
    def setup_method(self):
        self.mock_files = {}
        self.results = []

        def mock_read(path):
            if path not in self.mock_files:
                raise FileNotFoundError(f"File not found: {path}")
            return self.mock_files[path]

        def mock_write(path, content):
            self.mock_files[path] = content
            result = f"Wrote file: {path}"
            self.results.append(result)
            return result

        def mock_delete(path):
            if path not in self.mock_files:
                raise FileNotFoundError(f"File not found: {path}")
            del self.mock_files[path]
            result = f"Deleted file: {path}"
            self.results.append(result)
            return result

        self.read_fn = mock_read
        self.write_fn = mock_write
        self.delete_fn = mock_delete

    def test_add_file(self):
        patch = """*** Begin Patch
*** Add File: new_file.py
+def hello():
+    print("Hello, world!")
*** End Patch"""

        result = apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
        assert "new_file.py" in self.mock_files
        assert "def hello():" in self.mock_files["new_file.py"]
        assert 'print("Hello, world!")' in self.mock_files["new_file.py"]

    def test_delete_file(self):
        self.mock_files["old_file.py"] = "old content"

        patch = """*** Begin Patch
*** Delete File: old_file.py
*** End Patch"""

        result = apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
        assert "old_file.py" not in self.mock_files

    def test_update_file_simple(self):
        self.mock_files[
            "test.py"
        ] = """def example():
    pass"""

        patch = """*** Begin Patch
*** Update File: test.py
-    pass
+    return 123
*** End Patch"""

        result = apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
        assert "return 123" in self.mock_files["test.py"]
        assert "pass" not in self.mock_files["test.py"]

    def test_update_file_with_context(self):
        self.mock_files[
            "test.py"
        ] = """class Example:
    def method1(self):
        return 1
    
    def method2(self):
        pass
        
    def method3(self):
        return 3"""

        patch = """*** Begin Patch
*** Update File: test.py
@@ def method2(self):
-        pass
+        return 2
*** End Patch"""

        result = apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
        updated_content = self.mock_files["test.py"]
        assert "return 2" in updated_content
        assert "def method1(self):" in updated_content  # Other methods preserved
        assert "def method3(self):" in updated_content

    def test_multiple_operations(self):
        self.mock_files["update_me.py"] = "old content"
        self.mock_files["delete_me.py"] = "to be deleted"

        patch = """*** Begin Patch
*** Update File: update_me.py
-old content
+new content
*** Delete File: delete_me.py
*** Add File: create_me.py
+new file content
*** End Patch"""

        result = apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)

        assert self.mock_files["update_me.py"] == "new content"
        assert "delete_me.py" not in self.mock_files
        assert self.mock_files["create_me.py"] == "new file content"

    def test_file_move(self):
        self.mock_files[
            "old_path.py"
        ] = """def function():
    old_implementation()"""

        patch = """*** Begin Patch
*** Update File: old_path.py
*** Move File To: new_path.py
-    old_implementation()
+    new_implementation()
*** End Patch"""

        result = apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)

        assert "old_path.py" not in self.mock_files
        assert "new_path.py" in self.mock_files
        assert "new_implementation()" in self.mock_files["new_path.py"]


class TestErrorHandling:
    def setup_method(self):
        self.mock_files = {}

        def mock_read(path):
            if path not in self.mock_files:
                raise FileNotFoundError(f"File not found: {path}")
            return self.mock_files[path]

        def mock_write(path, content):
            self.mock_files[path] = content
            return f"Wrote file: {path}"

        def mock_delete(path):
            if path not in self.mock_files:
                raise FileNotFoundError(f"File not found: {path}")
            del self.mock_files[path]
            return f"Deleted file: {path}"

        self.read_fn = mock_read
        self.write_fn = mock_write
        self.delete_fn = mock_delete

    def test_invalid_patch_format(self):
        patch = "Invalid patch without proper format"

        try:
            apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
            assert False, "Expected DiffError"
        except DiffError as e:
            assert "Patch must start with" in str(e)

    def test_missing_file_for_update(self):
        patch = """*** Begin Patch
*** Update File: nonexistent.py
-old content
+new content
*** End Patch"""

        try:
            apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
            assert False, "Expected DiffError"
        except DiffError as e:
            assert "File not found" in str(e)

    def test_duplicate_file_path(self):
        self.mock_files["test.py"] = "content"

        patch = """*** Begin Patch
*** Update File: test.py
*** Update File: test.py
*** End Patch"""

        try:
            apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
            assert False, "Expected DiffError"
        except DiffError as e:
            assert "Duplicate Path" in str(e)

    def test_add_existing_file(self):
        self.mock_files["existing.py"] = "already exists"

        patch = """*** Begin Patch
*** Add File: existing.py
+new content
*** End Patch"""

        try:
            apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
            assert False, "Expected DiffError"
        except DiffError as e:
            assert "File already exists" in str(e)

    def test_invalid_context(self):
        self.mock_files[
            "test.py"
        ] = """def function():
    return 1"""

        patch = """*** Begin Patch
*** Update File: test.py
 this context does not exist
-old line
+new line
*** End Patch"""

        try:
            apply_patch(patch, self.read_fn, self.write_fn, self.delete_fn)
            assert False, "Expected DiffError"
        except DiffError as e:
            assert "Invalid Context" in str(e)


class TestTextToPatch:
    def test_valid_patch_parsing(self):
        orig_files = {"test.py": "def func():\n    pass"}

        patch_text = """*** Begin Patch
*** Update File: test.py
-    pass
+    return 123
*** End Patch"""

        patch, fuzz = text_to_patch(patch_text, orig_files)
        assert "test.py" in patch["actions"]
        assert patch["actions"]["test.py"]["type"] == ActionType.UPDATE
        assert len(patch["actions"]["test.py"]["chunks"]) == 1

    def test_invalid_patch_format(self):
        orig_files = {}
        patch_text = "Not a valid patch"

        try:
            text_to_patch(patch_text, orig_files)
            assert False, "Expected DiffError"
        except DiffError as e:
            assert "Invalid patch format" in str(e)

    def test_add_file_parsing(self):
        orig_files = {}

        patch_text = """*** Begin Patch
*** Add File: new.py
+def hello():
+    print("world")
*** End Patch"""

        patch, fuzz = text_to_patch(patch_text, orig_files)
        assert "new.py" in patch["actions"]
        assert patch["actions"]["new.py"]["type"] == ActionType.ADD
        assert "def hello():" in patch["actions"]["new.py"]["new_file"]


if __name__ == "__main__":
    # Simple test runner
    test_classes = [
        TestCanonFunction,
        TestFindContextCore,
        TestIdentifyFilesNeeded,
        TestPatchOperations,
        TestErrorHandling,
        TestTextToPatch,
    ]

    for test_class in test_classes:
        print(f"\nRunning {test_class.__name__}...")
        instance = test_class()

        for method_name in dir(instance):
            if method_name.startswith("test_"):
                try:
                    # Setup if exists
                    if hasattr(instance, "setup_method"):
                        instance.setup_method()

                    # Run test
                    getattr(instance, method_name)()
                    print(f"  ✓ {method_name}")
                except Exception as e:
                    print(f"  ✗ {method_name}: {e}")

    print("\nTests completed!")
