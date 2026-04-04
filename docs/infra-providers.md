# Infrastructure Providers

The OVE demo environment supports two infrastructure backends, selected by `infra_backend` in `inventory/group_vars/all.yml`. Both provide the same demo environment: a bastion VM with DNS/NTP and 4 OVE node VMs with VLAN-trunked networking.

## OpenStack Backend (`infra_backend: "openstack"`)

### Prerequisites

- OpenStack cloud with admin-level credentials in `clouds.yaml`
- Sufficient quota: 5 VMs, ~1500 GB block storage, 6 networks, trunking support
- Provider/external network for floating IPs
- RHEL 9.x image and an OpenStack keypair uploaded

### Architecture

```
site.yml
 Play 1 (localhost):
 ├── openstack_project    — project, user, app credential, clouds.yaml entry
 ├── openstack_networking — 6 networks/subnets, router
 └── bastion_vm           — ports, boot volume, floating IP, SSH wait
 Play 2 (bastion SSH):
 └── bastion_configure    — SSH key, RHSM, desktop/podman, firewall, BIND, NTP, sushy-emulator
 Play 3 (bastion SSH, appliance mode only):
 └── appliance_image      — build appliance.raw on bastion, upload to Glance
 Play 4 (localhost):
 └── ove_nodes            — Neutron trunks, Cinder volumes, Nova VMs
```

### Networking

Six Neutron networks are created in a dedicated project:

| Network | CIDR | DHCP | Port Security | Purpose |
|---------|------|------|---------------|---------|
| bastion | 10.0.0.0/24 | Yes | Yes | Bastion external access (router to provider net) |
| mgmt | 10.10.0.0/24 | Yes | No | OVE node management, trunk native VLAN |
| storage | 10.20.0.0/24 | No | No | Cluster storage (VLAN 20) |
| workload1 | 192.168.10.0/24 | No | No | Workload network (VLAN 30) |
| workload2 | 192.168.20.0/24 | No | No | Workload network (VLAN 40) |
| workload3 | 192.168.30.0/24 | No | No | Workload network (VLAN 50) |

Each OVE node has two Neutron trunk ports. The mgmt network is the native/untagged VLAN on the parent port; storage and workload networks are tagged sub-ports.

### Sushy-Emulator

Runs on the bastion VM with the OpenStack driver (`SUSHY_EMULATOR_OS_CLOUD`). Uses an application credential scoped to the demo project to manage Nova VMs via the Redfish API.

### Image Management

- **OVE mode**: Agent ISO uploaded to Glance, used to create USB volumes
- **Appliance mode**: `appliance.raw` built on bastion and uploaded to Glance, or referenced as a pre-existing Glance image

### Required Variables

| Variable | Description |
|---|---|
| `cloud_name` | Admin cloud from `clouds.yaml` |
| `ssh_key_name` | OpenStack keypair for bastion |
| `os_auth_url` | Identity v3 endpoint |
| `os_region` | OpenStack region |
| `external_network` | Provider network for floating IPs |
| `bastion_flavor` | Nova flavor for bastion |
| `bastion_image` | Glance image name for bastion |
| `ove_node_flavor` | Nova flavor for OVE nodes |

---

## libvirt Backend (`infra_backend: "libvirt"`)

### Prerequisites

- RHEL 9.x KVM host with root SSH access from the Ansible controller
- Sufficient resources: ~80 vCPUs, ~270 GB RAM, ~1.5 TB disk (for 4 OVE nodes + bastion)
- RHEL 9.x qcow2 guest image available on the KVM host
- Nested virtualization enabled (`kvm_intel.nested=1` or `kvm_amd.nested=1`)

The `kvm_host_prepare` role installs required packages (libvirt, qemu-kvm, Open vSwitch, genisoimage) and configures services automatically.

### Architecture

```
site.yml
 Play 1 (localhost):
 └── add KVM host to inventory
 Play 1b (kvm-host):
 ├── kvm_host_prepare      — packages, libvirtd, OVS, storage pool
 ├── libvirt_networking    — OVS bridge, NAT network, port forwarding, dnsmasq
 └── libvirt_bastion       — qcow2 copy, cloud-init ISO, domain XML, OVS port
 Play 2 (bastion SSH via port forward):
 └── bastion_configure     — SSH key, RHSM, desktop/podman, firewall, BIND, NTP (no sushy)
 Play 3 (bastion SSH, appliance mode only):
 └── appliance_image       — build appliance.raw on bastion (no Glance upload)
 Play 4b (kvm-host):
 └── libvirt_ove_nodes     — disk images, domain XML, OVS trunk port config
 Play 5 (kvm-host):
 └── kvm_sushy             — sushy-emulator with libvirt driver
```

### Networking

A single Open vSwitch bridge (`br-ove`) carries all OVE traffic using 802.1Q VLANs:

| VLAN | Network | CIDR | Purpose |
|------|---------|------|---------|
| 10 (native) | mgmt | 10.10.0.0/24 | Management, trunk native VLAN |
| 20 | storage | 10.20.0.0/24 | Cluster storage |
| 30 | workload1 | 192.168.10.0/24 | Workload network |
| 40 | workload2 | 192.168.20.0/24 | Workload network |
| 50 | workload3 | 192.168.30.0/24 | Workload network |

A separate libvirt NAT network (`ove-bastion-nat`, default `192.168.122.0/24`) provides the bastion's external connectivity via iptables port forwarding on the KVM host.

**OVS port types:**
- **Bastion mgmt port** (`bastion-mgmt`): access port on VLAN 10
- **KVM host internal port** (`mgmt-host`): access port on VLAN 10, IP `10.10.0.254` — for sushy-emulator reachability
- **OVE node trunk ports** (`ovenode{N}-t{0,1}`): `native-untagged` mode with VLAN 10 as PVID, trunking VLANs 10,20,30,40,50

This replicates the OpenStack trunk behavior: the VM sees mgmt as untagged frames, and storage/workload traffic with VLAN tags intact.

**DHCP:** A `dnsmasq` instance on the KVM host's `mgmt-host` interface provides DHCP for the mgmt network with static MAC-to-IP assignments. MAC addresses are deterministic, generated from `mac_prefix` and the node index.

### Bastion Access

The bastion VM has two NICs:
1. NAT network — gets DHCP from libvirt (`192.168.122.10`)
2. OVS bridge — static IP `10.10.0.1` on mgmt VLAN

SSH access is via port forwarding: `ssh -p 2222 cloud-user@<kvm-host-ip>` forwards to the bastion's NAT interface. The forward port is configurable via `bastion_ssh_forward_port`.

### Sushy-Emulator

Runs directly on the KVM host (not the bastion) with the libvirt driver:

```python
SUSHY_EMULATOR_DRIVER = 'libvirt'
SUSHY_EMULATOR_LIBVIRT_URI = 'qemu:///system'
```

Listens on `0.0.0.0:8000`, reachable from OVE nodes at `10.10.0.254:8000` via the `mgmt-host` OVS internal port.

### Image Management

- **OVE mode**: Agent ISO copied to KVM host storage pool, one copy per node as a virtio disk
- **Appliance mode**: `appliance.raw` built on bastion and transferred to KVM host via SCP over the mgmt network, or provided directly via `appliance_image_path`

### OVS Trunk Port Persistence

OVS port VLAN settings are lost when a VM restarts (libvirt recreates the tap device). The `configure_ovs_trunks.yml` task re-applies settings after VM start. The `reset-ove-nodes.yml` playbook also reconfigures trunks after restarting nodes.

### Required Variables

| Variable | Description |
|---|---|
| `kvm_host` | IP or hostname of the KVM host |
| `kvm_host_user` | SSH user (default: `root`) |
| `kvm_host_ssh_key` | Path to SSH private key (optional, uses ssh-agent if empty) |
| `bastion_qcow2_image` | Path to RHEL 9.x qcow2 on the KVM host |
| `ssh_public_key` | SSH public key content for bastion cloud-init |
| `bastion_vcpus` / `bastion_ram_mb` | Bastion VM sizing (default: 4 / 8192) |
| `ove_node_vcpus` / `ove_node_ram_mb` | OVE node VM sizing (default: 16 / 65536) |
| `libvirt_pool_path` | Storage pool path (default: `/var/lib/libvirt/images/ove-demo`) |
| `ovs_bridge_name` | OVS bridge name (default: `br-ove`) |
| `mac_prefix` | MAC address prefix (default: `52:54:00:10`) |

---

## Variable Reference

| Variable | OpenStack | libvirt | Description |
|---|---|---|---|
| `infra_backend` | Required | Required | `"openstack"` or `"libvirt"` |
| `install_method` | Both | Both | `"ove"` or `"appliance"` |
| `cloud_name` | Required | — | Admin cloud name |
| `ssh_key_name` | Required | — | OpenStack keypair |
| `os_auth_url` | Required | — | Identity endpoint |
| `kvm_host` | — | Required | KVM host address |
| `bastion_qcow2_image` | — | Required | RHEL qcow2 path on KVM host |
| `ssh_public_key` | — | Required | SSH public key for cloud-init |
| `bastion_flavor` | Required | — | Nova flavor |
| `bastion_vcpus` | — | Optional | vCPUs (default: 4) |
| `bastion_ram_mb` | — | Optional | RAM in MB (default: 8192) |
| `ove_node_flavor` | Required | — | Nova flavor |
| `ove_node_vcpus` | — | Optional | vCPUs (default: 16) |
| `ove_node_ram_mb` | — | Optional | RAM in MB (default: 65536) |
