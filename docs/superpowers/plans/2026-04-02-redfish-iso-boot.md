# Redfish ISO Boot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `boot-ove-nodes.yml` playbook that copies the OVE agent ISO to the bastion and boots all four OVE node VMs from it via Redfish.

**Architecture:** Apache httpd is added to the `bastion_configure` role so the bastion is HTTP-ready after `site.yml` runs. A standalone day-2 playbook copies the ISO to `/var/www/html/` on the bastion, then makes Redfish calls from the bastion to the local sushy-emulator (`localhost:{{ sushy_port }}`) to mount the ISO and power on each node.

**Tech Stack:** Ansible `ansible.builtin.copy`, `ansible.builtin.dnf`, `ansible.posix.firewalld`, `ansible.builtin.systemd`, `community.general.redfish_command`

---

### Task 1: Add httpd to bastion_configure role

**Files:**
- Create: `roles/bastion_configure/tasks/httpd.yml`
- Modify: `roles/bastion_configure/tasks/main.yml`

- [ ] **Step 1: Create `roles/bastion_configure/tasks/httpd.yml`**

```yaml
---
- name: Install Apache httpd
  ansible.builtin.dnf:
    name: httpd
    state: present

- name: Allow HTTP on management interface
  ansible.posix.firewalld:
    service: http
    zone: trusted
    permanent: true
    immediate: true
    state: enabled

- name: Start and enable httpd
  ansible.builtin.systemd:
    name: httpd
    state: started
    enabled: true
```

- [ ] **Step 2: Add httpd include to `roles/bastion_configure/tasks/main.yml`**

Add after the existing `sushy` include at the end of the file:

```yaml
- name: Configure Apache httpd
  ansible.builtin.include_tasks: httpd.yml
```

The full file should now end with:

```yaml
- name: Configure sushy-emulator
  ansible.builtin.include_tasks: sushy.yml

- name: Configure Apache httpd
  ansible.builtin.include_tasks: httpd.yml
```

- [ ] **Step 3: Verify syntax**

```bash
ansible-playbook site.yml --syntax-check
```

Expected: `playbook: site.yml` with no errors.

- [ ] **Step 4: Commit**

```bash
git add roles/bastion_configure/tasks/httpd.yml roles/bastion_configure/tasks/main.yml
git commit -m "feat: add httpd to bastion_configure role"
```

---

### Task 2: Add ISO to .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add ISO filename to `.gitignore`**

Append to the existing `.gitignore`:

```
agent-ove.x86_64.iso
```

The full `.gitignore` should now read:

```
.ove-demo-cache/
inventory/group_vars/all.yml
agent-ove.x86_64.iso
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore OVE agent ISO"
```

---

### Task 3: Create boot-ove-nodes.yml playbook

**Files:**
- Create: `boot-ove-nodes.yml`

- [ ] **Step 1: Create `boot-ove-nodes.yml`**

```yaml
---
# boot-ove-nodes.yml — Day-2 playbook: copy OVE agent ISO and boot all nodes via Redfish
#
# Usage:
#   ansible-playbook boot-ove-nodes.yml
#   ansible-playbook boot-ove-nodes.yml -e ove_agent_iso_path=/path/to/custom.iso
#
# Requires: bastion already configured via site.yml (httpd running, sushy-emulator running)

- name: Copy OVE agent ISO to bastion
  hosts: ove_demo_bastion
  become: true
  gather_facts: false
  vars:
    ove_agent_iso_path: "{{ playbook_dir }}/agent-ove.x86_64.iso"
  tasks:
    - name: Copy OVE agent ISO to web root
      ansible.builtin.copy:
        src: "{{ ove_agent_iso_path }}"
        dest: "/var/www/html/{{ ove_agent_iso_path | basename }}"
        mode: "0644"

- name: Boot OVE nodes via Redfish
  hosts: ove_demo_bastion
  gather_facts: false
  vars:
    ove_agent_iso_path: "{{ playbook_dir }}/agent-ove.x86_64.iso"
    ove_iso_url: "http://localhost/{{ ove_agent_iso_path | basename }}"
  tasks:
    - name: Insert virtual media for OVE node
      community.general.redfish_command:
        category: Manager
        command: VirtualMediaInsert
        baseuri: "localhost:{{ sushy_port }}"
        username: "{{ sushy_username }}"
        password: "{{ sushy_password }}"
        virtual_media:
          image_url: "{{ ove_iso_url }}"
          media_types:
            - CD
        resource_id: "{{ hostvars[item].openstack.id }}"
      loop: "{{ groups['ove_demo_ove_node'] }}"

    - name: Set one-time boot from CD for OVE node
      community.general.redfish_command:
        category: Systems
        command: SetOneTimeBoot
        baseuri: "localhost:{{ sushy_port }}"
        username: "{{ sushy_username }}"
        password: "{{ sushy_password }}"
        bootdevice: Cd
        resource_id: "{{ hostvars[item].openstack.id }}"
      loop: "{{ groups['ove_demo_ove_node'] }}"

    - name: Power on OVE node
      community.general.redfish_command:
        category: Systems
        command: PowerOn
        baseuri: "localhost:{{ sushy_port }}"
        username: "{{ sushy_username }}"
        password: "{{ sushy_password }}"
        resource_id: "{{ hostvars[item].openstack.id }}"
      loop: "{{ groups['ove_demo_ove_node'] }}"
```

- [ ] **Step 2: Verify syntax**

```bash
ansible-playbook boot-ove-nodes.yml --syntax-check
```

Expected: `playbook: boot-ove-nodes.yml` with no errors.

- [ ] **Step 3: Commit**

```bash
git add boot-ove-nodes.yml
git commit -m "feat: add boot-ove-nodes.yml playbook"
```

---

### Task 4: Run and verify

This task requires a live environment with `site.yml` already applied and the ISO present at the default path.

- [ ] **Step 1: Confirm httpd is running on the bastion (if site.yml was run before this change, re-run the bastion play)**

```bash
ansible-playbook site.yml --limit ove_demo_bastion
```

Expected: play completes with no failures. The new httpd tasks appear in the output.

- [ ] **Step 2: Place the OVE agent ISO in the playbook directory**

```bash
ls agent-ove.x86_64.iso
```

Expected: file exists.

- [ ] **Step 3: Run the boot playbook**

```bash
ansible-playbook boot-ove-nodes.yml -vv
```

Expected output (4 iterations each):
- `Insert virtual media for OVE node` → `changed`
- `Set one-time boot from CD for OVE node` → `changed`
- `Power on OVE node` → `changed`

- [ ] **Step 4: Confirm nodes are powered on via Redfish**

SSH to the bastion and query the power state of each node. Substitute `<node-uuid>` with one of the OVE node VM UUIDs (visible in the `-vv` output or via `openstack server list`):

```bash
curl -s -u <sushy_username>:<sushy_password> \
  http://localhost:8000/redfish/v1/Systems/<node-uuid> \
  | python3 -m json.tool | grep PowerState
```

Expected: `"PowerState": "On"` for each node.
