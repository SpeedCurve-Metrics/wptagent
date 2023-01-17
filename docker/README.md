# SpeedCurve Synthetic Agent for Docker

Docker container for the SpeedCurve synthetic agent with Chrome, Firefox and Lighthouse installed

## Prequisites

*ifb* must be loaded on the *host* for traffic shaping to work

```
sudo modprobe ifb numifbs=1
```

## Building the Container

Build the container from the *root* folder of the repo

```
docker build -t speedcurve-agent . -f docker/Dockerfile

```

## Using the Container

Three environment variables MUST to be set for the container to execute successfully!

- SERVER_URL - URL of SpeedCurve endpoint that the agent will poll for work and upload results to
- LOCATION - Name of the location
- KEY - key for the location


An example configuration might look like:

```
docker run -dit --init --name speedcurve-agent --shm-size 1g --network host --cap-add=NET_ADMIN --env SERVER_URL=xxx --env LOCATION=yyy --env KEY=zzz speedcurve-agent
```
