# Current status of Python 3 / Ubuntu 22.04 Post

## 2024-08-13

### TODO

#### General

[] rejig Dockerfile to reduce layers and other cleanups to make it smaller (current release is 2GB, this build is 4GB)
[] Install known versions of Browsers and LH
[] Remove Selenium telemetry
[] Add prefs to block FF access to captive portal and ??? (what was the other thing)
[] Prompts for password on startup in VM
[] Seeing ERR_CONNECTION_RESET in netlogs when testing www.bbc.co.uk in Chrome
[] Failures posting large files to server e.g. debug log
[] Netlog thread trying to read the pipe after it's closed - this looks like a timing issue with the threads
[] Remove netlog code from trace_parser 



#### Docker Only
[] tcpdump fails to launch on Docker (works in VM)
[] test traceroute

### Done
[x] Errors flushing DNS
[x] Error extracting font metadata
[x] Save generated netlog
[x] DNS lookups seem to be missing
[x] Removed H2 push from NetLog parser as have been removed from Chrome
[x] Remove blink feature usage from trace_parser

### Notes

Chrome and Firefox tests execute and produce waterfalls but there are still errors in the logs

Lightouse fails to execute – shell can't find it so assume it's a problem with it installed via NVM

tcpdump (and presumably traceroute) fail to launch with a python error


