# Milestone 03 --- Project Workspace

**Status:** Approved / Ready for Implementation\
**Phase:** Project Workspace\
**Project codename:** F.R.I.D.A.Y.\
**Final assistant name:** Deferred

## 1. Objective

Build the Project Workspace subsystem: explicit project registration,
current-working-directory (CWD) detection, an active-project focus
pointer, and the private FRIDAY project workspace that stores
assistant-maintained project context, facts, decisions, changelog, and
state.

Architectural rule: FRIDAY must support BOTH explicit project
registration AND CWD project detection. Explicit registration is
authoritative. CWD detection is a convenience/discovery mechanism and
must never silently create or register a project.

## 2. Current State

The `friday/filesystem/` subsystem already provides:

- `ProjectRootRegistry` --- persists authorization grants for external
  roots in `~/.friday/project_roots.json`.
- `PathPolicy` --- deny-by-default path authorization. `FRIDAY_HOME`
  (`~/.friday`) is the trusted workspace root; registered roots are
  additionally authorized.
- `FileSystemManager` --- deterministic I/O behind the policy boundary.
  It does not create parent directories and has no `create_directory`.

There is no project concept beyond the authorization grant, no CWD
detection, no active-project state, and no private project workspace.

The `friday/projects/` package does not exist yet.

## 3. Core Distinction

```text
Actual project root:
    /path/to/user/project/

FRIDAY private project workspace:
    ~/.friday/projects/<project-id>/
```

The private workspace stores assistant-maintained project context, not a
copy of the user's source tree. The two locations are never confused.

## 4. Domain Model

### Project

The persisted registry entry. Evolves the existing `Grant`.

| Field | Description |
| --- | --- |
| id | Stable internal project ID (`uuid4().hex[:12]`). Keys the workspace directory. Independent of the display name. |
| name | Display name. Freely editable. Not an identifier. |
| root | Resolved, absolute filesystem root of the user's project. Security boundary. |
| permissions | `read` / `write` authorization, existing grant semantics. |
| created_at | ISO timestamp. |

Derived, not stored: `workspace = FRIDAY_HOME / "projects" / id`.

### DetectedProject

A runtime observation: which registered `Project`'s root contains the
current CWD, or `None`. Never persisted. Detection performs no writes
and never registers unknown directories.

### ActiveProject

The current focus pointer, persisted to `~/.friday/active_project.json`:

``` json
{ "project_id": "...", "source": "explicit" | "detected", "updated_at": "..." }
```

## 5. Unified Registry

The existing `ProjectRootRegistry` is unified into the project registry
(ADR). One file, one source of truth: a registered project IS an
authorized root. No separate "known projects" store that could drift
from "authorized roots".

- Storage path stays `~/.friday/project_roots.json`.
- Loading is backward-compatible (accepts the existing `label` field as
  the display name).
- The registry is the security boundary consumed by `PathPolicy` and
  the source of project identity consumed by the projects layer.
- The registry must remain a pure authorization record. Workspace
  seeding happens in the projects layer.

## 6. Registration Flow

Host-authorized only. The assistant can never register or revoke
projects through a tool.

1. Host calls `ProjectService.register(root, name)`.
2. Validate `root` exists and is a directory; else
   `RootNotFoundError` (reused from the filesystem subsystem).
3. Generate stable internal `id`. Persist the registry entry with
   atomic tmp + rename.
4. `workspace.ensure(id)` seeds `~/.friday/projects/<id>/` with empty
   `context.md`, `facts.md`, `decisions.md`, `changelog.md` and a
   default `state.json`. This is the only thing registration creates on
   disk.

- Rename: mutates only `name`. ID, root, and workspace are untouched.
  The workspace survives renames by construction.
- Unregister: removes the registry entry. The workspace is retained on
  disk (derived, rebuildable knowledge --- do not delete).
- Duplicate root: registering an already-registered root returns the
  existing project (idempotent).

## 7. CWD Detection Flow

1. `detector.detect(Path.cwd().resolve())`.
2. Collect registered projects where `cwd.is_relative_to(project.root)`.
3. Select the LONGEST matching root (most specific). Overlapping or
   nested registered roots resolve to the deepest one.
4. Match -> return the `Project`. No match -> return `None`. Never
   register, never create a workspace.

This requires fixing `grant_containing()` in `registry.py`, which
currently returns the first match in dict order rather than the longest.

## 8. Active-Project Flow

### Precedence

**Explicit beats detected. Detection never overrides an explicit
pointer.**

### State transitions

`ProjectService.activate(id)`:

- Sets `active = {id, source: "explicit", now}` and persists.
- CWD changes have no effect on this pointer.
- Remains until `clear()`, `activate(other_id)`, or the project is
  unregistered (invalid).

`ProjectService.clear()`:

- Clears the explicit pointer.
- Immediately runs CWD detection on the current CWD:
  - inside a registered root -> `active = {id, source: "detected", now}`;
  - outside all registered roots -> `active = None`.

Automatic detection (only when there is no explicit pointer), at
session/request handling:

- CWD inside a registered root -> `active = {id, source: "detected",
  now}`.
- CWD leaves all registered roots -> `active = None`.

Unregistration of an explicitly active project:

- The pointer becomes invalid and is cleared.
- Then fall back to CWD detection per the `clear()` rule.
- A stale pointer is also rejected on load: resolves to `None`, then
  detection runs.

### Invariants

1. `active` non-null with `source="explicit"` implies its project is
   registered and CWD detection is bypassed.
2. `active` with `source="detected"` is always derived from the current
   CWD and recomputed on every reconcile.
3. At most one active project.
4. All transitions are deterministic and persisted atomically.

### Reconcile algorithm

```text
reconcile():
  active = load()
  if active and active.source == "explicit":
      if not registry.contains(active.id):
          active = None                  # invalid -> clear, fall through
      else:
          return active                  # explicit wins; ignore CWD
  detected = detector.detect(Path.cwd())
  if detected is None:
      return clear_pointer()             # active = None
  return set_pointer(detected.id, source="detected")
```

## 9. Private Workspace Design

```text
~/.friday/projects/<project-id>/
├── context.md
├── facts.md
├── decisions.md
├── changelog.md
└── state.json
```

| File | Format | Semantics |
| --- | --- | --- |
| context.md | markdown | current working context, TODOs, focus |
| facts.md | markdown | durable verified facts |
| decisions.md | markdown | recorded decisions, append-only |
| changelog.md | markdown | change history, append-only |
| state.json | JSON | machine-parseable state (branch, current task, last activity) |

- Assistant-maintained content, not user-facing documents.
- Formats are deliberately plain: inspectable, diffable, rebuildable.
- All I/O goes through `FileSystemManager`. Workspace paths live under
  `FRIDAY_HOME` and are already trusted by `PathPolicy`.
- Append operations are bounded read-modify-write via existing
  `read_file` / `write_file(overwrite=True)` until a real append
  capability is justified.
- Requires `FileSystemManager.create_directory()` for workspace seeding.

## 10. Persistence Recommendation

| Concern | Choice |
| --- | --- |
| Registry | JSON, evolving the existing `project_roots.json`. Tiny, low-write, atomic-replace, auditable. |
| Workspace content | Plain files: Markdown for prose, JSON for state. |
| Facts/decisions/state at scale | SQLite later, when retrieval/querying is a real requirement (ADR-012, memory storage backend). |

Do not select binary or custom encodings for compression without a
demonstrated benefit.

## 11. Interaction with Filesystem Subsystem

- No registry duplication. The unified `ProjectRegistry` in
  `friday/filesystem/` is the single source of truth for authorization
  and project identity.
- All project-root and workspace I/O flows through `PathPolicy` ->
  `FileSystemManager`. No raw `open()` / `Path.read_text()` in the
  projects layer.
- Introduce a composition root: a shared registry -> policy -> manager
  construction used by both the filesystem tools and the project
  service. This replaces the per-call rebuild in
  `tools/filesystem.py:_build_manager()`.
- Longest-match also improves authorization: the most-specific root
  wins, a strictly better security default.

## 12. Interaction with Future Memory Subsystem

```text
Conversation
    ↓
Memory extraction
    ↓
facts / decisions / context
    ↓ (project-scoped sink only)
ProjectWorkspace facts / decisions / context
```

- The workspace is the project-scoped sink for distilled knowledge.
  Raw conversations stay in the memory store.
- The projects layer exposes a workspace API (`record_fact`,
  `record_decision`, `update_context`, `update_state`) as the future
  sink interface. The extraction algorithm, model, and schema are NOT
  designed in this milestone.
- Project context is later consumed by the Context Pipeline
  (`Context.project` in DOMAIN_MODEL.md).
- Rebuildable by design: the workspace is derived knowledge and can be
  reconstructed from project files, git history, documents, and
  conversation history.

## 13. Security Boundaries

- Transport-free: no LiveKit, MCP, LLM, or `agent_friday.py` imports.
  No MCP tools, no CLI, no web UI in this milestone.
- Registration is host-side only.
- Deny-by-default: unregistered roots are inaccessible and never become
  "detected-active".
- Symlink-safe: all paths resolved; the policy already blocks escapes.
- Workspace content is bounded by existing read/write limits; append
  operations are bounded.
- Detection is strictly read-only.

## 14. Edge Cases

1. Nested/overlapping registered roots -> longest match.
2. CWD deleted or renamed -> `resolve(strict=False)`; no match; active
   cleared (or explicit kept).
3. Duplicate root registration -> idempotent return-existing.
4. Duplicate display names -> allowed (name is not identity).
5. Rename -> workspace unaffected (id-keyed).
6. Unregister -> entry removed, workspace retained on disk.
7. Corrupt registry file -> `RegistryCorruptError` (existing).
8. Root moved after registration -> detection returns `None`, no crash.
9. Case-insensitive filesystems -> `is_relative_to` follows each
   filesystem's semantics; resolution normalizes first.
10. Stale active pointer -> loads as `None`, cleared.
11. First run (no registry) -> empty registry, no detection, no
    workspace created.
12. CWD equals a root -> matches (prefix includes self).
13. Symlinked CWD inside a root -> resolves to the real path, matches.
14. CWD inside `~/.friday` -> only active if explicitly registered.
15. Workspace growth -> bounded by read/write limits; compaction later.

## 15. Package Structure

```text
friday/
├── filesystem/                 # EVOLVED, not duplicated
│   ├── models.py               # Grant -> Project (identity + authorization)
│   ├── registry.py             # ProjectRootRegistry -> ProjectRegistry (longest match)
│   ├── manager.py              # + create_directory
│   └── policy.py               # unchanged semantics
└── projects/                   # NEW, transport-free
    ├── __init__.py
    ├── models.py               # DetectedProject, ActiveProject
    ├── detector.py             # CWD -> Project | None (read-only)
    ├── active.py               # persisted pointer + reconcile
    ├── workspace.py            # private workspace via FileSystemManager
    ├── service.py              # ProjectService facade (public entry point)
    └── exceptions.py
```

`ProjectService` is the only public API. Registration, detection,
active-project, and workspace operations are reached through it.

## 16. Implementation Order

Each step is tested with `pytest`, matching the existing
`filesystem/test_*.py` style.

1. Filesystem evolution: longest-match in the registry;
   `create_directory` on `FileSystemManager`.
2. Registry unify: `Grant -> Project`, backward-compatible load, keep
   the storage path.
3. `friday/projects` skeleton: `models.py`, `exceptions.py`,
   `__init__.py`.
4. `workspace.py`: ensure/seed, read/write/append the five files via
   `FileSystemManager`.
5. `detector.py`: CWD -> `Project | None`, longest match, read-only.
6. `active.py`: persisted pointer + reconcile (explicit/detected/clear).
7. `service.py`: `ProjectService` facade + composition root shared with
   the filesystem tools.
8. Session wiring: expose `Session.current_project` (no MCP/CLI/UI).
9. Update architecture and decision documentation.

## 17. In Scope Now

- Unified project registry
- Explicit registration (host-authorized)
- CWD detection with longest-root matching
- Persisted active-project pointer with explicit/detected precedence
- Private workspace with context/facts/decisions/changelog/state
- Workspace I/O through `FileSystemManager`
- `create_directory` capability
- Composition root shared with filesystem tools
- Session wiring for the current project

## 18. Explicitly Out of Scope

- MCP tools for projects
- CLI
- Web UI
- Memory distillation / extraction algorithm
- SQLite for workspace content
- Semantic/vector retrieval
- Any coupling to LiveKit, MCP, LLM providers, or `agent_friday.py`

## 19. Acceptance Criteria

- [ ] A user can explicitly register a project root; the root must exist
      and be a directory.
- [ ] A registered project has a stable internal ID independent of its
      display name.
- [ ] Renaming a project does not break its stored workspace.
- [ ] CWD detection resolves nested directories to the registered root.
- [ ] Overlapping registered roots resolve to the longest/most-specific
      match.
- [ ] CWD detection never auto-registers unknown directories.
- [ ] Explicit active project persists across CWD changes.
- [ ] Without an explicit pointer, CWD detection drives the active
      project; leaving all roots clears it.
- [ ] `clear()` falls back to CWD detection immediately.
- [ ] Unregistering the explicitly active project invalidates and clears
      the pointer, then falls back to detection.
- [ ] Workspace content lives under `~/.friday/projects/<id>/`, never in
      the user's project root.
- [ ] All workspace I/O goes through `FileSystemManager`.
- [ ] The subsystem imports nothing from LiveKit, MCP, LLM providers, or
      `agent_friday.py`.
- [ ] Registry remains a single source of truth (no duplicated root
      registry).
- [ ] Existing filesystem tests and functionality continue to pass.
