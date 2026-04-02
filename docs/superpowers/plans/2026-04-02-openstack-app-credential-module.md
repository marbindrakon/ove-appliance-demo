# OpenStack App Credential Module Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CLI-based application credential management with `openstack.cloud.application_credential`, consolidate all local state into `.ove-demo-cache/`, and persist the credential secret locally so subsequent runs can retrieve it without recreating it.

**Architecture:** The `openstack.cloud.application_credential` module creates the credential idempotently; the secret (only returned at creation time) is written to `.ove-demo-cache/sushy-app-credential-secret`. Subsequent runs detect the absent secret in the module result and slurp it from the cache file instead. All generated local state (project suffix, sushy password, app credential id/secret) lives under `.ove-demo-cache/`.

**Tech Stack:** Ansible, openstack.cloud 2.5.0, `openstack.cloud.application_credential`

---

## Files Modified

| File | Change |
|------|--------|
| `.gitignore` | Replace two dotfile entries with `.ove-demo-cache/` |
| `inventory/group_vars/all.yml` | Update two `lookup('password', ...)` paths |
| `site.yml` | Add `pre_tasks` block to create cache directory |
| `teardown.yml` | Add `pre_tasks` block; replace CLI delete with module; add cache cleanup |
| `roles/openstack_project/tasks/main.yml` | Replace 4 CLI/parse tasks with module + cache read/write tasks |

---

## Task 1: Consolidate cache file paths

**Files:**
- Modify: `.gitignore`
- Modify: `inventory/group_vars/all.yml`

- [ ] **Step 1: Update .gitignore**

Replace the entire file content with:

```
.ove-demo-cache/
```

- [ ] **Step 2: Update group_vars lookup paths**

In `inventory/group_vars/all.yml`, make these two edits:

Line 10 — change:
```yaml
project_name: "ove-demo-{{ lookup('password', '.ove-demo-project-suffix chars=ascii_lowercase,digits length=5') }}"
```
to:
```yaml
project_name: "ove-demo-{{ lookup('password', '.ove-demo-cache/project-suffix chars=ascii_lowercase,digits length=5') }}"
```

Line 15 — change:
```yaml
sushy_password: "{{ lookup('password', '.ove-demo-sushy-password chars=ascii_letters,digits length=24') }}"
```
to:
```yaml
sushy_password: "{{ lookup('password', '.ove-demo-cache/sushy-password chars=ascii_letters,digits length=24') }}"
```

- [ ] **Step 3: Verify with ansible-lint (if available)**

```bash
ansible-lint inventory/group_vars/all.yml 2>/dev/null || echo "ansible-lint not available, skipping"
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore inventory/group_vars/all.yml
git commit -m "refactor: consolidate cache files into .ove-demo-cache/"
```

---

## Task 2: Ensure cache directory is created before lookups evaluate

**Files:**
- Modify: `site.yml`
- Modify: `teardown.yml`

The `lookup('password', ...)` calls in `group_vars/all.yml` evaluate lazily — when `project_name` or `sushy_password` is first referenced in a task. The `.ove-demo-cache/` directory must exist at that point. A `pre_tasks` block in each playbook guarantees this.

- [ ] **Step 1: Add pre_tasks to site.yml**

`site.yml` currently starts at line 4 with the play definition. Insert a `pre_tasks` block so the file reads:

```yaml
# site.yml — OVE Appliance Demo Environment Orchestrator
---
# Play 1: Create OpenStack infrastructure (project, networks, VMs)
- name: Create OVE demo infrastructure
  hosts: localhost
  connection: local
  gather_facts: false
  pre_tasks:
    - name: Ensure local cache directory exists
      ansible.builtin.file:
        path: ".ove-demo-cache"
        state: directory
        mode: '0700'
  roles:
    - openstack_project
    - openstack_networking
    - bastion_vm
    - ove_nodes

# Play 2: Configure bastion host services
- name: Configure bastion host
  hosts: ove_demo_bastion
  gather_facts: true
  become: true
  vars:
    os_auth_url: "{{ lookup('env', 'OS_AUTH_URL') | default(hostvars['localhost']['os_auth_url'], true) }}"
    os_region: "{{ lookup('env', 'OS_REGION_NAME') | default(hostvars['localhost']['os_region'] | default('RegionOne'), true) }}"
    sushy_app_credential_id: "{{ hostvars['localhost']['sushy_app_credential_id'] }}"
    sushy_app_credential_secret: "{{ hostvars['localhost']['sushy_app_credential_secret'] }}"
  roles:
    - bastion_configure
```

- [ ] **Step 2: Add pre_tasks to teardown.yml**

`teardown.yml` begins with `- name: Tear down OVE demo environment` at line 3. Insert a `pre_tasks` block before the `tasks:` key so teardown also creates the cache dir before any variable is first evaluated:

```yaml
# teardown.yml — Destroy all OVE demo resources
---
- name: Tear down OVE demo environment
  hosts: localhost
  connection: local
  gather_facts: false
  pre_tasks:
    - name: Ensure local cache directory exists
      ansible.builtin.file:
        path: ".ove-demo-cache"
        state: directory
        mode: '0700'
  tasks:
    # ... rest of file unchanged ...
```

(Only the `pre_tasks:` block is new; everything inside `tasks:` stays identical for now.)

- [ ] **Step 3: Commit**

```bash
git add site.yml teardown.yml
git commit -m "refactor: create .ove-demo-cache/ before playbook tasks run"
```

---

## Task 3: Replace CLI application credential tasks in openstack_project role

**Files:**
- Modify: `roles/openstack_project/tasks/main.yml`

This is the core change. Remove lines 75–115 (the delete CLI task, create CLI task, parse JSON task, and store facts task) and replace them with the module call + cache read/write tasks shown below.

- [ ] **Step 1: Remove the four CLI/parse tasks (lines 75–115)**

Delete from `roles/openstack_project/tasks/main.yml`:

```yaml
- name: Delete existing application credential if present
  ansible.builtin.command:
    cmd: >-
      openstack application credential delete
      --os-auth-url {{ os_auth_url }}
      --os-username {{ project_name }}-sushy
      --os-password {{ sushy_password }}
      --os-project-name {{ project_name }}
      --os-user-domain-name {{ project_domain }}
      --os-project-domain-name {{ project_domain }}
      {{ project_name }}-sushy-credential
  failed_when: false
  changed_when: false
  no_log: true

- name: Create application credential for sushy user
  ansible.builtin.command:
    cmd: >-
      openstack application credential create
      --os-auth-url {{ os_auth_url }}
      --os-username {{ project_name }}-sushy
      --os-password {{ sushy_password }}
      --os-project-name {{ project_name }}
      --os-user-domain-name {{ project_domain }}
      --os-project-domain-name {{ project_domain }}
      -f json
      {{ project_name }}-sushy-credential
  register: sushy_app_credential_raw
  changed_when: sushy_app_credential_raw.rc == 0
  no_log: true

- name: Parse application credential output
  ansible.builtin.set_fact:
    sushy_app_credential: "{{ sushy_app_credential_raw.stdout | from_json }}"

- name: Store application credential details
  ansible.builtin.set_fact:
    sushy_app_credential_id: "{{ sushy_app_credential.id }}"
    sushy_app_credential_secret: "{{ sushy_app_credential.secret }}"
    demo_project_name: "{{ project_name }}"
    cacheable: true
```

- [ ] **Step 2: Insert replacement tasks in the same location**

In place of the removed tasks, insert:

```yaml
- name: Ensure application credential exists for sushy user
  openstack.cloud.application_credential:
    auth:
      auth_url: "{{ os_auth_url }}"
      username: "{{ project_name }}-sushy"
      password: "{{ sushy_password }}"
      project_name: "{{ project_name }}"
      user_domain_name: "{{ project_domain }}"
      project_domain_name: "{{ project_domain }}"
    auth_type: password
    name: "{{ project_name }}-sushy-credential"
    state: present
  register: sushy_app_credential_result
  no_log: true

- name: Write application credential to cache
  when:
    - sushy_app_credential_result.application_credential.secret is defined
    - sushy_app_credential_result.application_credential.secret is not none
  block:
    - name: Write application credential id to cache
      ansible.builtin.copy:
        content: "{{ sushy_app_credential_result.application_credential.id }}"
        dest: ".ove-demo-cache/sushy-app-credential-id"
        mode: '0600'

    - name: Write application credential secret to cache
      ansible.builtin.copy:
        content: "{{ sushy_app_credential_result.application_credential.secret }}"
        dest: ".ove-demo-cache/sushy-app-credential-secret"
        mode: '0600'
      no_log: true

- name: Read application credential from cache
  when: >-
    sushy_app_credential_result.application_credential.secret is not defined
    or sushy_app_credential_result.application_credential.secret is none
  block:
    - name: Read application credential id from cache
      ansible.builtin.slurp:
        src: ".ove-demo-cache/sushy-app-credential-id"
      register: cached_app_cred_id

    - name: Read application credential secret from cache
      ansible.builtin.slurp:
        src: ".ove-demo-cache/sushy-app-credential-secret"
      register: cached_app_cred_secret
      no_log: true

- name: Store application credential facts from module result
  when:
    - sushy_app_credential_result.application_credential.secret is defined
    - sushy_app_credential_result.application_credential.secret is not none
  ansible.builtin.set_fact:
    sushy_app_credential_id: "{{ sushy_app_credential_result.application_credential.id }}"
    sushy_app_credential_secret: "{{ sushy_app_credential_result.application_credential.secret }}"
    demo_project_name: "{{ project_name }}"
    cacheable: true

- name: Store application credential facts from cache
  when: >-
    sushy_app_credential_result.application_credential.secret is not defined
    or sushy_app_credential_result.application_credential.secret is none
  ansible.builtin.set_fact:
    sushy_app_credential_id: "{{ cached_app_cred_id.content | b64decode | trim }}"
    sushy_app_credential_secret: "{{ cached_app_cred_secret.content | b64decode | trim }}"
    demo_project_name: "{{ project_name }}"
    cacheable: true
```

- [ ] **Step 3: Verify yaml syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('roles/openstack_project/tasks/main.yml'))" && echo "YAML OK"
```

Expected output: `YAML OK`

- [ ] **Step 4: Commit**

```bash
git add roles/openstack_project/tasks/main.yml
git commit -m "feat: replace CLI app credential tasks with openstack.cloud module"
```

---

## Task 4: Replace CLI delete in teardown.yml and add cache cleanup

**Files:**
- Modify: `teardown.yml`

Two changes: replace the CLI `application credential delete` task with the module, and add a final task to wipe `.ove-demo-cache/`.

- [ ] **Step 1: Replace CLI delete task (lines 134–147)**

Remove:

```yaml
    - name: Delete application credential
      ansible.builtin.command:
        cmd: >-
          openstack application credential delete
          --os-auth-url {{ os_auth_url }}
          --os-username {{ project_name }}-sushy
          --os-password {{ sushy_password }}
          --os-project-name {{ project_name }}
          --os-user-domain-name {{ project_domain }}
          --os-project-domain-name {{ project_domain }}
          {{ project_name }}-sushy-credential
      failed_when: false
      changed_when: true
      no_log: true
```

Replace with:

```yaml
    - name: Delete application credential for sushy user
      openstack.cloud.application_credential:
        auth:
          auth_url: "{{ os_auth_url }}"
          username: "{{ project_name }}-sushy"
          password: "{{ sushy_password }}"
          project_name: "{{ project_name }}"
          user_domain_name: "{{ project_domain }}"
          project_domain_name: "{{ project_domain }}"
        auth_type: password
        name: "{{ project_name }}-sushy-credential"
        state: absent
      failed_when: false
      no_log: true
```

- [ ] **Step 2: Add cache cleanup as the final task in teardown.yml**

After the last task in teardown.yml (`Remove demo cloud entry from clouds.yaml`, currently ending around line 180), append:

```yaml
    # --- Clean up local credential cache ---
    - name: Remove local credential cache
      ansible.builtin.file:
        path: ".ove-demo-cache"
        state: absent
```

- [ ] **Step 3: Verify yaml syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('teardown.yml'))" && echo "YAML OK"
```

Expected output: `YAML OK`

- [ ] **Step 4: Commit**

```bash
git add teardown.yml
git commit -m "feat: replace CLI app credential delete with module; clean up cache on teardown"
```

---

## Verification

After all tasks are complete, verify end-to-end on a real OpenStack environment:

**First run (credential creation path):**
```bash
ansible-playbook site.yml --tags openstack_project  # or run full playbook
```
- `.ove-demo-cache/` directory is created with mode `0700`
- `.ove-demo-cache/sushy-app-credential-id` and `sushy-app-credential-secret` are written with mode `0600`
- No `openstack` CLI invocations in the play output for the credential tasks

**Second run (credential cache-read path):**
```bash
ansible-playbook site.yml
```
- Credential module task shows `changed=false`
- Facts are loaded from cache files — bastion configuration still receives valid `sushy_app_credential_id` and `sushy_app_credential_secret`

**Teardown:**
```bash
ansible-playbook teardown.yml
```
- Application credential deleted via module (no CLI task)
- `.ove-demo-cache/` directory removed at end of play
