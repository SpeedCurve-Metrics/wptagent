#!/bin/sh
PATH=/home/ubuntu/bin:/home/ubuntu/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin

cd ~

if [ -e first.run ]
then
    echo "Cold boot detected. Running firstrun.sh."
    screen -dmS init ~/firstrun.sh
fi

echo "Starting agent."
screen -dmS agent ~/agent.sh

echo "Starting watchdog."
sudo service watchdog restart
