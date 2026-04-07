# OVE Appliance Demo

Ansible automation to provision an OVE (OpenShift Virtualization Engine) demo environment: networking, bastion VM, and bare-metal-emulated OVE nodes. Supports two infrastructure backends controlled by `infra_backend` in inventory:

- **`openstack`** (default) — Provisions on OpenStack (Neutron networking, Nova VMs, Cinder volumes)
- **`libvirt`** — Provisions on a RHEL KVM host using libvirt and Open vSwitch for VLAN trunking. Supports multiple independent labs per host via `lab_id`

Supports two install methods controlled by `install_method` in inventory:

- **`ove`** (default) — Agent ISO boot: blank root volume + USB volume from agent ISO, UEFI intervention required
- **`appliance`** — Factory disk image: pre-built appliance.raw from `openshift-appliance` container, direct boot, blank CD-ROM volume for sushy virtual media config delivery

## Commands

```bash
# Activate the venv before running anything
source .venv/bin/activate

ansible-playbook site.yml             # Full build (idempotent)
ansible-playbook teardown.yml         # Destroy everything including project
ansible-playbook reset-ove-nodes.yml  # Reset nodes (OVE: blank root; appliance: re-factory)
```

## Configuration

`inventory/group_vars/all.yml` is gitignored (secrets). Copy from `all.yml.sample` and fill in operator fields marked `# Must be set by operator`.

`.ove-demo-cache/` holds generated secrets (project suffix, sushy password, app credential). Gitignored. Delete to reset the project identity.

For appliance mode, set `install_method: "appliance"` and provide `pull_secret` (from console.redhat.com). The appliance image config (`appliance-config.yaml`) is templated from inventory variables including `appliance_ocp_version`, `appliance_operators`, and related settings in `roles/appliance_image/defaults/main.yml`. Image supply options (OpenStack, in priority order): set `appliance_glance_image` to reference an existing Glance image (not deleted on teardown), set `appliance_image_path` to upload a pre-built `appliance.raw` from the controller, or leave both unset to build on the bastion. For libvirt, an additional option exists: set `appliance_kvm_host_image_path` to an absolute path of a pre-built `appliance.raw` already on the KVM host — this skips Play 3 entirely and uses the file directly as the node boot image source (no bastion build, no transfer). For OVE mode, set `ove_agent_glance_image` to reference an existing Glance image (OpenStack) instead of uploading a local ISO, or set `ove_kvm_host_iso_path` to an absolute path of an agent ISO already on the KVM host (libvirt) to skip the controller transfer.

## Architecture

### OpenStack backend
```
site.yml
 Play 1 (localhost):
 ├── openstack_project    — project, user, app credential, clouds.yaml entry
 ├── openstack_networking — networks, subnets (with dns_nameservers), router
 └── bastion_vm           — ports, boot volume, floating IP, SSH wait
 Play 2 (bastion SSH):
 └── bastion_configure    — SSH key, RHSM, desktop/podman, firewall, BIND, NTP, sushy
 Play 3 (bastion SSH, appliance mode only):
 └── appliance_image      — build appliance.raw on bastion, upload to Glance
 Play 4 (localhost):
 └── ove_nodes            — trunks, volumes, VMs (branches on install_method)
```

### libvirt backend
```
site.yml
 Play 1 (localhost):
 └── add KVM host to inventory
 Play 1b (kvm-host):
 ├── kvm_host_prepare     — packages, libvirtd, OVS, shared storage pool
 ├── libvirt_networking   — OVS bridge br-ove-{lab_id}, NAT network, dnsmasq (all lab_id-scoped)
 └── libvirt_bastion      — qcow2 copy, cloud-init ISO, domain XML, OVS port config
 Play 2 (bastion SSH via ProxyCommand):
 └── bastion_configure    — SSH key, RHSM, desktop/podman, firewall, BIND, NTP (no sushy)
 Play 3 (bastion SSH, appliance mode only):
 └── appliance_image      — build appliance.raw on bastion (no Glance upload)
 Play 4b (kvm-host):
 └── libvirt_ove_nodes    — disk images, domain XML, OVS trunk ports
 Play 5 (kvm-host):
 └── kvm_sushy            — sushy-emulator with libvirt driver on KVM host (lab_id-scoped port/service)
```

## Key Design Points

**Boot flow (OVE mode)**: Each OVE node has two volumes. `boot_index=0` is a blank root volume (no bootloader); `boot_index=1` is a virtio USB volume pre-provisioned from the agent ISO. On first boot the VM lands in the UEFI shell (unintended but retained — it gives the operator a chance to intervene). The operator must enter UEFI config and select the USB device to launch the agent installer. The installer writes OCP to the root volume; subsequent reboots come up from root. No `nova rebuild` required.

**Boot flow (appliance mode)**: Each node has a single boot volume (`boot_index=0`) from the pre-built `appliance.raw` image plus a blank CD-ROM volume (`boot_index=1`, `device_type=cdrom`, `disk_bus=sata`) for sushy virtual media delivery of configuration ISOs. The appliance boots directly into the agent installer with no UEFI intervention. The appliance image is built on the bastion using `podman` with the `openshift-appliance` container and uploaded to Glance via the `sushy-cloud` credential by the `appliance_image` role.

**Bastion SSH key**: The `bastion_configure` role generates an ed25519 SSH key pair for `cloud-user`. In appliance mode, the public key is read by the `appliance_image` role and embedded in the appliance config so the bastion can SSH to installed nodes.

**Trunks (OpenStack)**: Each node has two OpenStack trunks (trunk0/trunk1). The mgmt network (10.10.0.0/24) is the native/untagged VLAN on the parent port. Storage and workload VLANs are sub-ports. `trunk0` parent ports have fixed IPs (`ove_node_mgmt_ips`) and infinite DHCP lease time so coreos-install writes a static address. `trunk1` parent ports use `fixed_ips: []` to prevent any IP allocation.

**Trunks (libvirt)**: OVS trunk ports use `vlan_mode=native-untagged` with mgmt VLAN as PVID and storage/workload VLANs trunked. Port names are predictable (`l{lab_id}-n{N}-t{0,1}`) via `<target dev>` in domain XML. OVS settings are lost on VM restart; `configure_ovs_trunks.yml` re-applies after start.

**`openstack.cloud.trunk` bug**: The module silently ignores `sub_ports` on creation. `create_trunk.yml` calls it twice (create then update) and uses port *names* not IDs — the update path matches by `sp['name'] == k['port']`.

**DNS**: Bastion subnet and bastion-mgmt-port `extra_dhcp_opts` both advertise `dns_forwarders` (not the bastion itself) so BIND isn't needed before subscription. Mgmt subnet advertises `bastion_mgmt_ip` as nameserver for OVE nodes. BIND on the bastion is authoritative for `base_domain` and forwards everything else.

**Sushy-emulator placement**: In OpenStack mode, sushy runs on the bastion with the OpenStack driver. In libvirt mode, sushy runs on the KVM host with the libvirt driver (`qemu:///system`), reachable at `10.10.{lab_id}.254:{8000+lab_id}` via the OVS `l{lab_id}-mgmt` internal port. The `bastion_configure` role conditionally skips sushy setup when `infra_backend == 'libvirt'`.

**Multi-lab isolation (libvirt)**: The `lab_id` variable (integer 0–55, set in inventory) namespaces all per-lab resources on a KVM host: OVS bridge (`br-ove-{lab_id}`), NAT network (`ove-nat-{lab_id}`), dnsmasq/sushy services, IP ranges (`10.10.{lab_id}.0/24` mgmt, `10.20.{lab_id}.0/24` storage, `192.168.{200+lab_id}.0/24` NAT), MAC prefix, and SSH/sushy ports. The libvirt storage pool is shared across labs; disk images are differentiated by `project_name` prefix. Teardown destroys only the lab's resources; pass `-e destroy_shared=true` to also remove the shared pool and appliance base images. VLAN IDs are per-bridge and do not conflict across labs.
