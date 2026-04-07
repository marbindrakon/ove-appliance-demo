# Appliance Mode Workflow (Factory Disk Image)

This guide walks through deploying an OVE demo environment using the
**appliance** method (`install_method: "appliance"`). In this mode each node
boots from a pre-built `appliance.raw` disk image that contains the agent
installer and all required operators. Nodes boot directly into the installer
with no UEFI intervention.

## Prerequisites

- Python 3 with `venv`
- **OpenStack backend**: A `clouds.yaml` with admin credentials; an OpenStack keypair for bastion SSH
- **libvirt backend**: A RHEL KVM host with root SSH access
- A pull secret from [console.redhat.com](https://console.redhat.com/)
- (Optional) A pre-built `appliance.raw` file, an existing Glance image, or an image already on the KVM host

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
| `install_method` | `"appliance"` |
| `infra_backend` | `"openstack"` or `"libvirt"` |
| `rh_subscription_org` | Red Hat subscription org ID |
| `rh_subscription_activation_key` | Red Hat activation key |
| `pull_secret` | Pull secret from console.redhat.com |

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

### Appliance Image Source

**OpenStack** — three options, checked in priority order:

1. **Existing Glance image** (fastest) -- Set `appliance_glance_image` to the
   name or ID of an image already in Glance. The playbook uses it directly and
   does **not** delete it on teardown. Use this when sharing a single image
   across multiple deployments.

2. **Pre-built image on the controller** -- Set `appliance_image_path` to the
   local path of an `appliance.raw` file. The playbook uploads it to Glance
   during Play 4, skipping the bastion build.

3. **Build on the bastion** (default) -- Leave both unset. The playbook builds
   the image on the bastion during Play 3 using `podman` and the
   `openshift-appliance` container, then uploads it to Glance.

**libvirt** — two options:

1. **Pre-built image on the KVM host** (fastest) -- Set
   `appliance_kvm_host_image_path` to the absolute path of an `appliance.raw`
   file already on the KVM host. This skips Play 3 entirely — no bastion
   build, no transfer.

2. **Build on the bastion** (default) -- Leave `appliance_kvm_host_image_path`
   unset. The playbook builds the image on the bastion during Play 3, then
   transfers it to the KVM host.

For libvirt, a qcow2 backing file chain is used: a shared `appliance-base.qcow2`
with thin-provisioned per-node overlay disks. Node resets are near-instant.

### Optional Tuning

| Variable | Default | Description |
|---|---|---|
| `appliance_ocp_version` | `4.20` | OpenShift version for the appliance |
| `appliance_ocp_channel` | `stable` | Release channel |
| `appliance_disk_size_gb` | `250` | Boot volume size (GB) |
| `appliance_cdrom_volume_gb` | `1` | CD-ROM volume size (GB) |
| `ove_node_flavor` | `g1.4xlarge` | Nova flavor for OVE nodes |
| `ove_node_count` | `4` | Number of OVE nodes |
| `ove_node_mgmt_ips` | `10.10.0.11-14` | Fixed management IPs (one per node) |
| `cluster_name` | `ove` | Cluster name for DNS |
| `base_domain` | `example.com` | Base DNS domain |
| `api_vip` | `10.10.0.100` | Kubernetes API VIP |
| `ingress_vip` | `10.10.0.101` | Ingress VIP |
| `appliance_enable_interactive_flow` | `false` | Enable interactive web UI instead of config image |

The appliance image includes a curated set of operators (ODF, GitOps, SR-IOV,
MetalLB, KubeVirt, cert-manager, NMState, and others). See
`roles/appliance_image/defaults/main.yml` for the full list. Customize by
editing `appliance_operators` in your inventory.

## 3. Deploy the Environment

```bash
source .venv/bin/activate
ansible-playbook site.yml
```

The playbook validates inputs, then runs backend-specific plays:

**OpenStack:**
1. **Create infrastructure** (localhost) -- project, networks, subnets, router, bastion VM with a floating IP.
2. **Configure bastion** (bastion via SSH) -- SSH key, RHSM, desktop, firewall, BIND DNS, NTP, sushy-emulator. The SSH public key generated here is embedded in the appliance image so the bastion can SSH to installed nodes.
3. **Build appliance image** (bastion via SSH) -- Templates `appliance-config.yaml`, runs the builder container, uploads to Glance. *Skipped if using an existing Glance image or a pre-built local image.*
4. **Create OVE nodes** (localhost) -- trunk ports, boot volumes from the appliance image, CD-ROM volumes for virtual media, launch VMs.

**libvirt:**
1. **Prepare KVM host** -- packages, libvirtd, OVS, storage pool, networking, bastion VM.
2. **Configure bastion** (bastion via SSH) -- SSH key, RHSM, desktop, firewall, BIND DNS, NTP.
3. **Build appliance image** (bastion via SSH) -- same as OpenStack but transfers to KVM host instead of Glance. *Skipped if `appliance_kvm_host_image_path` is set.*
4. **Create OVE nodes** (kvm-host) -- qcow2 overlay disks from appliance base, domain XML, OVS trunk ports.
5. **Sushy-emulator** (kvm-host) -- sushy with libvirt driver.

The playbook is idempotent and safe to re-run.

## 4. Configure and Build the OpenShift Cluster

The automation provisions the infrastructure and boots the nodes but does
**not** build the OpenShift cluster itself. After `site.yml` completes, each
node has two volumes:

- **boot_index 0** (disk): boot volume from `appliance.raw`
- **boot_index 1** (cdrom): blank CD-ROM for sushy virtual media

The node boots from the appliance image and the agent installer starts
automatically. There are two ways to deliver the cluster configuration,
depending on how the appliance image was built:

### Option A: Config image via sushy virtual media (default)

When `appliance_enable_interactive_flow` is `false` (the default), the
appliance expects a configuration ISO mounted via virtual media. From the
bastion VM, build a config image containing the cluster configuration and
use sushy-emulator's Redfish API (port 8000) to mount it to each node's
CD-ROM volume. The agent installer reads the config image and proceeds with
installation.

### Option B: Interactive web UI

If the appliance image was built with `appliance_enable_interactive_flow`
set to `true`, the nodes boot into an interactive mode instead. Log in to the
bastion VM (via SSH or the GNOME desktop) and use the assisted installer web
UI to configure and start the cluster installation, the same way as the agent
ISO method.

## 5. Monitor Progress

Monitor installation progress via the node console (OpenStack: Horizon or
`openstack console url show`; libvirt: `virt-manager` or `virsh console`) or
by SSH from the bastion once a node is reachable on its management IP.

## 6. Build the Appliance Image Separately

To build or rebuild the appliance image without running the full playbook:

```bash
ansible-playbook build-appliance-image.yml
```

This runs only the image build on the bastion. Useful for iterating on
`appliance_operators` or `appliance_ocp_version` without re-creating the
infrastructure.

## 7. Reset Nodes (Re-install)

To return nodes to their factory state and re-run the installer without
destroying the rest of the environment:

```bash
ansible-playbook reset-ove-nodes.yml
```

This rebuilds each node's boot volume with the appliance image. The CD-ROM
volume is left untouched. On next boot the node enters the agent installer
fresh, with no manual intervention required.

## 8. Tear Down Everything

To destroy the entire environment:

```bash
ansible-playbook teardown.yml
```

**OpenStack:** Deletes OVE node VMs and volumes, bastion (FIP, VM, volume,
ports), trunk ports and sub-ports, router and networks, sushy user, app
credential, project, and clouds.yaml entries. If `appliance_glance_image` was
set, that image is **not** deleted.

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

## Sushy Virtual Media

The CD-ROM volume on each node is used by sushy-emulator for virtual media
delivery of configuration ISOs, enabling automated node configuration without
direct console access.

- **OpenStack**: Sushy runs on the bastion with the OpenStack driver, port `8000 + lab_id`.
- **libvirt**: Sushy runs on the KVM host with the libvirt driver, reachable at `10.10.{lab_id}.254:{8000+lab_id}`.
