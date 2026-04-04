# OVE Appliance Demo Environment

Ansible automation to provision an OpenStack-hosted OVE (OpenShift Virtualization Engine) demo environment: project, networking, bastion VM, and bare-metal-emulated OVE nodes.

## Install Methods

Two install methods are controlled by `install_method` in inventory:

- **`ove`** (default) — Agent ISO boot: blank root volume + USB volume from agent ISO, UEFI intervention required
- **`appliance`** — Factory disk image: pre-built appliance.raw from `openshift-appliance` container, direct boot, no UEFI intervention required

## Prerequisites

- Python 3 with `venv`
- A `clouds.yaml` with credentials that can create projects and users

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

| Variable | Description |
|---|---|
| `cloud_name` | Cloud name from your `clouds.yaml` |
| `ssh_key_name` | OpenStack keypair name for bastion access |
| `os_auth_url` | OpenStack identity endpoint (e.g. `https://identity.example.com:5000/v3`) |
| `os_region` | OpenStack region name |
| `rh_subscription_org` | Red Hat subscription org ID |
| `rh_subscription_activation_key` | Red Hat activation key |
| `pull_secret` | (appliance mode only) Pull secret from console.redhat.com |

The `.ove-demo-cache/` directory holds generated secrets (project suffix, sushy password, app credential) and is gitignored. The project name suffix is stored here so teardown can find it automatically. Delete this directory to reset the project identity.

## Usage

Always activate the venv first:

```bash
source .venv/bin/activate
```

```bash
ansible-playbook site.yml              # Full build (idempotent)
ansible-playbook teardown.yml          # Destroy everything including project
ansible-playbook reset-ove-nodes.yml   # Reset nodes (OVE: blank root; appliance: re-factory)
```

For appliance mode, set `install_method: "appliance"` in `all.yml`. The appliance image is built on the bastion during `site.yml` (Play 3). To rebuild it separately:

```bash
ansible-playbook build-appliance-image.yml
```
