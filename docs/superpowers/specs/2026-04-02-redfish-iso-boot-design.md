# Redfish ISO Boot — Design Spec

## Overview

During `site.yml`, the bastion is configured with everything needed to boot the OVE nodes from an ISO via Redfish. A self-contained boot playbook and static Redfish inventory are templated onto the bastion at provisioning time and run locally from there — no OpenStack dynamic inventory or controller cloud credentials required at boot time.

## Architecture

Three additions to the existing `bastion_configure` role, plus a new `boot_prep.yml` task file:

```
roles/
  bastion_configure/
    tasks/
      httpd.yml             # Existing: install httpd, firewall, start service
      boot_prep.yml         # New: ansible-core, collection, copy ISO, template files
      main.yml              # Updated: includes httpd.yml and boot_prep.yml
    templates/
      ove-redfish-inventory.ini.j2   # New: static inventory with 4 node names
      boot-ove-nodes.yml.j2          # New: self-contained boot playbook
inventory/
  group_vars/
    all.yml.sample          # Updated: adds ove_agent_iso_path
```

The controller-side `boot-ove-nodes.yml` (created earlier) is removed — superseded by the bastion-local version.

## Variable

| Variable | Where set | Default | Description |
|---|---|---|---|
| `ove_agent_iso_path` | `inventory/group_vars/all.yml` | `{{ playbook_dir }}/agent-ove.x86_64.iso` | Path to OVE agent ISO on the controller |

## boot_prep.yml Tasks

Runs as part of `bastion_configure` role (Play 2 of `site.yml`) with `become: true`.

1. **Install ansible-core** — `ansible.builtin.dnf`, name: ansible-core
2. **Install community.general collection** — `ansible.builtin.command` running `ansible-galaxy collection install community.general`
3. **Copy ISO to web root** — `ansible.builtin.copy` src: `{{ ove_agent_iso_path }}`, dest: `/var/www/html/{{ ove_agent_iso_path | basename }}`
4. **Template Redfish inventory** — `ansible.builtin.template` → `/root/ove-redfish-inventory.ini`
5. **Template boot playbook** — `ansible.builtin.template` → `/root/boot-ove-nodes.yml`

## ove-redfish-inventory.ini.j2

Static INI inventory with one entry per OVE node, using the known naming pattern:

```ini
[ove_nodes]
{{ project_name }}-{{ ove_node_name_prefix }}-0
{{ project_name }}-{{ ove_node_name_prefix }}-1
...
```

Node names follow the pattern `{project_name}-{ove_node_name_prefix}-{i}` for i in 0..ove_node_count-1. sushy-emulator redirects name-based Redfish URLs to the UUID-based ones, so no UUID discovery is needed.

## boot-ove-nodes.yml.j2

Self-contained playbook templated onto the bastion. Static values (`sushy_port`, `sushy_username`, `sushy_password`, ISO filename) are baked in at template time. `{{ inventory_hostname }}` is preserved as a Jinja2 expression using `{% raw %}` so it evaluates when the generated playbook runs.

```yaml
- name: Boot OVE nodes from ISO via Redfish
  hosts: ove_nodes
  connection: local
  gather_facts: false
  tasks:
    - name: Insert ISO as virtual media     # resource_id: {{ inventory_hostname }}
    - name: Set one-time boot from CD       # bootdevice: Cd
    - name: Power on
```

All three tasks use `community.general.redfish_command` with `baseuri: localhost:<sushy_port>` and `no_log: true`. `resource_id` is the node name from the inventory hostname.

## Running the Boot Playbook

From the bastion:

```bash
ansible-playbook /root/boot-ove-nodes.yml -i /root/ove-redfish-inventory.ini
```

## Pivot Path

If sushy-emulator does not redirect name-based Redfish URLs to UUIDs, the static inventory approach still works — the inventory would need to carry the UUIDs instead of names. UUIDs could be gathered in Play 1 by registering `openstack.cloud.server` results and storing them as facts on localhost, then accessed in Play 2 via `hostvars['localhost']` to template the inventory.
