#!/bin/bash
KLIPPER_PATH="${HOME}/klipper"
SYSTEMDDIR="/etc/systemd/system"

# Constants
EXTENSION_NAME="tool_offset"

# Force script to exit if an error occurs
set -e


# Find SRCDIR from the pathname of this script
SRCDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/ && pwd )"

KLIPPER_PATH="${HOME}/klipper"
# Parse command line arguments to allow KLIPPER_PATH override
while getopts "k:" arg; do
    case $arg in
        k) KLIPPER_PATH=$OPTARG;;
    esac
done
# Verify Klipper has been installed
check_klipper()
{
    if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper.service")" ]; then
        echo "Klipper service found!"
    else
        echo "Klipper service not found, please install Klipper first"
        exit -1
    fi
}

# Verify conditions for the install to take place
check_preconditions()
{
    if [ "$EUID" -eq 0 ]; then
        echo "This script must not run as root"
        exit -1
    fi

    if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F "klipper.service")" ]; then
        echo "Klipper service found!"
    else
        echo "Klipper service not found, please install Klipper first"
        exit -1
    fi
}

# Step 2: create a symlinks to the extension files in the klippy/extras directory
link_extension()
{
    echo "Linking ${EXTENSION_NAME} to Klippy extras..."
    ln -sf ${SRCDIR}/*.py ${KLIPPER_PATH}/klippy/extras/
}

# Step 3: restarting Klipper
restart_klipper()
{
    echo "Restarting Klipper..."
    sudo systemctl restart klipper
}

# Helper functions
verify_ready()
{
    if [ "$EUID" -eq 0 ]; then
        echo "This script must not run as root"
        exit -1
    fi
}

# Installation steps:
check_preconditions
verify_ready
link_extension
restart_klipper