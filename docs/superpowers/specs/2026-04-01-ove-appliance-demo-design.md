# OVE Appliance Demo Environment — Design Spec

## Overview

Ansible playbooks to create a demo/test environment for disconnected installation of OpenShift Virtualization Engine (OVE) using an appliance-based installer. The environment runs on OpenStack, with a fully configured bastion host and blank OVE node VMs ready for live installation during the demo.

## Architecture: Role-Based with Orchestrator

```
ove-appliance-demo/
├── site.yml                        # Orchestrator (two plays: infra + config)
├── teardown.yml                    # Destroy all resources
├── ansible.cfg
├── inventory/
│   ├── group_vars/
│   │   └── all.yml                 # Global configurable defaults
│   └── openstack.yml               # Dynamic inventory source
├── roles/
│   ├── openstack_project/          # Project, user, Application Credential
│   ├── openstack_networking/       # Networks, subnets, router, trunk ports
│   ├── bastion_vm/                 # Bastion instance, volume, ports, FIP
│   ├── ove_nodes/                  # 4 OVE node VMs with trunk ports
│   └── bastion_configure/          # GNOME, BIND, NTP, sushy, firewall
```

### site.yml Structure

**Play 1 — Infrastructure** (runs against `localhost` using OpenStack modules):
1. `openstack_project` role
2. `openstack_networking` role
3. `bastion_vm` role
4. `ove_nodes` role

**Play 2 — Bastion Configuration** (runs against `ove_demo_bastion` group via FIP):
1. `bastion_configure` role

### Dynamic Inventory

```yaml
plugin: openstack.cloud.openstack
only_clouds:
  - "{{ cloud_name }}"
expand_hostvars: true
fail_on_errors: true

keyed_groups:
  - key: openstack.metadata.role
    prefix: ove_demo
    separator: "_"
```

VMs are grouped by metadata: bastion → `ove_demo_bastion`, OVE nodes → `ove_demo_ove_node`.

## Networks

| Network          | CIDR             | DHCP    | Port Security | Purpose                     |
|------------------|------------------|---------|---------------|-----------------------------|
| External         | (provider)       | N/A     | N/A           | FIP for bastion             |
| Bastion          | 10.0.0.0/24      | Enabled | Enabled       | Bastion connectivity        |
| Trunk Native     | 10.99.0.0/24     | Disabled| Disabled      | Parent port for trunks      |
| OCP Management   | 10.10.0.0/24     | Disabled| Disabled      | VLAN 10 sub-port            |
| OCP Storage      | 10.20.0.0/24     | Disabled| Disabled      | VLAN 20 sub-port            |
| Workload 1       | 192.168.10.0/24  | Disabled| Disabled      | VLAN 30 sub-port            |
| Workload 2       | 192.168.20.0/24  | Disabled| Disabled      | VLAN 40 sub-port            |
| Workload 3       | 192.168.30.0/24  | Disabled| Disabled      | VLAN 50 sub-port            |

- One router with external gateway on `ext-net` and interface on bastion subnet.
- All network names, CIDRs, and VLAN IDs are configurable via defaults.

## Bastion VM

- **Flavor**: `g1.large` (configurable: `bastion_flavor`)
- **Image**: `rhel-9.5` (configurable: `bastion_image`)
- **Boot volume**: 250GB (configurable: `bastion_disk_gb`)
- **Metadata**: `role: bastion`
- **Ports**:
  - Bastion network port with floating IP from `ext-net`
  - OCP management network port (static IP, default: 10.10.0.1, configurable: `bastion_mgmt_ip`)
- **No IP forwarding**: The bastion must not route traffic between OCP management and external networks, enforcing the disconnected demo scenario.

### Bastion Services

**GNOME Desktop**: Installed via `@workstation` package group for demo presentation.

**BIND DNS**: Authoritative for the OVE cluster domain with:
- `api.<cluster_name>.<base_domain>` → API VIP (configurable, on management network)
- `*.apps.<cluster_name>.<base_domain>` → Ingress VIP (configurable, on management network)
- Defaults: `cluster_name: ove`, `base_domain: example.com`

**Chronyd NTP Server**: Configured to serve time to hosts on the OCP management network.

**sushy-emulator**: Provides Redfish BMC emulation for the OVE node VMs.
- Installed from custom fork: `github.com/marbindrakon/sushy-tools`
- Runs via gunicorn with systemd service unit
- OpenStack driver using Application Credential in `/root/.config/openstack/clouds.yaml`
- htpasswd authentication
- Listens on port 8000
- Blank image for ejected cdrom: `sushy-tools-blank-image` (configurable: sushy_blank_image)
- Virtual media feature set enabled

## OVE Node VMs (x4)

- **Flavor**: `g1.4xlarge` (configurable: `ove_node_flavor`)
- **Count**: 4 (configurable: `ove_node_count`)
- **Boot volume**: 250GB, created from sushy_blank_image (configurable: ove_node_disk_gb)
- **Metadata**: `role: ove_node`
- **Naming**: `ove-node-0` through `ove-node-3` (prefix configurable: `ove_node_name_prefix`)

### Trunk Ports

Each node has 2 trunk ports simulating dual NICs on bare metal. Each trunk has:
- **Parent port**: on trunk-native network (10.99.0.0/24)
- **Sub-ports**:
  - VLAN 10 → OCP management network
  - VLAN 20 → OCP storage network
  - VLAN 30 → Workload 1
  - VLAN 40 → Workload 2
  - VLAN 50 → Workload 3

Total per node: 2 parent ports + 10 sub-ports = 12 ports.

## OpenStack Project & Credentials

1. **Project**: Created with configurable name, default `ove-demo-<random 5 chars>`.
2. **Sushy service user**: Created with `member` role on the project (e.g., `<project_name>-sushy`).
3. **Application Credential**: Created under the sushy user, scoped to the project, used in the sushy-emulator `clouds.yaml`.

The playbooks run using the operator's existing `clouds.yaml` credentials, which must have privileges to create projects and users.

## Configurable Defaults Summary

| Variable               | Default                          |
|------------------------|----------------------------------|
| `cloud_name`           | (from operator's clouds.yaml)    |
| `external_network`     | `ext-net`                        |
| `project_name`         | `ove-demo-<random 5 chars>`      |
| `bastion_flavor`       | `g1.large`                       |
| `bastion_image`        | `rhel-9.5`                       |
| `ove_node_flavor`      | `g1.4xlarge`                     |
| `ove_node_count`       | `4`                              |
| `ove_node_name_prefix` | `ove-node`                       |
| `cluster_name`         | `ove`                            |
| `base_domain`          | `example.com`                    |
| `bastion_mgmt_ip`      | `10.10.0.1`                      |
| `bastion_disk_gb`      | `250`                            |
| `ove_node_disk_gb`     | `250`                            |
| `sushy_blank_image`    | `sushy-tools-blank-image`        |

Network CIDRs, VLAN IDs, and VIP addresses are also configurable with the defaults described in the Networks section.

## Teardown

`teardown.yml` destroys all resources in reverse order:
1. Delete OVE node VMs and their volumes
2. Delete bastion VM, its volume, and floating IP
3. Delete trunk ports and sub-ports
4. Delete router interfaces and router
5. Delete networks and subnets
6. Delete Application Credential, sushy service user, and project
