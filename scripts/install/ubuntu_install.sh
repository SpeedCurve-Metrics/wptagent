#!/bin/bash

set -eu

: ${UBUNTU_VERSION:=`(lsb_release -rs | cut -b 1,2)`}

# Stable Chrome versions https://www.ubuntuupdates.org/package/google_chrome/stable/main/base/google-chrome-stable
#
# Firefox versions: https://download-installer.cdn.mozilla.net/pub/firefox/releases/

CHROME_STABLE_VERSION=126.0.6478.126-1
FIREFOX_STABLE_VERSION=127.0.2
LIGHTHOUSE_VERSION=12.1.0
NODEJS_VERSION=20.x

until sudo apt-get update
do
    sleep 1
done

until sudo apt-get install -y imagemagick ffmpeg xvfb dbus-x11 cgroup-tools traceroute software-properties-common psmisc libnss3-tools iproute2 net-tools git curl \
    wget zlib1g-dev libjpeg-dev sudo kmod tcpdump bind9utils nano
do
    sleep 1
done

sudo dbus-uuidgen --ensure

# Setup Python, it's environment and dependencies
until sudo apt-get install -y python3 python3-pip python3-venv python3-ujson python3-xlib
do
    sleep 1
done
python3 -m venv /home/ubuntu/agent_env
source /home/ubuntu/agent_env/bin/activate
pip3 install -r /home/ubuntu/wptagent/scripts/install/requirements.txt


# Install NodeJS and Lighthouse
curl -sL https://deb.nodesource.com/setup_${NODEJS_VERSION} | sudo -E bash -
until sudo apt-get install -y nodejs
do
    sleep 1
done
until sudo npm install -g lighthouse@${LIGHTHOUSE_VERSION}
do
    sleep 1
done
sudo npm update -g

# Browsers
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
sudo sh -c 'echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list'
# Chrome stable has to be manually downloaded and installed (only latest stable version is available via apt-get)
sudo wget --no-verbose -O /tmp/chrome.deb https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${CHROME_STABLE_VERSION}_amd64.deb
sudo apt install -y /tmp/chrome.deb
sudo rm /tmp/chrome.deb
# Firefox
sudo wget --no-verbose -O /tmp/firefox.tar.bz2 https://download-installer.cdn.mozilla.net/pub/firefox/releases/${FIREFOX_STABLE_VERSION}/linux-x86_64/en-US/firefox-${FIREFOX_STABLE_VERSION}.tar.bz2
sudo rm -rf /opt/firefox
sudo tar -C /opt -xjf /tmp/firefox.tar.bz2
sudp rm /tmp/firefox.tar.bz2
sudo ln -s /opt/firefox/firefox /usr/local/bin/firefox
sudo apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -yq firefox-geckodriver 

sudo add-apt-repository -y ppa:ubuntu-mozilla-daily/ppa
sudo add-apt-repository -y ppa:mozillateam/ppa
sudo apt-get update
until sudo DEBIAN_FRONTEND=noninteractive apt-get install -yq google-chrome-beta google-chrome-unstable firefox-trunk firefox-esr firefox-geckodriver
do
    sleep 1
done

# Install the fonts - needed for non-Latin character sets like Chinese, Korean etc 
echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections
until sudo DEBIAN_FRONTEND=noninteractive apt-get -y install ttf-mscorefonts-installer fonts-noto*
do
    sleep 1
done

# Install any missing dependencies and cleanup
until sudo apt --fix-broken install -y
do
    sleep 1
done
sudo fc-cache -f -v
sudo apt-get clean

# Increase the number of open files
cat << _LIMITS_ | sudo tee /etc/security/limits.d/wptagent.conf
# Limits increased for wptagent
* soft nofile 250000
* hard nofile 300000
_LIMITS_

# Increase the number of SYN retries
cat << _SYSCTL_ | sudo tee /etc/sysctl.d/60-wptagent.conf
net.ipv4.tcp_syn_retries = 4
_SYSCTL_

sudo sysctl -p

# Copy run scripts to home directory
cp /home/ubuntu/wptagent/scripts/run/* /home/ubuntu

echo 'Reboot is recommended before starting testing'
