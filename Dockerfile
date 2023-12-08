FROM ubuntu:18.04

LABEL author="support@speedcurve.com" 

# Default versions for Chrome Stable and Lighthouse
#
# Can be overidden at build time e.g. docker build --build-arg LIGHTHOUSE_VERSION=8.5.1
#
# Stable Chrome versions https://www.ubuntuupdates.org/package/google_chrome/stable/main/base/google-chrome-stable
#
# Firefox versions: https://download-installer.cdn.mozilla.net/pub/firefox/releases/
#
ARG CHROME_STABLE_VERSION=115.0.5790.170-1
ARG FIREFOX_STABLE_VERSION=115.0.3
ARG LIGHTHOUSE_VERSION=10.4.0
ARG NODEJS_VERSION=16.x

# Default Timeszone
#
# TODO Is there are better way to do this as most customers won't be in this tz?
# Maybe just keep it as UTC?
#
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && \
  apt-get install -y \
    wget \
    curl \
    git \
    python \
    python-pip \
    python-ujson \
    xvfb \
    imagemagick \
    python-dev \
    zlib1g-dev \
    libjpeg-dev \
    psmisc \
    dbus-x11 \
    sudo \
    kmod \
    ffmpeg \
    net-tools \
    tcpdump \
    traceroute \
    bind9utils \
    libnss3-tools \
    iproute2 \
    software-properties-common \
    nano && \
#    gpg-agent \
#    python-setuptools \
#    gcc && \
# Node setup
# Node
  curl -sL https://deb.nodesource.com/setup_${NODEJS_VERSION} | sudo -E bash - && \
# Install browsers
# Chrome
  wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
  echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list && \
# Chrome stable has to be manually downloaded and installed (only latest stable version is available via apt-get)
  wget --no-verbose -O /tmp/chrome.deb https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${CHROME_STABLE_VERSION}_amd64.deb && \
    apt install -y /tmp/chrome.deb && \
    rm /tmp/chrome.deb && \
# Firefox
  apt-get update && \
  wget --no-verbose -O /tmp/firefox.tar.bz2 https://download-installer.cdn.mozilla.net/pub/firefox/releases/${FIREFOX_STABLE_VERSION}/linux-x86_64/en-US/firefox-${FIREFOX_STABLE_VERSION}.tar.bz2 && \
  rm -rf /opt/firefox && \
  tar -C /opt -xjf /tmp/firefox.tar.bz2 && \
  rm /tmp/firefox.tar.bz2 && \
  ln -s /opt/firefox/firefox /usr/local/bin/firefox && \
  apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -yq \
    firefox-geckodriver \
    nodejs && \
#  apt-get update && \
#  add-apt-repository -y ppa:ubuntu-mozilla-daily/ppa && \
#    DEBIAN_FRONTEND=noninteractive apt-get install -yq \
#    google-chrome-beta \
#    google-chrome-unstable \
# Firefox 
#    firefox \
#    firefox-trunk \
# Get fonts
  echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections && \
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y install ttf-mscorefonts-installer fonts-noto* && \
  sudo fc-cache -f -v && \
# Cleaup to save space in layer
  sudo apt-get clean && \
  rm -rf /var/lib/apt/lists/* && \
# Install lighthouse
  npm install -g lighthouse@${LIGHTHOUSE_VERSION} && \
# Install other utilities
  pip install --no-cache-dir \
    dnspython \
    monotonic \
    pillow \
    psutil \
    requests \
    tornado \
    'wsaccel==0.6.3' \
    xvfbwrapper \
    'brotli==1.0.9' \
    'fonttools>=3.44.0,<4.0.0' \
    'mozrunner==7.4.0' \
    'mozfile==2.1.0' \
    marionette_driver \
    selenium \
    future

COPY ./wptagent.py /wptagent/wptagent.py
COPY ./internal /wptagent/internal
COPY ./ws4py /wptagent/ws4py
COPY ./urlmatch /wptagent/urlmatch

COPY ./docker/linux-headless/entrypoint.sh /wptagent/entrypoint.sh

WORKDIR /wptagent

HEALTHCHECK --interval=300s --timeout=30s --start-period=30s \
  CMD curl -f http://localhost:8888/ping || exit 1

CMD ["/bin/bash", "/wptagent/entrypoint.sh"]

  