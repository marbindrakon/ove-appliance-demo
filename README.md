# OVE Appliance Demo Environment

Ansible automation to provision an OVE (OpenShift Virtualization Engine) demo environment: networking, bastion VM, and bare-metal-emulated OVE nodes. Supports two infrastructure backends controlled by `infra_backend` in inventory:

- **`openstack`** (default) — Provisions on an OpenStack cloud (project, Neutron networking, Nova VMs)
- **`libvirt`** — Provisions on a single RHEL KVM host using libvirt and Open vSwitch for VLAN trunking

## Install Methods

Two install methods are controlled by `install_method` in inventory (work with both backends):

- **`ove`** (default) — Agent ISO boot: blank root volume + USB volume from agent ISO, UEFI intervention required
- **`appliance`** — Factory disk image: pre-built appliance.raw from `openshift-appliance` container, direct boot, no UEFI intervention required

See [docs/infra-providers.md](docs/infra-providers.md) for detailed backend-specific documentation.

## Prerequisites

- Python 3 with `venv`
- **OpenStack backend**: A `clouds.yaml` with credentials that can create projects and users
- **libvirt backend**: A RHEL KVM host with root SSH access, sufficient CPU/RAM/disk for bastion + OVE nodes

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Ansible collections
ansible-galaxy collection install -r requirements.yml
```

## Configuration

```bash
cp inventory/group_vars/all.yml.sample inventory/group_vars/all.yml
```

Edit `inventory/group_vars/all.yml` and fill in all fields marked `# Must be set by operator`:

**Common variables:**

| Variable | Description |
|---|---|
| `infra_backend` | `"openstack"` or `"libvirt"` |
| `rh_subscription_org` | Red Hat subscription org ID |
| `rh_subscription_activation_key` | Red Hat activation key |
| `pull_secret` | (appliance mode only) Pull secret from console.redhat.com |

**OpenStack backend:**

| Variable | Description |
|---|---|
| `cloud_name` | Cloud name from your `clouds.yaml` |
| `ssh_key_name` | OpenStack keypair name for bastion access |
| `os_auth_url` | OpenStack identity endpoint (e.g. `https://identity.example.com:5000/v3`) |
| `os_region` | OpenStack region name |

**libvirt backend:**

| Variable | Description |
|---|---|
| `kvm_host` | IP or hostname of the KVM host |
| `bastion_qcow2_image` | Path to RHEL 9.x qcow2 image on the KVM host |
| `ssh_public_key` | SSH public key content for bastion cloud-init injection |

The `.ove-demo-cache/lab-{lab_id}/` directory holds per-lab generated secrets (project suffix, sushy password, app credential) and is gitignored. Delete a lab's cache subdirectory to reset that lab's project identity.

## Usage

Always activate the venv first:

```bash
source .venv/bin/activate
```

### Single Lab

```bash
ansible-playbook site.yml              # Full build (idempotent)
ansible-playbook teardown.yml          # Destroy everything including project
ansible-playbook reset-ove-nodes.yml   # Reset nodes (OVE: blank root; appliance: re-factory)
```

Use tags for selective execution:

```bash
ansible-playbook site.yml --tags nodes          # Only create OVE nodes
ansible-playbook site.yml --tags bastion,nodes   # Skip infra, configure bastion + nodes
ansible-playbook site.yml --list-tags            # Show all available tags
```

Available tags: `infra`, `networking`, `bastion`, `nodes`, `appliance`, `sushy`, `openstack`, `libvirt`.

For appliance mode, set `install_method: "appliance"` in `all.yml`. The appliance image is built on the bastion during `site.yml` (Play 3). To rebuild it separately:

```bash
ansible-playbook build-appliance-image.yml
```

### Multiple Labs

The `manage-labs.sh` script deploys, tears down, or resets multiple labs in parallel. Each lab is defined by a YAML file in `labs/` that sets `lab_id`, `infra_backend`, `install_method`, and any per-lab overrides (see `labs/*.yml.sample` for examples).

```bash
# Deploy specific labs in parallel
./manage-labs.sh deploy labs/openstack-appliance.yml labs/libvirt-ove.yml

# Teardown a single lab
./manage-labs.sh teardown labs/libvirt-appliance.yml

# Deploy/teardown/reset all labs in labs/
./manage-labs.sh deploy-all
./manage-labs.sh teardown-all
./manage-labs.sh reset-all
```

Each lab runs as a background process. Logs are written to `logs/YYYYMMDD-HHMMSS/<lab-name>.log` and a summary is printed when all labs finish.

The `lab_id` variable (integer 0--55) isolates each lab's resources: credential cache, network address space, sushy port, and (for libvirt) OVS bridges, NAT networks, dnsmasq/sushy services, and MAC addresses. See [docs/infra-providers.md](docs/infra-providers.md) for details.
