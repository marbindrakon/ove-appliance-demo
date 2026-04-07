# OVE Mode Workflow (Agent ISO Boot)

This guide walks through deploying an OVE demo environment using the default
**agent ISO boot** method (`install_method: "ove"`). In this mode each node
boots from a USB volume containing the agent ISO. On first boot the operator
must select the USB device in UEFI to launch the installer, which then writes
OpenShift to the root volume.

## Prerequisites

- Python 3 with `venv`
- **OpenStack backend**: A `clouds.yaml` with admin credentials; an OpenStack keypair for bastion SSH
- **libvirt backend**: A RHEL KVM host with root SSH access
- An OVE agent ISO file (typically `agent-ove.x86_64.iso`, ~41 GB)

## 1. Set Up the Python Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml
```

## 2. Configure Inventory

```bash
cp inventory/group_vars/all.yml.sample inventory/group_vars/all.yml
```

Edit `inventory/group_vars/all.yml` and set:

| Variable | Description |
|---|---|
| `install_method` | `"ove"` (this is the default) |
| `infra_backend` | `"openstack"` or `"libvirt"` |
| `rh_subscription_org` | Red Hat subscription org ID |
| `rh_subscription_activation_key` | Red Hat activation key |

**OpenStack-specific:**

| Variable | Description |
|---|---|
| `cloud_name` | Cloud name from your `clouds.yaml` |
| `ssh_key_name` | OpenStack keypair name for bastion SSH access |
| `os_auth_url` | OpenStack identity endpoint |
| `os_region` | OpenStack region name |

**libvirt-specific:**

| Variable | Description |
|---|---|
| `kvm_host` | IP or hostname of the KVM host |
| `bastion_qcow2_image` | Path to RHEL 9.x qcow2 image on the KVM host |
| `ssh_public_key` | SSH public key content for bastion cloud-init |

### Agent ISO Source

**OpenStack:** By default the playbook uploads the ISO from the controller at
the path specified by `ove_agent_iso_path` (defaults to
`./agent-ove.x86_64.iso`). To use an ISO that already exists in Glance, set
`ove_agent_glance_image` to the image name or ID — this skips the upload, and
the image is not deleted on teardown.

**libvirt:** By default the ISO is transferred from the controller to the KVM
host. To use an ISO already on the KVM host, set `ove_kvm_host_iso_path` to
its absolute path — this skips the transfer.

### Optional Tuning

| Variable | Default | Description |
|---|---|---|
| `ove_node_flavor` | `g1.4xlarge` | Nova flavor for OVE nodes |
| `ove_node_count` | `4` | Number of OVE nodes |
| `ove_node_disk_gb` | `250` | Root volume size (GB) |
| `ove_usb_volume_gb` | `50` | USB volume size (must be >= ISO size) |
| `ove_node_mgmt_ips` | `10.10.0.11-14` | Fixed management IPs (one per node) |
| `cluster_name` | `ove` | Cluster name for DNS |
| `base_domain` | `example.com` | Base DNS domain |
| `api_vip` | `10.10.0.100` | Kubernetes API VIP |
| `ingress_vip` | `10.10.0.101` | Ingress VIP |

## 3. Deploy the Environment

```bash
source .venv/bin/activate
ansible-playbook site.yml
```

The playbook validates inputs, then runs backend-specific plays:

**OpenStack:**
1. **Create infrastructure** (localhost) -- project, networks, subnets, router, bastion VM with a floating IP.
2. **Configure bastion** (bastion via SSH) -- SSH key, RHSM, desktop, firewall, BIND DNS, NTP, sushy-emulator.
3. *(skipped in OVE mode)*
4. **Create OVE nodes** (localhost) -- Upload agent ISO to Glance (unless `ove_agent_glance_image` is set), create trunk ports, root and USB volumes, launch VMs.

**libvirt:**
1. **Prepare KVM host** -- packages, libvirtd, OVS, storage pool, networking, bastion VM.
2. **Configure bastion** (bastion via SSH) -- SSH key, RHSM, desktop, firewall, BIND DNS, NTP.
3. *(skipped in OVE mode)*
4. **Create OVE nodes** (kvm-host) -- disk images, domain XML, OVS trunk ports.
5. **Sushy-emulator** (kvm-host) -- sushy with libvirt driver.

The playbook is idempotent and safe to re-run.

## 4. Complete the UEFI Boot (Per Node)

After `site.yml` completes, each OVE node has two volumes:

- **boot_index 0**: blank root volume (no bootloader)
- **boot_index 1**: USB volume with the agent ISO

On first boot the VM fails to boot from the blank root volume and drops into
the UEFI shell. You must manually select the USB device to start the agent
installer:

1. Open the node's console (OpenStack: Horizon or `openstack console url show`; libvirt: `virt-manager` or `virsh console`).
2. Enter UEFI setup and change the boot order to boot from the USB device.
3. Save and reboot.
4. The agent installer starts and writes OpenShift to the root volume.
5. Subsequent reboots will come up from the root volume automatically.

Repeat for each node.

## 5. Build the OpenShift Cluster

The automation provisions the infrastructure and boots the nodes but does
**not** build the OpenShift cluster itself. Once all nodes have booted into
the agent installer, log in to the bastion VM (via SSH or the GNOME desktop)
and use the assisted installer web UI to configure and start the cluster
installation.

## 6. Reset Nodes (Re-install)

To wipe the root volumes and re-run the installer without destroying the rest
of the environment:

```bash
ansible-playbook reset-ove-nodes.yml
```

This rebuilds each node's root volume with a blank image. The USB volume is
left untouched. On next boot the node falls through to the USB device again
and performs a clean installation. You will need to repeat the UEFI boot
selection.

## 7. Tear Down Everything

To destroy the entire environment including the OpenStack project:

```bash
ansible-playbook teardown.yml
```

**OpenStack:** Deletes OVE node VMs and volumes, bastion (FIP, VM, volume,
ports), trunk ports and sub-ports, router and networks, sushy user, app
credential, project, and clouds.yaml entries.

**libvirt:** Destroys OVE node domains and disks, bastion domain and disks,
OVS bridge, NAT network, dnsmasq and sushy services. Pass
`-e destroy_shared=true` to also remove the shared storage pool and appliance
base images.

Both backends delete the lab's `.ove-demo-cache/lab-{lab_id}/` directory.

## Network Layout

Each OVE node gets two trunk ports (trunk0, trunk1). The management network
(`10.10.0.0/24`) is the native/untagged VLAN on the parent port. Additional
networks are carried as tagged VLAN sub-ports:

| VLAN | Network | CIDR |
|------|---------|------|
| 10 | Management | `10.10.0.0/24` |
| 20 | Storage | `10.20.0.0/24` |
| 30 | Workload 1 | `192.168.10.0/24` |
| 40 | Workload 2 | `192.168.20.0/24` |
| 50 | Workload 3 | `192.168.30.0/24` |

The bastion sits on a separate bastion network (`10.0.0.0/24`) with a
floating IP, and also has a port on the management network at
`10.10.0.1`. BIND on the bastion is authoritative for the cluster domain
and forwards all other queries to `dns_forwarders`.
