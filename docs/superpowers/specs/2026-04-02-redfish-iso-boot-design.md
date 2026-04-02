# Redfish ISO Boot — Design Spec

## Overview

A standalone day-2 Ansible playbook (`boot-ove-nodes.yml`) that copies the OVE agent ISO to the bastion host and boots all four OVE node VMs from it via Redfish, using sushy-emulator as the Redfish BMC backend.

## Architecture

Two complementary changes:

1. **`bastion_configure` role** — gains a new `httpd.yml` task file that installs Apache httpd and opens port 80 in firewalld. This is included by `main.yml` so the bastion is HTTP-ready after `site.yml` runs.
2. **`boot-ove-nodes.yml`** — standalone playbook with two plays, both targeting `ove_demo_bastion`.

```
boot-ove-nodes.yml          # Day-2 playbook
roles/
  bastion_configure/
    tasks/
      httpd.yml             # New: install httpd, firewall, start service
      main.yml              # Updated: include httpd.yml
agent-ove.x86_64.iso        # Default ISO location (gitignored)
.gitignore                  # Updated: agent-ove.x86_64.iso added
```

## Variable

| Variable | Default | Description |
|---|---|---|
| `ove_agent_iso_path` | `{{ playbook_dir }}/agent-ove.x86_64.iso` | Local path to OVE agent ISO |

Passed at runtime via `-e` if overriding the default:
```
ansible-playbook boot-ove-nodes.yml -e ove_agent_iso_path=/path/to/ove-agent.iso
```

## bastion_configure: httpd.yml

New task file included in `main.yml`. Runs with `become: true` as part of `site.yml` Play 2.

1. Install `httpd` via `ansible.builtin.dnf`
2. Open `http` service in firewalld `trusted` zone (same zone as management interface `eth1`) via `ansible.posix.firewalld`
3. Start and enable `httpd` via `ansible.builtin.systemd`

## boot-ove-nodes.yml: Play 1 — Copy ISO

**Targets**: `ove_demo_bastion` | **become**: true

1. Copy `{{ ove_agent_iso_path }}` to `/var/www/html/` on the bastion using `ansible.builtin.copy`

The ISO is then accessible to sushy-emulator at `http://localhost/{{ ove_agent_iso_path | basename }}`.

## boot-ove-nodes.yml: Play 2 — Boot Nodes via Redfish

**Targets**: `ove_demo_bastion` | **become**: false

Loops over `groups['ove_demo_ove_node']` (OVE node VMs from dynamic inventory). Each iteration resolves `system_id: "{{ hostvars[item].openstack.id }}"` — the OpenStack VM UUID used by sushy-emulator as the Redfish system identifier.

Three `community.general.redfish_command` tasks per node:

| Step | Category | Command | Key Parameters |
|---|---|---|---|
| 1 | Manager | VirtualMediaInsert | `image_url: http://localhost/<iso-filename>`, `media_types: [CD]` |
| 2 | Systems | SetOneTimeBoot | `bootdevice: Cd` |
| 3 | Systems | PowerOn | — |

All tasks use `baseuri: "localhost:{{ sushy_port }}"`, `username: "{{ sushy_username }}"`, `password: "{{ sushy_password }}"`. Requests originate from the bastion, reaching sushy-emulator without crossing the firewalld zone boundary.

## Redfish Reachability

sushy-emulator listens on `0.0.0.0:{{ sushy_port }}` but port 8000 is only open in the `trusted` firewalld zone (management interface). The operator machine cannot reach it via the floating IP. By running Play 2 on `ove_demo_bastion`, all Redfish calls go to `localhost:{{ sushy_port }}` and bypass the firewall entirely.

## Pivot Path

If `community.general.redfish_command` proves incompatible with sushy-emulator's VirtualMedia implementation, replace the three `redfish_command` tasks with `ansible.builtin.uri` calls targeting the same `localhost:{{ sushy_port }}` endpoint with explicit Redfish REST payloads.
