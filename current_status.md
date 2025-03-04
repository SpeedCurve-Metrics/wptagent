# Current status of Python 3 / Ubuntu 22.04 Post

## 2024-08-13

### TODO

#### General

[] rejig Dockerfile to reduce layers and other cleanups to make it smaller (current release is 2GB, this build is 4GB)
[] Add prefs to block FF access to captive portal and ??? (what was the other thing)
[] Seeing ERR_CONNECTION_RESET in netlogs when testing www.bbc.co.uk in Chrome
[] Remove netlog code from trace_parser 



#### Docker Only
[] tcpdump fails to launch on Docker (works in VM)
[] test traceroute
[] test LH


### Temp Workarounds
[] Prompts for password on startup in VM - grant priveledges in /etc/sudoers
[x] Failures posting large files to server e.g. debug log - fixed in php.ini


### Done
[x] Errors flushing DNS
[x] Error extracting font metadata
[x] Save generated netlog
[x] DNS lookups seem to be missing
[x] Removed H2 push from NetLog parser as have been removed from Chrome
[x] Remove blink feature usage from trace_parser
[x] Error closing websocket (reverted automatic changes to ws4py)
[x] Netlog thread trying to read the pipe after it's closed - this looks like a timing issue with the threads and only appears to happen during a LH run
[x] Install known versions of Browsers and LH
[x] Remove Selenium telemetry



### Notes






