# OVE Appliance Demo Environment

Ansible playbooks to provision a disconnected OVE demo environment on OpenStack.

## Prerequisites

- Ansible 2.14+
- `openstack.cloud`, `ansible.utils`, and `ansible.posix` collections
- OpenStack CLI (`python-openstackclient`)
- A `clouds.yaml` with credentials that can create projects and users

## Setup

```bash
ansible-galaxy collection install -r requirements.yml
```

## Usage

1. Copy and edit the variables in `inventory/group_vars/all.yml` — at minimum set `cloud_name`, `ssh_key_name`, and `os_auth_url`.

2. Deploy the environment:
```bash
ansible-playbook site.yml
```

3. Tear down the environment:
```bash
ansible-playbook teardown.yml -e project_name=<your-project-name>
```

Note: Since `project_name` includes a random suffix, you must pass the actual project name used during creation when running teardown.
