# Infrastructure Providers

The OVE demo environment supports two infrastructure backends, selected by `infra_backend` in `inventory/group_vars/all.yml`. Both provide the same demo environment: a bastion VM with DNS/NTP and OVE node VMs with VLAN-trunked networking. The `lab_id` variable (integer 0--55, default 0) isolates each lab's resources so multiple labs can coexist on the same infrastructure.

## OpenStack Backend (`infra_backend: "openstack"`)

### Prerequisites

- OpenStack cloud with admin-level credentials in `clouds.yaml`
- Sufficient quota: 5 VMs, ~1500 GB block storage, 6 networks, trunking support
- Provider/external network for floating IPs
- RHEL 9.x image and an OpenStack keypair uploaded

### Architecture

```
site.yml
 Play 0 (localhost):
 └── validate_inputs      — assert required variables, validate backend/install_method
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

- **OVE mode**: Agent ISO uploaded to Glance (or set `ove_agent_glance_image` to reference an existing image)
- **Appliance mode**: `appliance.raw` built on bastion and uploaded to Glance, uploaded from the controller via `appliance_image_path`, or referenced as a pre-existing Glance image via `appliance_glance_image`

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
 Play 0 (localhost):
 └── validate_inputs       — assert required variables, validate backend/install_method
 Play 1 (localhost):
 └── add KVM host to inventory
 Play 1b (kvm-host):
 ├── kvm_host_prepare      — packages, libvirtd, OVS, shared storage pool
 ├── libvirt_networking    — OVS bridge, NAT network, dnsmasq (all lab_id-scoped)
 └── libvirt_bastion       — qcow2 copy, virt-customize, domain XML, OVS port
 Play 2 (bastion SSH via ProxyCommand):
 └── bastion_configure     — SSH key, RHSM, desktop/podman, firewall, BIND, NTP (no sushy)
 Play 3 (bastion SSH, appliance mode only):
 └── appliance_image       — build appliance.raw on bastion (no Glance upload)
 Play 4b (kvm-host):
 └── libvirt_ove_nodes     — disk images, domain XML, OVS trunk port config
 Play 5 (kvm-host):
 └── kvm_sushy             — sushy-emulator with libvirt driver (lab_id-scoped port/service)
```

### Networking

All resource names and IP ranges are scoped by `lab_id` so multiple labs can coexist on the same KVM host. The examples below show `lab_id: 0`; substitute your lab's ID for other deployments.

A per-lab Open vSwitch bridge (`br-ove-{lab_id}`) carries all OVE traffic using 802.1Q VLANs:

| VLAN | Network | CIDR (lab_id=0) | Purpose |
|------|---------|------|---------|
| 10 (native) | mgmt | 10.10.0.0/24 | Management, trunk native VLAN |
| 20 | storage | 10.20.0.0/24 | Cluster storage |
| 30 | workload1 | 192.168.10.0/24 | Workload network |
| 40 | workload2 | 192.168.20.0/24 | Workload network |
| 50 | workload3 | 192.168.30.0/24 | Workload network |

A separate libvirt NAT network (`ove-nat-{lab_id}`, `192.168.{200+lab_id}.0/24`) provides the bastion's external connectivity via iptables port forwarding on the KVM host.

**OVS port types:**
- **Bastion mgmt port** (`l{lab_id}-bst`): access port on VLAN 10
- **KVM host internal port** (`l{lab_id}-mgmt`): access port on VLAN 10, IP `10.10.{lab_id}.254` — for sushy-emulator reachability
- **OVE node trunk ports** (`l{lab_id}-n{N}-t{0,1}`): `native-untagged` mode with VLAN 10 as PVID, trunking VLANs 10,20,30,40,50

VLAN IDs are per-bridge and do not conflict across labs. This replicates the OpenStack trunk behavior: the VM sees mgmt as untagged frames, and storage/workload traffic with VLAN tags intact.

**DHCP:** A per-lab `dnsmasq` instance (`dnsmasq-ove-{lab_id}-mgmt`) on the KVM host's `l{lab_id}-mgmt` interface provides DHCP for the mgmt network with static MAC-to-IP assignments. MAC addresses are deterministic, generated from `mac_prefix` (`52:54:00:{lab_id_hex}`) and the node index.

### Bastion Access

The bastion VM has two NICs:
1. NAT network — gets DHCP from libvirt (`192.168.{200+lab_id}.10`)
2. OVS bridge — static IP `10.10.{lab_id}.1` on mgmt VLAN

SSH access is via port forwarding: `ssh -p {2222+lab_id} cloud-user@<kvm-host-ip>` forwards to the bastion's NAT interface. The forward port is derived from `lab_id` (`bastion_ssh_forward_port: {{ 2222 + lab_id }}`).

### Sushy-Emulator

Runs directly on the KVM host (not the bastion) with the libvirt driver:

```python
SUSHY_EMULATOR_DRIVER = 'libvirt'
SUSHY_EMULATOR_LIBVIRT_URI = 'qemu:///system'
```

Listens on port `8000 + lab_id`, reachable from OVE nodes at `10.10.{lab_id}.254:{8000+lab_id}` via the `l{lab_id}-mgmt` OVS internal port. Each lab gets its own systemd service (`sushy-ove-{lab_id}`).

### Image Management

- **OVE mode**: Agent ISO copied to KVM host storage pool (or set `ove_kvm_host_iso_path` to an absolute path of an ISO already on the KVM host to skip the transfer)
- **Appliance mode**: `appliance.raw` built on bastion and transferred to KVM host, or set `appliance_kvm_host_image_path` to an absolute path of a pre-built image already on the KVM host (skips Play 3 entirely — no bastion build, no transfer)

For appliance mode, the KVM host uses a qcow2 backing file chain: a shared `appliance-base.qcow2` with thin-provisioned per-node overlay disks. Node resets are near-instant via `qemu-img create -b`.

### OVS Trunk Port Persistence

OVS port VLAN settings are lost when a VM restarts (libvirt recreates the tap device). The `configure_ovs_trunks.yml` task re-applies settings after VM start. The `reset-ove-nodes.yml` playbook also reconfigures trunks after restarting nodes.

### Multi-Lab Isolation

The `lab_id` variable namespaces all per-lab resources on a KVM host so multiple labs can run independently. The libvirt storage pool is shared across labs; disk images are differentiated by `project_name` prefix. Teardown destroys only the targeted lab's resources. Pass `-e destroy_shared=true` to also remove the shared pool and appliance base images.

| Resource | Naming Pattern |
|---|---|
| OVS bridge | `br-ove-{lab_id}` |
| NAT network | `ove-nat-{lab_id}` |
| Mgmt subnet | `10.10.{lab_id}.0/24` |
| Storage subnet | `10.20.{lab_id}.0/24` |
| NAT subnet | `192.168.{200+lab_id}.0/24` |
| MAC prefix | `52:54:00:{lab_id_hex}` |
| SSH forward port | `2222 + lab_id` |
| Sushy port | `8000 + lab_id` |
| dnsmasq service | `dnsmasq-ove-{lab_id}-mgmt` |
| Sushy service | `sushy-ove-{lab_id}` |

### Required Variables

| Variable | Description |
|---|---|
| `kvm_host` | IP or hostname of the KVM host |
| `kvm_host_user` | SSH user (default: `root`) |
| `kvm_host_ssh_key` | Path to SSH private key (optional, uses ssh-agent if empty) |
| `bastion_qcow2_image` | Path to RHEL 9.x qcow2 on the KVM host |
| `ssh_public_key` | SSH public key content for bastion cloud-init |
| `lab_id` | Lab identifier, 0--55 (default: `0`). Scopes all per-lab resources |
| `bastion_vcpus` / `bastion_ram_mb` | Bastion VM sizing (default: 4 / 8192) |
| `ove_node_vcpus` / `ove_node_ram_mb` | OVE node VM sizing (default: 16 / 65536) |
| `libvirt_pool_path` | Storage pool path (default: `/var/lib/libvirt/images/ove-demo`) |
| `appliance_kvm_host_image_path` | (appliance) Pre-built `appliance.raw` on KVM host — skips bastion build |
| `ove_kvm_host_iso_path` | (OVE) Agent ISO on KVM host — skips controller transfer |

---

## Variable Reference

| Variable | OpenStack | libvirt | Description |
|---|---|---|---|
| `infra_backend` | Required | Required | `"openstack"` or `"libvirt"` |
| `install_method` | Both | Both | `"ove"` or `"appliance"` |
| `lab_id` | Both | Both | Lab identifier, 0--55 (default: 0) |
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
| `appliance_glance_image` | Optional | — | Existing Glance image name/ID |
| `appliance_image_path` | Optional | — | Local `appliance.raw` to upload |
| `appliance_kvm_host_image_path` | — | Optional | `appliance.raw` already on KVM host |
| `ove_agent_glance_image` | Optional | — | Existing agent ISO in Glance |
| `ove_kvm_host_iso_path` | — | Optional | Agent ISO already on KVM host |
