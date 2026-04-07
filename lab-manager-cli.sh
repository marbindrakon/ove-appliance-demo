#!/usr/bin/env bash
# lab-manager-cli.sh — Deploy, teardown, or reset one or more labs in parallel
#
# Usage:
#   ./lab-manager-cli.sh deploy   labs/openstack-appliance.yml labs/libvirt-ove.yml
#   ./lab-manager-cli.sh teardown labs/openstack-appliance.yml
#   ./lab-manager-cli.sh reset    labs/libvirt-appliance.yml
#   ./lab-manager-cli.sh deploy-all     # all .yml files in labs/
#   ./lab-manager-cli.sh teardown-all
#   ./lab-manager-cli.sh reset-all

set -euo pipefail

ACTION="${1:?Usage: $0 <deploy|teardown|reset|deploy-all|teardown-all|reset-all> [lab-files...]}"
shift

LOG_DIR="logs/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LOG_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_ROOT="${SCRIPT_DIR}/.ove-demo-cache/tui"
CALLBACK_DIR="${SCRIPT_DIR}/callback_plugins"

declare -A PLAYBOOKS=(
    [deploy]=site.yml
    [teardown]=teardown.yml
    [reset]=reset-ove-nodes.yml
)

run_lab() {
    local playbook="$1" lab_file="$2"
    local lab_name
    lab_name=$(basename "$lab_file" .yml)
    local log_file="${LOG_DIR}/${lab_name}.log"
    local state_dir="${STATE_ROOT}/${lab_name}"

    mkdir -p "$state_dir"

    echo "[$(date +%H:%M:%S)] Starting ${lab_name} → ${log_file}"
    if OVE_LAB_NAME="$lab_name" \
       OVE_STATE_DIR="$state_dir" \
       OVE_ACTION="${ACTION%-all}" \
       ANSIBLE_CALLBACK_PLUGINS="$CALLBACK_DIR" \
       ANSIBLE_CALLBACKS_ENABLED="ove_tui" \
       ansible-playbook "$playbook" -e "@${lab_file}" > "$log_file" 2>&1; then
        echo "[$(date +%H:%M:%S)] ✓ ${lab_name} succeeded"
        # Copy log to state dir for TUI access
        cp "$log_file" "$state_dir/ansible.log"
        return 0
    else
        echo "[$(date +%H:%M:%S)] ✗ ${lab_name} FAILED — see ${log_file}"
        cp "$log_file" "$state_dir/ansible.log"
        return 1
    fi
}

# Resolve action to playbook and lab files
case "$ACTION" in
    deploy|teardown|reset)
        PLAYBOOK="${PLAYBOOKS[$ACTION]}"
        LAB_FILES=("$@")
        if [[ ${#LAB_FILES[@]} -eq 0 ]]; then
            echo "Error: specify one or more lab files" >&2
            exit 1
        fi
        ;;
    deploy-all|teardown-all|reset-all)
        BASE_ACTION="${ACTION%-all}"
        PLAYBOOK="${PLAYBOOKS[$BASE_ACTION]}"
        LAB_FILES=(labs/*.yml)
        if [[ ${#LAB_FILES[@]} -eq 0 || ! -f "${LAB_FILES[0]}" ]]; then
            echo "Error: no .yml files found in labs/" >&2
            exit 1
        fi
        ;;
    *)
        echo "Error: unknown action '$ACTION'" >&2
        echo "Usage: $0 <deploy|teardown|reset|deploy-all|teardown-all|reset-all> [lab-files...]" >&2
        exit 1
        ;;
esac

echo "Action: ${ACTION} | Playbook: ${PLAYBOOK} | Labs: ${LAB_FILES[*]}"
echo "Logs:   ${LOG_DIR}/"
echo ""

# Launch all labs in parallel
PIDS=()
LABS=()
for lab_file in "${LAB_FILES[@]}"; do
    run_lab "$PLAYBOOK" "$lab_file" &
    PIDS+=($!)
    LABS+=("$(basename "$lab_file" .yml)")
done

# Wait for all and collect exit codes
FAILED=0
for i in "${!PIDS[@]}"; do
    if ! wait "${PIDS[$i]}"; then
        ((FAILED++))
    fi
done

echo ""
echo "=== Summary ==="
echo "Total: ${#LABS[@]} | Failed: ${FAILED}"
echo "Logs:  ${LOG_DIR}/"

exit "$FAILED"
