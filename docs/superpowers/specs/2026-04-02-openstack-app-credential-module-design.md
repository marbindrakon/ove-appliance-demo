# Design: Replace CLI App Credential Management with openstack.cloud Module

**Date:** 2026-04-02
**Scope:** `roles/openstack_project`, `inventory/group_vars/all.yml`, `site.yml`, `teardown.yml`, `.gitignore`

## Problem

The `openstack_project` role manages the sushy application credential via `ansible.builtin.command` calls to the `openstack` CLI. This is inconsistent with the rest of the role, which uses `openstack.cloud.*` modules, and requires the OpenStack CLI to be installed on the control node.

Additionally, the two `lookup('password', ...)` cache files (`.ove-demo-project-suffix`, `.ove-demo-sushy-password`) sit loose in the project root alongside the future application credential cache files, making the gitignore harder to manage.

## Goals

- Replace CLI-based application credential tasks with `openstack.cloud.application_credential` (collection 2.5.0)
- Make application credential creation idempotent: only create if not present, persist the secret locally for subsequent runs
- Consolidate all local state into a single `.ove-demo-cache/` directory

## Cache Directory

All generated/persisted local state lives in `.ove-demo-cache/` at the project root:

```
.ove-demo-cache/
  project-suffix                # 5-char random suffix for project name
  sushy-password                # 24-char sushy service user password
  sushy-app-credential-id       # OpenStack application credential ID
  sushy-app-credential-secret   # OpenStack application credential secret
```

The directory is gitignored as a unit. Because `lookup('password', ...)` evaluates lazily (when the variable is first referenced, not at parse time), the directory must exist before any task references `project_name` or `sushy_password`. A `pre_tasks` block in `site.yml` creates `.ove-demo-cache/` with `ansible.builtin.file` (`state: directory`, `mode: '0700'`) so it is present before any role runs.

**Migration note:** Changing the `lookup('password', ...)` paths invalidates any existing `.ove-demo-project-suffix` and `.ove-demo-sushy-password` files. Existing users must tear down their current environment before upgrading, or manually move the files into `.ove-demo-cache/` with the new names.

## Changes

### `.gitignore`

Remove:
```
.ove-demo-project-suffix
.ove-demo-sushy-password
```

Add:
```
.ove-demo-cache/
```

### `inventory/group_vars/all.yml`

Update the two `lookup('password', ...)` file paths:

| Variable | Old path | New path |
|----------|----------|----------|
| `project_name` suffix | `.ove-demo-project-suffix` | `.ove-demo-cache/project-suffix` |
| `sushy_password` | `.ove-demo-sushy-password` | `.ove-demo-cache/sushy-password` |

### `roles/openstack_project/tasks/main.yml`

Replace the three CLI tasks (delete credential, create credential, parse JSON output) with:

1. **Ensure application credential exists** — `openstack.cloud.application_credential` with `state: present`, authenticating inline as the sushy user via `auth:` dict (not `cloud:`, since the sushy user has no clouds.yaml entry). Uses `os_auth_url`, `sushy_password`, `project_name`, and `project_domain`.

2. **Write secret to cache** — conditional on the module result containing a `secret` (i.e., the credential was just created). Writes `sushy-app-credential-id` and `sushy-app-credential-secret` to `.ove-demo-cache/` with mode `0600`.

3. **Read secret from cache** — conditional on the module result not containing a `secret` (i.e., the credential pre-existed). Slurps both cache files.

4. **Set facts** — sets `sushy_app_credential_id` and `sushy_app_credential_secret` as cacheable facts from whichever path provided the data. Replaces the existing "store application credential details" task.

The downstream fact names (`sushy_app_credential_id`, `sushy_app_credential_secret`, `demo_project_name`) remain unchanged so no other roles are affected.

### `site.yml`

Add a `pre_tasks` block (runs on `localhost`) to create `.ove-demo-cache/` before any role executes:

```yaml
pre_tasks:
  - name: Ensure local cache directory exists
    ansible.builtin.file:
      path: ".ove-demo-cache"
      state: directory
      mode: '0700'
    delegate_to: localhost
    run_once: true
```

### `teardown.yml`

- No changes to task logic: `project_name` and `sushy_password` are resolved via `group_vars/all.yml` lookups which already point to the new cache paths after the `all.yml` update.
- Add a final task to delete `.ove-demo-cache/` (`ansible.builtin.file`, `state: absent`, `delegate_to: localhost`) so a subsequent `site.yml` run starts fully fresh.

## Authentication for the Module

The sushy user is not in `clouds.yaml`, so the module uses inline authentication:

```yaml
auth:
  auth_url: "{{ os_auth_url }}"
  username: "{{ project_name }}-sushy"
  password: "{{ sushy_password }}"
  project_name: "{{ project_name }}"
  user_domain_name: "{{ project_domain }}"
  project_domain_name: "{{ project_domain }}"
auth_type: password
```

`os_auth_url` is already resolved earlier in the play (either from `group_vars` or the existing catalog-lookup CLI task).

## Out of Scope

- Replacing the `openstack catalog show` CLI task used to resolve `os_auth_url`
- Changes to any other role
