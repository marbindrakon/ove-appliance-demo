# TODO: Support pre-generated appliance images

## Goal

Allow the user to provide a pre-built `appliance.raw` file on the controller instead of always building it on the bastion. If a file path is provided, upload directly from the controller to Glance, skipping the bastion build entirely.

## New variable

```yaml
# Path to a pre-built appliance.raw on the Ansible controller (optional).
# If set, the image is uploaded directly from the controller to Glance
# and the bastion-based build is skipped entirely.
appliance_image_path: ""
```

## Changes

### `site.yml`

Play 3 (appliance build on bastion) gets a `when` that also checks `appliance_image_path` is not set:

```yaml
- name: Build appliance image on bastion
  hosts: ove_demo_bastion
  ...
  roles:
    - role: appliance_image
      when:
        - install_method | default('ove') == 'appliance'
        - appliance_image_path | default('') | length == 0
```

Play 4 (localhost, before ove_nodes) gets a new pre_tasks block or role to handle the controller-side upload:

```yaml
- name: Create OVE nodes
  hosts: localhost
  ...
  pre_tasks:
    - name: Upload pre-built appliance image to Glance
      when:
        - install_method | default('ove') == 'appliance'
        - appliance_image_path | default('') | length > 0
      block:
        - name: Check if appliance image already exists in Glance
          openstack.cloud.image_info:
            cloud: "{{ demo_cloud_name }}"
            image: "{{ appliance_image_name }}"
          register: appliance_image_info

        - name: Upload appliance image from controller
          openstack.cloud.image:
            cloud: "{{ demo_cloud_name }}"
            name: "{{ appliance_image_name }}"
            filename: "{{ appliance_image_path }}"
            disk_format: raw
            container_format: bare
            state: present
          when: appliance_image_info.images | length == 0
  roles:
    - ove_nodes
```

### `inventory/group_vars/all.yml.sample`

Add `appliance_image_path` to the appliance mode section.

### `teardown.yml`

No changes needed — already deletes by `appliance_image_name` regardless of how it was uploaded.
