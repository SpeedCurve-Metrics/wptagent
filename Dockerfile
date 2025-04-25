FROM ubuntu:24.04

LABEL author="support@speedcurve.com"

# Default Timeszone
#
# TODO Is there are better way to do this as most customers won't be in this tz?
# Maybe just keep it as UTC?
#
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Keep update and install in same layer to avoid Docker cachine issues
RUN apt-get update && \
  apt-get install -y \
  wget \
  curl \
  git \
  python3 \
  python3-pip \
  python3-ujson \
  python3-xlib \
  xvfb \
  imagemagick \
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
  nano

# Stable Chrome versions https://www.ubuntuupdates.org/package/google_chrome/stable/main/base/google-chrome-stable
#
# Firefox versions: https://download-installer.cdn.mozilla.net/pub/firefox/releases/

# Add the ARGs here so that changing them doesn't invalidate the previous layers' cache
ARG CHROME_STABLE_VERSION=133.0.6943.98-1
ARG FIREFOX_STABLE_VERSION=135.0
ARG LIGHTHOUSE_VERSION=12.3.0
ARG NODEJS_VERSION=20.x

# Install Node.js with nvm
#RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash && \
#  export NVM_DIR="$HOME/.nvm" && \
#  [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" && \
#  nvm install $NODEJS_VERSION

RUN  curl -fsSL https://deb.nodesource.com/setup_${NODEJS_VERSION} | sudo bash - && \
    sudo apt-get install -y nodejs

# Install browsers
# Note: Google have started removing old Chrome versions, so we cannot specify a version here. We
# just fetch the latest stable and unstable builds.
# Chrome Stable
#RUN wget -O /tmp/chrome-stable.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
#RUN apt install -y /tmp/chrome-stable.deb && \
#    rm /tmp/chrome-stable.deb

RUN  wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
RUN  sh -c 'echo "deb http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list'
  # Chrome stable has to be manually downloaded and installed (only latest stable version is available via apt-get)
RUN  wget --no-verbose -O /tmp/chrome.deb https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${CHROME_STABLE_VERSION}_amd64.deb
RUN  apt install -y /tmp/chrome.deb 
RUN  rm /tmp/chrome.deb
      

# Chrome Beta
# RUN wget -O /tmp/chrome-beta.deb https://dl.google.com/linux/direct/google-chrome-beta_current_amd64.deb
# RUN apt install -y /tmp/chrome-beta.deb && \
#    rm /tmp/chrome-beta.deb

# Chrome Unstable
# RUN wget -O /tmp/chrome-unstable.deb https://dl.google.com/linux/direct/google-chrome-unstable_current_amd64.deb
# RUN apt install -y /tmp/chrome-unstable.deb && \
#    rm /tmp/chrome-unstable.deb

# Firefox
# RUN wget -O /tmp/firefox.tar.bz2 https://download-installer.cdn.mozilla.net/pub/firefox/releases/${FIREFOX_STABLE_VERSION}/linux-x86_64/en-US/firefox-127.0.2.tar.bz2 && \
#  rm -rf /opt/firefox && \
#  tar -C /opt -xjf /tmp/firefox.tar.bz2 && \
#  rm /tmp/firefox.tar.bz2 && \
#  ln -s /opt/firefox/firefox /usr/local/bin/firefox

RUN wget  -O /tmp/firefox.deb https://download-installer.cdn.mozilla.net/pub/firefox/releases/${FIREFOX_STABLE_VERSION}/linux-x86_64/en-US/firefox-${FIREFOX_STABLE_VERSION}.deb
RUN apt install -y /tmp/firefox.deb && \
    rm /tmp/firefox.deb


# Get fonts
RUN echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections && \
  sudo DEBIAN_FRONTEND=noninteractive apt-get -y install ttf-mscorefonts-installer fonts-noto* && \
  sudo fc-cache -f -v

  # Cleaup to save space in layer
RUN sudo apt-get clean && \
  rm -rf /var/lib/apt/lists/*

# Install lighthouse
# RUN bash -c 'source $HOME/.nvm/nvm.sh   && \
RUN npm install -g lighthouse@${LIGHTHOUSE_VERSION}

# Install Python dependencies
COPY ./scripts/install/requirements.txt /wptagent/requirements.txt
RUN python3 -m pip install --break-system-packages --upgrade --user pip && \
    python3 -m pip install --break-system-packages --user -r /wptagent/requirements.txt

COPY ./wptagent.py /wptagent/wptagent.py
COPY ./internal /wptagent/internal
COPY ./ws4py /wptagent/ws4py
COPY ./urlmatch /wptagent/urlmatch
COPY ./docker/linux-headless/entrypoint.sh /wptagent/entrypoint.sh

WORKDIR /wptagent

HEALTHCHECK --interval=300s --timeout=30s --start-period=30s \
  CMD curl -f http://localhost:8888/ping || exit 1

CMD ["/bin/bash", "/wptagent/entrypoint.sh"]
