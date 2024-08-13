# Current status of Python 3 / Ubuntu 22.04 Post

## 2024-08-09

### TODO

#### General

[] rejig Dockerfile to reduce layers and other cleanups to make it smaller (current release is 2GB, this build is 4GB)
[] Install known versions of Browsers and LH
[] Remove Selenium telemetry
[] Add prefs to block FF access to captive portal and ??? (what was the other thing)
[] Prompts for password on startup in VM
[] Seeing ERR_CONNECTION_RESET in netlogs when testing www.bbc.co.uk in Chrome
[] DNS lookups seem to be missing
[] Error extracting font metadata


#### Docker Only
[] tcpdump fails to launch on Docker (works in VM)
[] test traceroute

### Done
[x] Errors flushing DNS

### Notes

Chrome and Firefox tests execute and produce waterfalls but there are still errors in the logs

Lightouse fails to execute – shell can't find it so assume it's a problem with it installed via NVM

tcpdump (and presumably traceroute) fail to launch with a python error


