"""The registry: namespaces, tools, and the command each one dispatches to.

One TOML file. A table is a group; a table inside it is a command in that group:

    [llm]
    description = "local model servers and the containers around them"
    command     = "/Users/x/llmctl"

      [llm.llama]
      description = "run and control local language model servers"
      command     = "/Users/x/llmctl llama"

    [jq]
    command = "/usr/bin/jq"

A **tool** is a name mapped to a command. A **namespace** groups tools; it may carry
its own `command`, which makes it dispatchable. A standalone tool is a namespace with
a command and no tools — one shape, no special case.

The split below is by what a caller wants, not by type: `model` is the shapes,
`names` is what a legal name is, `read` parses and looks up, `write` mutates the
file, `checks` is what doctor asks. Callers use this module, not its parts.
"""
from __future__ import annotations

from ..config import BUILTIN_NAMES
from .checks import (
    ADVISORY,
    BROKEN,
    CHECKS,
    REACHABILITY,
    STRUCTURE,
    DoctorIssue,
    doctor_issues,
    environment_specific,
    is_shell_construct,
    issues_for,
    path_matches,
    syntax_problem,
)
from .model import Entry, Namespace, Registry
from .names import ensure_addable, is_shadowed, name_problem, split_name, validate_name
from .read import (
    is_grouping_namespace,
    load,
    read_file,
    resolve,
    shadowed_names,
    visible_entries,
)
from .write import (
    MergeResult,
    add,
    edit,
    merge_file,
    remove,
    rename,
    set_command,
    set_description,
)

__all__ = [
    "ADVISORY",
    "BROKEN",
    "BUILTIN_NAMES",
    "CHECKS",
    "REACHABILITY",
    "STRUCTURE",
    "DoctorIssue",
    "Entry",
    "MergeResult",
    "Namespace",
    "Registry",
    "add",
    "doctor_issues",
    "edit",
    "ensure_addable",
    "environment_specific",
    "is_grouping_namespace",
    "is_shadowed",
    "is_shell_construct",
    "issues_for",
    "load",
    "merge_file",
    "name_problem",
    "path_matches",
    "read_file",
    "remove",
    "rename",
    "resolve",
    "set_command",
    "set_description",
    "shadowed_names",
    "split_name",
    "syntax_problem",
    "validate_name",
    "visible_entries",
]
