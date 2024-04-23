# SpeedCurve Synthetic Agent

(Based on a fork of the Apache branch of the WebPageTest agent)


## Docker

Docker container for the SpeedCurve synthetic agent with Chrome, Firefox and Lighthouse installed

### Prequisites

The container relies on network level packet shaping.

For this to work correctly *ifb* must be loaded on the *host*

```
sudo modprobe ifb numifbs=1
```

The following command checks whether *ifb* is loaded on the host and can be executed from either the host or the container.

```
sudo lsmod | grep ifb
```

The also needs `NET_ADMIN` permissions and must be run with `--cap-add=NET_ADMIN`


### Known Issues

Firefox support is currently broken in the current container release (Nov 2022)


### Building the Container

Build the container directly from GitHub

```
docker build https://github.com/SpeedCurve-Metrics/wptagent.git#docker-release -t speedcurve-agent
```

Alternatively the container can be built from the *root* folder in the **docker-release** branch of the repo

```
docker build -t speedcurve-agent . 

```

### Using the Container

Three environment variables MUST to be set for the container to execute successfully!

- SERVER_URL - URL of SpeedCurve endpoint that the agent will poll for work and upload results to
- LOCATION - Name of the location
- KEY - key for the location

SpeedCurve will provide this configuration information


An example configuration might look like:

```
docker run -dit --init --name speedcurve-agent --shm-size 1g --network host --cap-add=NET_ADMIN --env SERVER_URL=xxx --env LOCATION=yyy --env KEY=zzz speedcurve-agent
```

## Notes

Only ./wptagent.py, ./internal and ./ws4py are installed in the container.

All other files / folders are excluded via .dockerignore