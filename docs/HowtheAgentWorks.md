# How the Agent Works
This currently focuses on how the Chrome Agent works, although the other browsers work in a similar way there are some differences

It's also a work in progress!

Agent is divided into three main parts
- Poll the server for jobs
- Execute the jobs it gets – launch browser, execute scripts, gather data as script executes
- Process the data it gathers and send it to the server

## Polling the Server 

## Executing the Job

## Processing the Data

In Chrome, there are three sources of used to generate the 'result' data
- Chrome Debugger Protocol (CDP) Events
- TimeLine Events (as seen if you export a trace from Chrome's Performance Panel)
- NetLog Events 

These are processed by
- `internal/support/devtools_parser.py`
- `internal/support/trace_parser.py`
- `internal/support/netlog_parser.py`

Each of these can be run as standalone CLI tools - see the code for the list of arguments

### Network Request Data

#### Chrome

In Chrome the data for network requests that are visualised as a waterfall is produced by merging CDP events and netlog data.

CDP data is a view of the requests the renderer makes and the responses it gets, this is not a complete picture of network activity. The netlog contains data on all the requests so includes ones that aren't visible to the renderer e.g. requests triggered by early hints, beacon API etc., and these are given a request_id starting 99999.9999.n

The netlog contains requests from all browser processes so may contain requests from internal services, where possible the services that make these requests are disabled via browser flags, or filtered when the netlog is processed


## Script Command Implementation

### setHeader

When headers are set via CDPs `[Network.setExtraHeaders](https://chromedevtools.github.io/devtools-protocol/tot/Network/#method-setExtraHTTPHeaders)` command then they are added to all outgoing requests, and this can create CORS issues.

CDPs `[Fetch Domain](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)` enables individual request interception based on a urlpattern.

`[Fetch.enable](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/#method-enable)` intialises interception. When a pattern matches a `[Fetch.requestPaused](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/#event-requestPaused)` event is sent to the agent for it to add headers. The agent then responds with`[Fetch.continueRequest](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/#method-continueRequest)`. 

**If the agent doesn't respond to the Fetch.requestPaused event the test will hang until it times out**

This flow is implemented in the agent via

#### devtools.py:set_header

For each new header set and entry is added to `additional_headers` and `Fetch.enable` called.

The additional headers array follow this format

``` json
[{
    'pattern': urlpattern, 
    'header': {
        'name': name, 
        'value': value
    }
}]
```

If there's no pattern specified in the setHeader command then a default pattern of *://*/* is applied. This should perhaps default to the origin of the page being tested instead

#### devtools.py:reset_headers

Empties the `additional_headers' array and calls `Fetch.disable`.

If request interception is extended to other uses e.g. authentication then this code will need reviewing. Perhaps it should empty the array and then call `Fetch.enable` with the empty array?


#### devtools.py:process_fetch_event

This processes the `Fetch.requestPaused` events. When one is recieved it compares the URL of the request with the patterns in the `additional_header` array, and when there's a match responds with the appropriate headers.

To avoid the test hanging the error handling attempts to always return a response even if it's an empty array.

Comparisons between the URL and the URL Pattern are made using [urlmatch](https://github.com/jessepollak/urlmatch). This module doesn't support unicode strings so the strings are forced to non unicode which may present issues and should be revisited in the future.

*://*/* will match all requests
https://*.speedcurve.com/* will match all requests to https://www.speedcurve.com, https://app.speedcurve.com etc
https://www.speedcurve.com will only match request to https://www.speedcurve.com/ and won't match https://www.speedcurve.com/some-path 