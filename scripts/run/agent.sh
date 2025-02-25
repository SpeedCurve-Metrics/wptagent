#!/bin/sh
echo tsc | sudo tee /sys/devices/system/clocksource/clocksource0/current_clocksource
export DEBIAN_FRONTEND=noninteractive

# Activate python virtual environment
. /home/ubuntu/agent_env/bin/activate

cd ~/wptagent

echo "Updating Firefox Nightly, Chrome Beta and Chrome Canary"
sudo apt -y update
sudo apt -y install firefox-trunk google-chrome-unstable google-chrome-beta
sudo apt clean

#echo "Starting dummy X11 server"
#export DISPLAY=:1
#Xorg -noreset +extension GLX +extension RANDR +extension RENDER -logfile /dev/null -config ./misc/xorg.conf :1 &

# Create ifb network adapter for traffic shaping
sudo ip link add  ifb0 type ifb

# Ensure AWS meta data service is reachable (Agent adds a route that blocks this)
sudo route delete 169.254.169.254

# Check if the wptagent branch was specified in the EC2 user data
# IMDSv2 requires a session token
aws_token=$(curl --silent -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
wpt_branch=$(curl --silent --connect-timeout 2 -H "X-aws-ec2-metadata-token: $aws_token" http://169.254.169.254/latest/user-data | sed -nE 's/.*wpt_branch=([^ ]+).*/\1/p')
[ ! -z "$wpt_branch" ] || wpt_branch='release'

for i in `seq 1 24`
do
    echo "Updating from origin/$wpt_branch"
    git fetch origin
    git reset --hard origin/$wpt_branch
    python wptagent.py -vvvv --ec2 --xvfb --throttle --exit 60 --alive /tmp/wptagent
    echo "Exited, restarting"
    sleep 1
done
sudo reboot

