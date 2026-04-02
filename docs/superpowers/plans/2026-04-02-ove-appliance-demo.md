# OVE Appliance Demo Environment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create Ansible playbooks that provision a complete disconnected OVE demo environment on OpenStack — including project, networks, bastion VM (with GNOME, BIND, NTP, sushy-emulator), and 4 blank OVE node VMs with VLAN trunk ports.

**Architecture:** Role-based Ansible project with an orchestrator `site.yml` (two plays: infrastructure on localhost, configuration on bastion via FIP) and a `teardown.yml` for cleanup. Roles: `openstack_project`, `openstack_networking`, `bastion_vm`, `ove_nodes`, `bastion_configure`.

**Tech Stack:** Ansible, `openstack.cloud` collection, BIND, Chrony, sushy-tools, GNOME, RHEL 9/10

**Reference project:** `/home/aaustin/cc-workspaces/oso-dz-testbed` — follow its conventions for OpenStack module usage, template style, and verification patterns.

---

## File Structure

```
ove-appliance-demo/
├── ansible.cfg
├── requirements.yml
├── site.yml
├── teardown.yml
├── inventory/
│   ├── group_vars/
│   │   └── all.yml
│   └── openstack.yml
├── roles/
│   ├── openstack_project/
│   │   ├── defaults/main.yml
│   │   └── tasks/main.yml
│   ├── openstack_networking/
│   │   ├── defaults/main.yml
│   │   └── tasks/main.yml
│   ├── bastion_vm/
│   │   ├── defaults/main.yml
│   │   └── tasks/main.yml
│   ├── ove_nodes/
│   │   ├── defaults/main.yml
│   │   └── tasks/main.yml
│   └── bastion_configure/
│       ├── defaults/main.yml
│       ├── tasks/main.yml
│       ├── templates/
│       │   ├── named.conf.j2
│       │   ├── ove-zone.db.j2
│       │   ├── ove-reverse.db.j2
│       │   ├── chrony.conf.j2
│       │   ├── sushy-emulators.conf.j2
│       │   ├── sushy-emulators.service.j2
│       │   ├── sushy-emulators.htpasswd.j2
│       │   └── clouds.yaml.j2
│       └── files/
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `ansible.cfg`
- Create: `requirements.yml`
- Create: `inventory/group_vars/all.yml`
- Create: `inventory/openstack.yml`

- [ ] **Step 1: Create `ansible.cfg`**

```ini
[defaults]
inventory = inventory/
remote_user = cloud-user
host_key_checking = False
collections_paths = ~/.ansible/collections:/usr/share/ansible/collections

[inventory]
enable_plugins = openstack.cloud.openstack, ini, host_list

[privilege_escalation]
become = True
become_method = sudo
```

- [ ] **Step 2: Create `requirements.yml`**

```yaml
---
collections:
  - name: openstack.cloud
  - name: ansible.utils
  - name: ansible.posix
```

- [ ] **Step 3: Create `inventory/openstack.yml`**

```yaml
plugin: openstack.cloud.openstack

only_clouds:
  - "{{ cloud_name }}"

expand_hostvars: true
fail_on_errors: true
legacy_groups: false
strict: false

keyed_groups:
  - key: openstack.metadata.role
    prefix: ove_demo
    separator: "_"
```

- [ ] **Step 4: Create `inventory/group_vars/all.yml`**

This is the master configuration file with all configurable defaults.

```yaml
---
# OpenStack connection
cloud_name: ""  # Must be set by operator — matches a cloud in clouds.yaml

# External/provider network
external_network: "ext-net"

# Project
project_name: "ove-demo-{{ lookup('password', '/dev/null chars=ascii_lowercase,digits length=5') }}"
project_domain: "Default"

# Sushy service user
sushy_username: "sushy"
sushy_password: "{{ lookup('password', '/dev/null chars=ascii_letters,digits length=24') }}"

# SSH key
ssh_key_name: ""  # Must be set by operator

# OpenStack auth URL (needed for sushy-emulator clouds.yaml)
os_auth_url: ""  # Must be set by operator (e.g., https://identity.example.com:5000/v3)

# Bastion VM
bastion_flavor: "g1.large"
bastion_image: "rhel-9.5"
bastion_disk_gb: 250
bastion_mgmt_ip: "10.10.0.1"

# OVE node VMs
ove_node_flavor: "g1.4xlarge"
ove_node_count: 4
ove_node_name_prefix: "ove-node"
ove_node_disk_gb: 250

# OVE cluster DNS
cluster_name: "ove"
base_domain: "example.com"
api_vip: "10.10.0.100"
ingress_vip: "10.10.0.101"

# Sushy emulator
sushy_blank_image: "sushy-tools-blank-image"
sushy_port: 8000

# Networks
bastion_network_cidr: "10.0.0.0/24"
trunk_native_cidr: "10.99.0.0/24"
mgmt_network_cidr: "10.10.0.0/24"
storage_network_cidr: "10.20.0.0/24"
workload1_network_cidr: "192.168.10.0/24"
workload2_network_cidr: "192.168.20.0/24"
workload3_network_cidr: "192.168.30.0/24"

# VLAN IDs for trunk sub-ports
mgmt_vlan_id: 10
storage_vlan_id: 20
workload1_vlan_id: 30
workload2_vlan_id: 40
workload3_vlan_id: 50
```

- [ ] **Step 5: Initialize git repo and commit**

```bash
cd /home/aaustin/cc-workspaces/ove-appliance-demo
git init
git add ansible.cfg requirements.yml inventory/
git commit -m "feat: project scaffolding with ansible config, requirements, and inventory"
```

---

### Task 2: openstack_project Role

**Files:**
- Create: `roles/openstack_project/defaults/main.yml`
- Create: `roles/openstack_project/tasks/main.yml`

- [ ] **Step 1: Create role defaults**

```yaml
# roles/openstack_project/defaults/main.yml
---
# Defaults inherited from group_vars/all.yml:
#   project_name, project_domain, sushy_username, sushy_password, cloud_name
```

- [ ] **Step 2: Create role tasks**

```yaml
# roles/openstack_project/tasks/main.yml
---
- name: Create demo project
  openstack.cloud.project:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}"
    domain_id: "{{ project_domain }}"
    state: present
  register: demo_project

- name: Create sushy service user
  openstack.cloud.identity_user:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-sushy"
    password: "{{ sushy_password }}"
    domain: "{{ project_domain }}"
    state: present
  register: sushy_user

- name: Assign member role to sushy user on demo project
  openstack.cloud.role_assignment:
    cloud: "{{ cloud_name }}"
    user: "{{ project_name }}-sushy"
    project: "{{ project_name }}"
    role: "member"
    state: present

- name: Create application credential for sushy user
  openstack.cloud.application_credential:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-sushy-credential"
    user: "{{ project_name }}-sushy"
    state: present
  register: sushy_app_credential

- name: Store application credential details
  ansible.builtin.set_fact:
    sushy_app_credential_id: "{{ sushy_app_credential.application_credential.id }}"
    sushy_app_credential_secret: "{{ sushy_app_credential.application_credential.secret }}"
    demo_project_name: "{{ project_name }}"
    cacheable: true
```

- [ ] **Step 3: Commit**

```bash
git add roles/openstack_project/
git commit -m "feat: add openstack_project role — creates project, sushy user, and app credential"
```

---

### Task 3: openstack_networking Role

**Files:**
- Create: `roles/openstack_networking/defaults/main.yml`
- Create: `roles/openstack_networking/tasks/main.yml`

- [ ] **Step 1: Create role defaults**

```yaml
# roles/openstack_networking/defaults/main.yml
---
# Network definitions — each entry drives network + subnet creation
demo_networks:
  - name: "{{ project_name }}-bastion"
    cidr: "{{ bastion_network_cidr }}"
    enable_dhcp: true
    port_security_enabled: true
  - name: "{{ project_name }}-trunk-native"
    cidr: "{{ trunk_native_cidr }}"
    enable_dhcp: false
    port_security_enabled: false
  - name: "{{ project_name }}-mgmt"
    cidr: "{{ mgmt_network_cidr }}"
    enable_dhcp: false
    port_security_enabled: false
  - name: "{{ project_name }}-storage"
    cidr: "{{ storage_network_cidr }}"
    enable_dhcp: false
    port_security_enabled: false
  - name: "{{ project_name }}-workload1"
    cidr: "{{ workload1_network_cidr }}"
    enable_dhcp: false
    port_security_enabled: false
  - name: "{{ project_name }}-workload2"
    cidr: "{{ workload2_network_cidr }}"
    enable_dhcp: false
    port_security_enabled: false
  - name: "{{ project_name }}-workload3"
    cidr: "{{ workload3_network_cidr }}"
    enable_dhcp: false
    port_security_enabled: false
```

- [ ] **Step 2: Create role tasks**

```yaml
# roles/openstack_networking/tasks/main.yml
---
- name: Create demo networks
  openstack.cloud.network:
    cloud: "{{ cloud_name }}"
    name: "{{ item.name }}"
    port_security_enabled: "{{ item.port_security_enabled }}"
    project: "{{ project_name }}"
    state: present
  loop: "{{ demo_networks }}"

- name: Create demo subnets
  openstack.cloud.subnet:
    cloud: "{{ cloud_name }}"
    name: "{{ item.name }}-subnet"
    network_name: "{{ item.name }}"
    cidr: "{{ item.cidr }}"
    enable_dhcp: "{{ item.enable_dhcp }}"
    project: "{{ project_name }}"
    state: present
  loop: "{{ demo_networks }}"

- name: Create router
  openstack.cloud.router:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-router"
    network: "{{ external_network }}"
    project: "{{ project_name }}"
    interfaces:
      - "{{ project_name }}-bastion-subnet"
    state: present
```

- [ ] **Step 3: Commit**

```bash
git add roles/openstack_networking/
git commit -m "feat: add openstack_networking role — creates 7 networks, subnets, and router"
```

---

### Task 4: bastion_vm Role

**Files:**
- Create: `roles/bastion_vm/defaults/main.yml`
- Create: `roles/bastion_vm/tasks/main.yml`

- [ ] **Step 1: Create role defaults**

```yaml
# roles/bastion_vm/defaults/main.yml
---
# Defaults inherited from group_vars/all.yml:
#   project_name, bastion_flavor, bastion_image, bastion_disk_gb,
#   bastion_mgmt_ip, external_network, ssh_key_name, cloud_name
```

- [ ] **Step 2: Create role tasks**

```yaml
# roles/bastion_vm/tasks/main.yml
---
- name: Create bastion port on bastion network
  openstack.cloud.port:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-bastion-port"
    network: "{{ project_name }}-bastion"
    project: "{{ project_name }}"
    state: present
  register: bastion_port

- name: Create bastion port on management network
  openstack.cloud.port:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-bastion-mgmt-port"
    network: "{{ project_name }}-mgmt"
    project: "{{ project_name }}"
    fixed_ips:
      - ip_address: "{{ bastion_mgmt_ip }}"
    port_security_enabled: false
    state: present
  register: bastion_mgmt_port

- name: Create bastion boot volume
  openstack.cloud.volume:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-bastion-volume"
    image: "{{ bastion_image }}"
    size: "{{ bastion_disk_gb }}"
    state: present
  register: bastion_volume

- name: Create bastion VM
  openstack.cloud.server:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-bastion"
    flavor: "{{ bastion_flavor }}"
    boot_volume: "{{ bastion_volume.volume.id }}"
    key_name: "{{ ssh_key_name }}"
    nics:
      - port-id: "{{ bastion_port.port.id }}"
      - port-id: "{{ bastion_mgmt_port.port.id }}"
    meta:
      role: bastion
    state: present
  register: bastion_server

- name: Assign floating IP to bastion
  openstack.cloud.floating_ip:
    cloud: "{{ cloud_name }}"
    server: "{{ project_name }}-bastion"
    network: "{{ external_network }}"
    state: present
  register: bastion_fip

- name: Store bastion FIP for later use
  ansible.builtin.set_fact:
    bastion_floating_ip: "{{ bastion_fip.floating_ip.floating_ip_address }}"
    cacheable: true

- name: Wait for bastion SSH to become available
  ansible.builtin.wait_for:
    host: "{{ bastion_floating_ip }}"
    port: 22
    delay: 10
    timeout: 300
```

- [ ] **Step 3: Commit**

```bash
git add roles/bastion_vm/
git commit -m "feat: add bastion_vm role — creates ports, volume, server, and FIP"
```

---

### Task 5: ove_nodes Role

**Files:**
- Create: `roles/ove_nodes/defaults/main.yml`
- Create: `roles/ove_nodes/tasks/main.yml`
- Create: `roles/ove_nodes/tasks/create_trunk.yml`

- [ ] **Step 1: Create role defaults**

```yaml
# roles/ove_nodes/defaults/main.yml
---
# Trunk sub-port definitions — maps VLAN IDs to networks
trunk_subports:
  - vlan_id: "{{ mgmt_vlan_id }}"
    network: "{{ project_name }}-mgmt"
  - vlan_id: "{{ storage_vlan_id }}"
    network: "{{ project_name }}-storage"
  - vlan_id: "{{ workload1_vlan_id }}"
    network: "{{ project_name }}-workload1"
  - vlan_id: "{{ workload2_vlan_id }}"
    network: "{{ project_name }}-workload2"
  - vlan_id: "{{ workload3_vlan_id }}"
    network: "{{ project_name }}-workload3"
```

- [ ] **Step 2: Create trunk creation task file**

This is included per-node per-trunk-index. It creates the parent port, sub-ports, and assembles the trunk using the OpenStack CLI (since the `openstack.cloud` collection does not have a trunk module).

```yaml
# roles/ove_nodes/tasks/create_trunk.yml
# Variables expected: node_idx, trunk_idx, project_name, trunk_subports
---
- name: "Create parent port for {{ ove_node_name_prefix }}-{{ node_idx }} trunk {{ trunk_idx }}"
  openstack.cloud.port:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ node_idx }}-trunk{{ trunk_idx }}-parent"
    network: "{{ project_name }}-trunk-native"
    project: "{{ project_name }}"
    port_security_enabled: false
    state: present
  register: parent_port

- name: "Create sub-ports for {{ ove_node_name_prefix }}-{{ node_idx }} trunk {{ trunk_idx }}"
  openstack.cloud.port:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ node_idx }}-trunk{{ trunk_idx }}-vlan{{ item.vlan_id }}"
    network: "{{ item.network }}"
    project: "{{ project_name }}"
    port_security_enabled: false
    state: present
  loop: "{{ trunk_subports }}"
  register: sub_ports

- name: "Build sub-port argument list for {{ ove_node_name_prefix }}-{{ node_idx }} trunk {{ trunk_idx }}"
  ansible.builtin.set_fact:
    subport_args: >-
      {% for result in sub_ports.results %}
      --subport port={{ result.port.id }},segmentation-type=vlan,segmentation-id={{ result.item.vlan_id }}{{ ' ' }}
      {% endfor %}

- name: "Create trunk for {{ ove_node_name_prefix }}-{{ node_idx }} trunk {{ trunk_idx }}"
  ansible.builtin.command:
    cmd: >-
      openstack --os-cloud {{ cloud_name }}
      network trunk create
      --parent-port {{ parent_port.port.id }}
      {{ subport_args }}
      {{ project_name }}-{{ ove_node_name_prefix }}-{{ node_idx }}-trunk{{ trunk_idx }}
  register: trunk_result
  changed_when: trunk_result.rc == 0

- name: "Store parent port ID for {{ ove_node_name_prefix }}-{{ node_idx }} trunk {{ trunk_idx }}"
  ansible.builtin.set_fact:
    "trunk{{ trunk_idx }}_port_id_node{{ node_idx }}": "{{ parent_port.port.id }}"
```

- [ ] **Step 3: Create main tasks file**

```yaml
# roles/ove_nodes/tasks/main.yml
---
- name: Create OVE node trunks
  ansible.builtin.include_tasks: create_trunk.yml
  loop: "{{ range(0, ove_node_count | int) | product([0, 1]) | list }}"
  loop_control:
    loop_var: node_trunk_pair
  vars:
    node_idx: "{{ node_trunk_pair[0] }}"
    trunk_idx: "{{ node_trunk_pair[1] }}"

- name: Create OVE node boot volumes
  openstack.cloud.volume:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item }}-volume"
    image: "{{ sushy_blank_image }}"
    size: "{{ ove_node_disk_gb }}"
    state: present
  loop: "{{ range(0, ove_node_count | int) | list }}"

- name: Create OVE node VMs
  openstack.cloud.server:
    cloud: "{{ cloud_name }}"
    name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item }}"
    flavor: "{{ ove_node_flavor }}"
    boot_volume: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item }}-volume"
    nics:
      - port-id: "{{ hostvars[inventory_hostname]['trunk0_port_id_node' + item | string] }}"
      - port-id: "{{ hostvars[inventory_hostname]['trunk1_port_id_node' + item | string] }}"
    meta:
      role: ove_node
    state: present
  loop: "{{ range(0, ove_node_count | int) | list }}"
```

- [ ] **Step 4: Commit**

```bash
git add roles/ove_nodes/
git commit -m "feat: add ove_nodes role — creates trunk ports, sub-ports, volumes, and VMs"
```

---

### Task 6: bastion_configure Role — GNOME Desktop & Firewall

**Files:**
- Create: `roles/bastion_configure/defaults/main.yml`
- Create: `roles/bastion_configure/tasks/main.yml`
- Create: `roles/bastion_configure/tasks/desktop.yml`
- Create: `roles/bastion_configure/tasks/firewall.yml`

- [ ] **Step 1: Create role defaults**

```yaml
# roles/bastion_configure/defaults/main.yml
---
# Defaults inherited from group_vars/all.yml:
#   cluster_name, base_domain, api_vip, ingress_vip,
#   bastion_mgmt_ip, mgmt_network_cidr,
#   sushy_port, sushy_username, sushy_password,
#   sushy_blank_image, sushy_app_credential_id, sushy_app_credential_secret

# DNS
dns_forwarders:
  - 8.8.8.8
  - 8.8.4.4

# NTP
ntp_upstream_servers:
  - 0.rhel.pool.ntp.org
  - 1.rhel.pool.ntp.org
  - 2.rhel.pool.ntp.org
```

- [ ] **Step 2: Create main tasks file (dispatcher)**

```yaml
# roles/bastion_configure/tasks/main.yml
---
- name: Configure GNOME desktop
  ansible.builtin.include_tasks: desktop.yml

- name: Configure firewall (no IP forwarding)
  ansible.builtin.include_tasks: firewall.yml

- name: Configure BIND DNS
  ansible.builtin.include_tasks: dns.yml

- name: Configure Chrony NTP server
  ansible.builtin.include_tasks: ntp.yml

- name: Configure sushy-emulator
  ansible.builtin.include_tasks: sushy.yml
```

- [ ] **Step 3: Create desktop tasks**

```yaml
# roles/bastion_configure/tasks/desktop.yml
---
- name: Install GNOME desktop environment
  ansible.builtin.dnf:
    name: "@workstation"
    state: present

- name: Set default target to graphical
  ansible.builtin.systemd:
    name: graphical.target
    enabled: true

- name: Set graphical as default systemd target
  ansible.builtin.command:
    cmd: systemctl set-default graphical.target
  changed_when: true
```

- [ ] **Step 4: Create firewall tasks**

This ensures the bastion does NOT forward traffic between its management NIC and external-facing NIC, enforcing the disconnected environment.

```yaml
# roles/bastion_configure/tasks/firewall.yml
---
- name: Disable IP forwarding
  ansible.posix.sysctl:
    name: net.ipv4.ip_forward
    value: "0"
    sysctl_set: true
    reload: true
    state: present

- name: Ensure firewalld is installed and running
  ansible.builtin.dnf:
    name: firewalld
    state: present

- name: Start and enable firewalld
  ansible.builtin.systemd:
    name: firewalld
    state: started
    enabled: true

- name: Allow DNS on management interface
  ansible.posix.firewalld:
    service: dns
    zone: trusted
    permanent: true
    immediate: true
    state: enabled

- name: Allow NTP on management interface
  ansible.posix.firewalld:
    service: ntp
    zone: trusted
    permanent: true
    immediate: true
    state: enabled

- name: Allow sushy-emulator port on management interface
  ansible.posix.firewalld:
    port: "{{ sushy_port }}/tcp"
    zone: trusted
    permanent: true
    immediate: true
    state: enabled
```

- [ ] **Step 5: Commit**

```bash
git add roles/bastion_configure/defaults/ roles/bastion_configure/tasks/main.yml roles/bastion_configure/tasks/desktop.yml roles/bastion_configure/tasks/firewall.yml
git commit -m "feat: add bastion_configure role — GNOME desktop and firewall"
```

---

### Task 7: bastion_configure — BIND DNS

**Files:**
- Create: `roles/bastion_configure/tasks/dns.yml`
- Create: `roles/bastion_configure/templates/named.conf.j2`
- Create: `roles/bastion_configure/templates/ove-zone.db.j2`
- Create: `roles/bastion_configure/templates/ove-reverse.db.j2`

- [ ] **Step 1: Create DNS tasks**

```yaml
# roles/bastion_configure/tasks/dns.yml
---
- name: Install BIND
  ansible.builtin.dnf:
    name:
      - bind
      - bind-utils
    state: present

- name: Deploy named.conf
  ansible.builtin.template:
    src: named.conf.j2
    dest: /etc/named.conf
    owner: root
    group: named
    mode: "0640"
  notify: restart named

- name: Deploy forward zone file
  ansible.builtin.template:
    src: ove-zone.db.j2
    dest: "/var/named/{{ base_domain }}.db"
    owner: root
    group: named
    mode: "0640"
  notify: restart named

- name: Deploy reverse zone file
  ansible.builtin.template:
    src: ove-reverse.db.j2
    dest: "/var/named/{{ mgmt_network_cidr | ansible.utils.ipaddr('revdns') | regex_replace('^[0-9]+\\.', '') | regex_replace('\\.$', '') }}.db"
    owner: root
    group: named
    mode: "0640"
  notify: restart named

- name: Start and enable named
  ansible.builtin.systemd:
    name: named
    state: started
    enabled: true
```

- [ ] **Step 2: Create `named.conf.j2` template**

```jinja2
// /etc/named.conf — managed by Ansible
options {
    listen-on port 53 { 127.0.0.1; {{ bastion_mgmt_ip }}; };
    listen-on-v6 port 53 { none; };
    directory       "/var/named";
    dump-file       "/var/named/data/cache_dump.db";
    statistics-file "/var/named/data/named_stats.txt";
    allow-query     { localhost; {{ mgmt_network_cidr }}; };
    recursion yes;
    forwarders {
{% for fwd in dns_forwarders %}
        {{ fwd }};
{% endfor %}
    };
    dnssec-validation no;
};

zone "{{ base_domain }}" IN {
    type master;
    file "{{ base_domain }}.db";
    allow-update { none; };
};

zone "{{ mgmt_network_cidr | ansible.utils.ipaddr('revdns') | regex_replace('^[0-9]+\\.', '') | regex_replace('\\.$', '') }}" IN {
    type master;
    file "{{ mgmt_network_cidr | ansible.utils.ipaddr('revdns') | regex_replace('^[0-9]+\\.', '') | regex_replace('\\.$', '') }}.db";
    allow-update { none; };
};
```

- [ ] **Step 3: Create forward zone template**

```jinja2
; {{ base_domain }} zone — managed by Ansible
$TTL 86400
@   IN  SOA bastion.{{ base_domain }}. admin.{{ base_domain }}. (
        2024010101  ; serial
        3600        ; refresh
        1800        ; retry
        604800      ; expire
        86400       ; minimum TTL
)
@           IN  NS  bastion.{{ base_domain }}.
bastion     IN  A   {{ bastion_mgmt_ip }}

; OVE cluster endpoints
api.{{ cluster_name }}          IN  A   {{ api_vip }}
*.apps.{{ cluster_name }}       IN  A   {{ ingress_vip }}
```

- [ ] **Step 4: Create reverse zone template**

```jinja2
; Reverse zone for {{ mgmt_network_cidr }} — managed by Ansible
$TTL 86400
@   IN  SOA bastion.{{ base_domain }}. admin.{{ base_domain }}. (
        2024010101  ; serial
        3600        ; refresh
        1800        ; retry
        604800      ; expire
        86400       ; minimum TTL
)
@   IN  NS  bastion.{{ base_domain }}.

{{ bastion_mgmt_ip | ansible.utils.ipaddr('revdns') | regex_replace('\\..*$', '') }}  IN  PTR  bastion.{{ base_domain }}.
{{ api_vip | ansible.utils.ipaddr('revdns') | regex_replace('\\..*$', '') }}           IN  PTR  api.{{ cluster_name }}.{{ base_domain }}.
```

- [ ] **Step 5: Create handlers file for named restart**

```yaml
# roles/bastion_configure/handlers/main.yml
---
- name: restart named
  ansible.builtin.systemd:
    name: named
    state: restarted
```

- [ ] **Step 6: Commit**

```bash
git add roles/bastion_configure/tasks/dns.yml roles/bastion_configure/templates/named.conf.j2 roles/bastion_configure/templates/ove-zone.db.j2 roles/bastion_configure/templates/ove-reverse.db.j2 roles/bastion_configure/handlers/
git commit -m "feat: add BIND DNS configuration with OVE cluster zone"
```

---

### Task 8: bastion_configure — Chrony NTP Server

**Files:**
- Create: `roles/bastion_configure/tasks/ntp.yml`
- Create: `roles/bastion_configure/templates/chrony.conf.j2`

- [ ] **Step 1: Create NTP tasks**

```yaml
# roles/bastion_configure/tasks/ntp.yml
---
- name: Install chrony
  ansible.builtin.dnf:
    name: chrony
    state: present

- name: Deploy chrony.conf
  ansible.builtin.template:
    src: chrony.conf.j2
    dest: /etc/chrony.conf
    owner: root
    group: root
    mode: "0644"
  notify: restart chronyd

- name: Start and enable chronyd
  ansible.builtin.systemd:
    name: chronyd
    state: started
    enabled: true
```

- [ ] **Step 2: Create chrony.conf template**

```jinja2
# /etc/chrony.conf — managed by Ansible
{% for server in ntp_upstream_servers %}
server {{ server }} iburst
{% endfor %}

# Serve time to the OCP management network
allow {{ mgmt_network_cidr }}

driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
```

- [ ] **Step 3: Add chronyd handler**

Append to the existing handlers file:

```yaml
# Append to roles/bastion_configure/handlers/main.yml
- name: restart chronyd
  ansible.builtin.systemd:
    name: chronyd
    state: restarted
```

- [ ] **Step 4: Commit**

```bash
git add roles/bastion_configure/tasks/ntp.yml roles/bastion_configure/templates/chrony.conf.j2 roles/bastion_configure/handlers/main.yml
git commit -m "feat: add Chrony NTP server configuration for management network"
```

---

### Task 9: bastion_configure — sushy-emulator

**Files:**
- Create: `roles/bastion_configure/tasks/sushy.yml`
- Create: `roles/bastion_configure/templates/sushy-emulators.conf.j2`
- Create: `roles/bastion_configure/templates/sushy-emulators.service.j2`
- Create: `roles/bastion_configure/templates/sushy-emulators.htpasswd.j2`
- Create: `roles/bastion_configure/templates/clouds.yaml.j2`

- [ ] **Step 1: Create sushy tasks**

```yaml
# roles/bastion_configure/tasks/sushy.yml
---
- name: Install sushy-tools prerequisites
  ansible.builtin.dnf:
    name:
      - python3-pip
      - git
    state: present

- name: Install sushy-tools and dependencies
  ansible.builtin.pip:
    name:
      - git+https://github.com/marbindrakon/sushy-tools.git
      - openstacksdk
      - gunicorn
    executable: pip3

- name: Create OpenStack config directory
  ansible.builtin.file:
    path: /root/.config/openstack
    state: directory
    mode: "0700"

- name: Deploy clouds.yaml for sushy-emulator
  ansible.builtin.template:
    src: clouds.yaml.j2
    dest: /root/.config/openstack/clouds.yaml
    mode: "0600"

- name: Generate htpasswd hash for sushy user
  ansible.builtin.command:
    cmd: "python3 -c \"import hashlib; print(hashlib.md5(b'{{ sushy_username }}:{{ sushy_password }}'.decode() if False else '{{ sushy_password }}'.encode()).hexdigest())\""
  register: sushy_hash_result
  changed_when: false
  no_log: true

- name: Create htpasswd file using httpd-tools
  ansible.builtin.dnf:
    name: httpd-tools
    state: present

- name: Generate htpasswd file
  ansible.builtin.command:
    cmd: "htpasswd -cbB /root/sushy-emulators.htpasswd {{ sushy_username }} {{ sushy_password }}"
  changed_when: true
  no_log: true

- name: Set htpasswd file permissions
  ansible.builtin.file:
    path: /root/sushy-emulators.htpasswd
    mode: "0600"

- name: Deploy sushy-emulators config
  ansible.builtin.template:
    src: sushy-emulators.conf.j2
    dest: /root/sushy-emulators.conf
    mode: "0644"
  notify: restart sushy-emulators

- name: Deploy sushy-emulators systemd unit
  ansible.builtin.template:
    src: sushy-emulators.service.j2
    dest: /etc/systemd/system/sushy-emulators.service
    mode: "0644"
  notify: restart sushy-emulators

- name: Reload systemd and enable sushy-emulators
  ansible.builtin.systemd:
    name: sushy-emulators
    daemon_reload: true
    enabled: true
    state: started
```

- [ ] **Step 2: Create `clouds.yaml.j2` template**

```jinja2
clouds:
  sushy-cloud:
    auth_type: v3applicationcredential
    auth:
      auth_url: "{{ os_auth_url }}"
      application_credential_id: "{{ sushy_app_credential_id }}"
      application_credential_secret: "{{ sushy_app_credential_secret }}"
    region_name: "{{ os_region | default('RegionOne') }}"
    cacert: /etc/pki/tls/certs/ca-bundle.crt
```

- [ ] **Step 3: Create `sushy-emulators.conf.j2` template**

```jinja2
SUSHY_EMULATOR_LISTEN_IP = u'0.0.0.0'
SUSHY_EMULATOR_LISTEN_PORT = {{ sushy_port }}
SUSHY_EMULATOR_SSL_CERT = None
SUSHY_EMULATOR_SSL_KEY = None
SUSHY_EMULATOR_AUTH_FILE = "/root/sushy-emulators.htpasswd"
SUSHY_EMULATOR_OS_CLOUD = "sushy-cloud"
SUSHY_EMULATOR_OS_VMEDIA_IMAGE_FILE_UPLOAD = True
SUSHY_EMULATOR_OS_VMEDIA_BLANK_IMAGE = '{{ sushy_blank_image }}'
SUSHY_EMULATOR_OS_VMEDIA_DELAY_EJECT = False
SUSHY_EMULATOR_FEATURE_SET = 'vmedia'
```

- [ ] **Step 4: Create `sushy-emulators.service.j2` template**

```jinja2
[Unit]
Description=Sushy BMC Emulator
After=syslog.target

[Service]
Type=simple
Environment="SUSHY_EMULATOR_CONFIG=/root/sushy-emulators.conf"
ExecStart=/usr/local/bin/gunicorn -b 0.0.0.0 -w 8 --max-requests 100 --log-level debug sushy_tools.emulator.main:app
LimitNOFILE=65536
StandardOutput=syslog
StandardError=syslog

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Add sushy-emulators handler**

Append to the existing handlers file:

```yaml
# Append to roles/bastion_configure/handlers/main.yml
- name: restart sushy-emulators
  ansible.builtin.systemd:
    name: sushy-emulators
    daemon_reload: true
    state: restarted
```

- [ ] **Step 6: Commit**

```bash
git add roles/bastion_configure/tasks/sushy.yml roles/bastion_configure/templates/clouds.yaml.j2 roles/bastion_configure/templates/sushy-emulators.conf.j2 roles/bastion_configure/templates/sushy-emulators.service.j2 roles/bastion_configure/handlers/main.yml
git commit -m "feat: add sushy-emulator configuration with Application Credential auth"
```

---

### Task 10: site.yml Orchestrator

**Files:**
- Create: `site.yml`

- [ ] **Step 1: Create site.yml**

```yaml
# site.yml — OVE Appliance Demo Environment Orchestrator
---
# Play 1: Create OpenStack infrastructure (project, networks, VMs)
- name: Create OVE demo infrastructure
  hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - openstack_project
    - openstack_networking
    - bastion_vm
    - ove_nodes

# Play 2: Configure bastion host services
- name: Configure bastion host
  hosts: ove_demo_bastion
  gather_facts: true
  vars:
    os_auth_url: "{{ lookup('env', 'OS_AUTH_URL') | default(hostvars['localhost']['os_auth_url'], true) }}"
    os_region: "{{ lookup('env', 'OS_REGION_NAME') | default(hostvars['localhost']['os_region'] | default('RegionOne'), true) }}"
    sushy_app_credential_id: "{{ hostvars['localhost']['sushy_app_credential_id'] }}"
    sushy_app_credential_secret: "{{ hostvars['localhost']['sushy_app_credential_secret'] }}"
  roles:
    - bastion_configure
```

- [ ] **Step 2: Commit**

```bash
git add site.yml
git commit -m "feat: add site.yml orchestrator — infra creation then bastion configuration"
```

---

### Task 11: teardown.yml

**Files:**
- Create: `teardown.yml`

- [ ] **Step 1: Create teardown.yml**

```yaml
# teardown.yml — Destroy all OVE demo resources
---
- name: Tear down OVE demo environment
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    # --- Delete OVE node VMs and volumes ---
    - name: Delete OVE node VMs
      openstack.cloud.server:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item }}"
        state: absent
      loop: "{{ range(0, ove_node_count | int) | list }}"

    - name: Delete OVE node boot volumes
      openstack.cloud.volume:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item }}-volume"
        state: absent
      loop: "{{ range(0, ove_node_count | int) | list }}"

    # --- Delete OVE node trunk ports ---
    - name: Delete OVE node trunks
      ansible.builtin.command:
        cmd: >-
          openstack --os-cloud {{ cloud_name }}
          network trunk delete
          {{ project_name }}-{{ ove_node_name_prefix }}-{{ item[0] }}-trunk{{ item[1] }}
      loop: "{{ range(0, ove_node_count | int) | product([0, 1]) | list }}"
      failed_when: false
      changed_when: true

    - name: Delete OVE node sub-ports
      openstack.cloud.port:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item[0] }}-trunk{{ item[1] }}-vlan{{ item[2] }}"
        state: absent
      loop: >-
        {{ range(0, ove_node_count | int)
           | product([0, 1])
           | product([mgmt_vlan_id, storage_vlan_id, workload1_vlan_id, workload2_vlan_id, workload3_vlan_id])
           | map('flatten')
           | list }}

    - name: Delete OVE node parent ports
      openstack.cloud.port:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-{{ ove_node_name_prefix }}-{{ item[0] }}-trunk{{ item[1] }}-parent"
        state: absent
      loop: "{{ range(0, ove_node_count | int) | product([0, 1]) | list }}"

    # --- Delete bastion VM ---
    - name: Release bastion floating IP
      openstack.cloud.floating_ip:
        cloud: "{{ cloud_name }}"
        server: "{{ project_name }}-bastion"
        network: "{{ external_network }}"
        state: absent
      failed_when: false

    - name: Delete bastion VM
      openstack.cloud.server:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-bastion"
        state: absent

    - name: Delete bastion boot volume
      openstack.cloud.volume:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-bastion-volume"
        state: absent

    - name: Delete bastion ports
      openstack.cloud.port:
        cloud: "{{ cloud_name }}"
        name: "{{ item }}"
        state: absent
      loop:
        - "{{ project_name }}-bastion-port"
        - "{{ project_name }}-bastion-mgmt-port"

    # --- Delete router and networks ---
    - name: Delete router
      openstack.cloud.router:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-router"
        state: absent

    - name: Delete subnets
      openstack.cloud.subnet:
        cloud: "{{ cloud_name }}"
        name: "{{ item.name }}-subnet"
        state: absent
      loop: "{{ demo_networks }}"

    - name: Delete networks
      openstack.cloud.network:
        cloud: "{{ cloud_name }}"
        name: "{{ item.name }}"
        state: absent
      loop: "{{ demo_networks }}"

    # --- Delete credentials and project ---
    - name: Delete application credential
      openstack.cloud.application_credential:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-sushy-credential"
        user: "{{ project_name }}-sushy"
        state: absent
      failed_when: false

    - name: Delete sushy service user
      openstack.cloud.identity_user:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}-sushy"
        domain: "{{ project_domain }}"
        state: absent
      failed_when: false

    - name: Delete demo project
      openstack.cloud.project:
        cloud: "{{ cloud_name }}"
        name: "{{ project_name }}"
        domain_id: "{{ project_domain }}"
        state: absent
```

- [ ] **Step 2: Commit**

```bash
git add teardown.yml
git commit -m "feat: add teardown.yml — destroys all demo resources in reverse order"
```

---

### Task 12: Verification and Documentation

**Files:**
- Create: `README.md` (minimal usage instructions)

- [ ] **Step 1: Run ansible-lint to validate syntax**

```bash
cd /home/aaustin/cc-workspaces/ove-appliance-demo
ansible-lint site.yml teardown.yml
```

Fix any issues reported.

- [ ] **Step 2: Verify all role structures are complete**

```bash
find roles/ -name "main.yml" | sort
```

Expected output:
```
roles/bastion_configure/defaults/main.yml
roles/bastion_configure/handlers/main.yml
roles/bastion_configure/tasks/main.yml
roles/bastion_vm/defaults/main.yml
roles/bastion_vm/tasks/main.yml
roles/openstack_networking/defaults/main.yml
roles/openstack_networking/tasks/main.yml
roles/openstack_project/defaults/main.yml
roles/openstack_project/tasks/main.yml
roles/ove_nodes/defaults/main.yml
roles/ove_nodes/tasks/main.yml
```

- [ ] **Step 3: Create minimal README**

```markdown
# OVE Appliance Demo Environment

Ansible playbooks to provision a disconnected OVE demo environment on OpenStack.

## Prerequisites

- Ansible 2.14+
- `openstack.cloud` and `ansible.utils` collections
- OpenStack CLI (`python-openstackclient`)
- A `clouds.yaml` with credentials that can create projects and users

## Setup

```bash
ansible-galaxy collection install -r requirements.yml
```

## Usage

1. Copy and edit the variables in `inventory/group_vars/all.yml` — at minimum set `cloud_name` and `ssh_key_name`.

2. Deploy the environment:
```bash
ansible-playbook site.yml
```

3. Tear down the environment:
```bash
ansible-playbook teardown.yml -e project_name=<your-project-name>
```

Note: Since `project_name` includes a random suffix, you must pass the actual project name used during creation when running teardown.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup and usage instructions"
```
