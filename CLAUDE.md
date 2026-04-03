# OVE Appliance Demo

Ansible automation to provision an OpenStack-hosted OVE (OpenShift Virtualization Engine) demo environment: project, networking, bastion VM, and bare-metal-emulated OVE nodes booted from a pre-provisioned agent ISO.

## Commands

```bash
# Activate the venv before running anything
source .venv/bin/activate

ansible-playbook site.yml             # Full build (idempotent)
ansible-playbook teardown.yml         # Destroy everything including project
ansible-playbook reset-ove-nodes.yml  # Wipe OVE node root volumes to blank for re-installation (bastion untouched)
ansible-playbook unmount-ove-nodes.yml  # Reimage USB volumes back to blank
```

## Configuration

`inventory/group_vars/all.yml` is gitignored (secrets). Copy from `all.yml.sample` and fill in operator fields marked `# Must be set by operator`.

`.ove-demo-cache/` holds generated secrets (project suffix, sushy password, app credential). Gitignored. Delete to reset the project identity.

## Architecture

```
site.yml
├── openstack_project   — project, user, app credential, clouds.yaml entry
├── openstack_networking — networks, subnets (with dns_nameservers), router
├── bastion_vm          — ports, boot volume, floating IP, SSH wait
└── ove_nodes           — ISO upload, trunks, volumes, VMs
    └── bastion_configure (Play 2, SSH) — RHSM, desktop, firewall, BIND, NTP, sushy
```

## Key Design Points

**Boot flow**: Each OVE node has two volumes. `boot_index=0` is a blank root volume (no bootloader); `boot_index=1` is a virtio USB volume pre-provisioned from the agent ISO. On first boot the VM lands in the UEFI shell (unintended but retained — it gives the operator a chance to intervene). The operator must enter UEFI config and select the USB device to launch the agent installer. The installer writes OCP to the root volume; subsequent reboots come up from root. No `nova rebuild` required.

**Trunks**: Each node has two OpenStack trunks (trunk0/trunk1). The mgmt network (10.10.0.0/24) is the native/untagged VLAN on the parent port. Storage and workload VLANs are sub-ports. `trunk0` parent ports have fixed IPs (`ove_node_mgmt_ips`) and infinite DHCP lease time so coreos-install writes a static address. `trunk1` parent ports use `fixed_ips: []` to prevent any IP allocation.

**`openstack.cloud.trunk` bug**: The module silently ignores `sub_ports` on creation. `create_trunk.yml` calls it twice (create then update) and uses port *names* not IDs — the update path matches by `sp['name'] == k['port']`.

**DNS**: Bastion subnet and bastion-mgmt-port `extra_dhcp_opts` both advertise `dns_forwarders` (not the bastion itself) so BIND isn't needed before subscription. Mgmt subnet advertises `bastion_mgmt_ip` as nameserver for OVE nodes. BIND on the bastion is authoritative for `base_domain` and forwards everything else.
