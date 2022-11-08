#!/usr/bin/env python
"""
Process a Chrome Netlog into a set of requests for further processing by the agent

Majority of the code is ported from devtools_parser.py 

Chromium Code that generates NetLog https://source.chromium.org/chromium/chromium/src/+/main:net/log/

Needs cleaning up to make it more 'pythonic'
"""

"""
Copyright 2022 SpeedCurve Limited
Copyright 2019 WebPageTest LLC.
Copyright 2016 Google Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import gzip
import logging
import os
import re
import sys
import time

if (sys.version_info >= (3, 0)):
    from urllib.parse import urlparse # pylint: disable=import-error
    unicode = str
    GZIP_TEXT = 'wt'
    GZIP_READ_TEXT = 'rt'
else:
    from urlparse import urlparse # pylint: disable=import-error
    GZIP_TEXT = 'w'
    GZIP_READ_TEXT = 'r'

# try a fast json parser if it is installed
try:
    import ujson as json
except BaseException:
    import json


class NetLog():
    """Main class"""
    def __init__(self):
        self.netlog = {'bytes_in': 0, 'bytes_out': 0, 'next_request_id': 1000000}
        self.start_time = None
        self.marked_start_time = None
        self.netlog_requests = None
        self.netlog_event_types = {}
        self.constants = {}
        return

#
# process_netlog
#
# NetLog format is typically:
#
# {"constants": {…} 
# events: [
#  …  
# ]}
#
# The closing ]} is often missing making whole file invalid JSON in some tools
# Files can also be large so each line is processed as JSON in isolation
#
    def process_netlog(self, netlog_file):
        """ Load the netlog and process each line in isolation """

        with open(netlog_file, 'rt', encoding='utf-8') as file:
            processing_events=False
            for line in file:
                try:
                    line = line.strip(", \r\n")
                    if processing_events:
                        if line.startswith('{'):
                            event = json.loads(line)
                            self.process_event(event)
                    elif line.startswith('{"constants":'):
                        raw = json.loads(line + '}')
                        if raw and 'constants' in raw:
                            self.process_constants(raw['constants'])
                    elif line.startswith('"events": ['):
                        processing_events = True
                except Exception as error:
                    logging.exception('Error processing ' + line)
                    logging.exception(error)

#
# add_constants
#
# Constants are string:number pairs grouped into an object e.g.
#
#    "logEventPhase":{
#        "PHASE_BEGIN":1,
#        "PHASE_END":2,
#        "PHASE_NONE":0
#    },
#
# Event entries use the numerical identifier e.g. {"phase":1,
#
# Create lookup table so numerical entries used in events can be replaced by string equivalents
# so that existing code copied from trace_parser.py works unchanged
#
# TODO(AD): 
#   Review keeping numerical entries in events rather than preprocessing events e.g. constants['logEventPhase']['PHASE_BEGIN']
#   Do we need any of the non-dictionary constants, is there anything that should be excluded?
#
    def process_constants(self, constants):
        """ Create lookup table from constants entry in NetLog """
        for entry in constants:
            # Exclude entries such as "activeFieldTrialGroups":[] that aren't dictionaries
            if isinstance(constants[entry], dict):
                self.constants[entry] = {}
                for key in constants[entry]:
                    value = constants[entry][key]
                    self.constants[entry][value] = key

# 
# process_event
#
# Process an individual Netlog event
#
# Needs a tidy up and lots of error checking
#
# TODO(AD)
#   Is using try/except just being lazy here - does it need better checks?
#   Convert source.time to an integer???
#   Reuse type for the string rather than add name to entry?
#   This takes a minimal view ATM what other fields need converting?
#
    def process_event(self, event):

        try:
            if 'phase' in event:
                event['phase'] = [event['phase']]
            if 'type' in event:
                event['name'] = self.constants['logEventTypes'][event['type']]
            if 'source' in event:
                if 'type' in event['source']:
                    event['source']['name'] = self.constants['logSourceType'][event['source']['type']]
                if 'time' in event['source']:
                    event['source']['time'] = int(event['source']['time']) # TODO(AD) is int large enough in python 2.7?
            
            if 'time' in event:
                event['time'] = int(event['time']) # TODO(AD) is int large enough in python 2.7?

            self.ProcessNetlogEvent(event)
        except Exception as error: 
            logging.exception(error)
        
    ##########################################################################
    #   Netlog - extracted from trace_parser.py and updated for netlog events
    ##########################################################################
    def ProcessNetlogEvent(self, event):    
        
        if 'source' in event and 'id' in event['source'] and 'name' in event:
            try:
                if isinstance(event['source']['id'], (str, unicode)):
                    event['id'] = int(event['id'], 16)

#                event_type = None
#                name = event['name']
#                if 'source_type' in event['args']:
#                    event_type = event['args']['source_type']
#                    if name not in self.netlog_event_types:
#                        self.netlog_event_types[name] = event_type
#                elif name in self.netlog_event_types:
#                    event_type = self.netlog_event_types[name]
                
                event_type=event['source']['name'] # TODO (AD) switch to type?

                if event_type is not None:
                    if event_type == 'HOST_RESOLVER_IMPL_JOB' or \
                            event['name'].startswith('HOST_RESOLVER'):
                        self.ProcessNetlogDnsEvent(event)
                    elif event_type == 'CONNECT_JOB' or \
                            event_type == 'SSL_CONNECT_JOB' or \
                            event_type == 'TRANSPORT_CONNECT_JOB':
                        self.ProcessNetlogConnectJobEvent(event)
                    elif event_type == 'HTTP_STREAM_JOB':
                        self.ProcessNetlogStreamJobEvent(event)
                    elif event_type == 'HTTP2_SESSION':
                        self.ProcessNetlogHttp2SessionEvent(event)
                    elif event_type == 'QUIC_SESSION':
                        self.ProcessNetlogQuicSessionEvent(event)
                    elif event_type == 'SOCKET':
                        self.ProcessNetlogSocketEvent(event)
                    elif event_type == 'UDP_SOCKET':
                        self.ProcessNetlogUdpSocketEvent(event)
                    elif event_type == 'URL_REQUEST':
                        self.ProcessNetlogUrlRequestEvent(event)
                    elif event_type == 'DISK_CACHE_ENTRY':
                        self.ProcessNetlogDiskCacheEvent(event)
            except Exception:
                logging.exception('Error processing netlog event')

    def post_process_netlog_events(self):
        """Post-process the raw netlog events into request data"""
        if self.netlog_requests is not None:
            return self.netlog_requests
        requests = []
        known_hosts = ['cache.pack.google.com', 'clients1.google.com', 'redirector.gvt1.com']
        last_time = 0
        if 'url_request' in self.netlog:
            for request_id in self.netlog['url_request']:
                request = self.netlog['url_request'][request_id]
                request['fromNet'] = bool('start' in request)
                if 'start' in request and request['start'] > last_time:
                    last_time = request['start']
                if 'end' in request and request['end'] > last_time:
                    last_time = request['end']
                # build a URL from the request headers if one wasn't explicitly provided
                if 'url' not in request and 'request_headers' in request:
                    scheme = None
                    origin = None
                    path = None
                    if 'line' in request:
                        match = re.search(r'^[^\s]+\s([^\s]+)', request['line'])
                        if match:
                            path = match.group(1)
                    if 'group' in request:
                        scheme = 'http'
                        if request['group'].find('ssl/') >= 0:
                            scheme = 'https'
                    elif 'socket' in request and 'socket' in self.netlog and request['socket'] in self.netlog['socket']:
                        socket = self.netlog['socket'][request['socket']]
                        scheme = 'http'
                        if 'certificates' in socket or 'ssl_start' in socket:
                            scheme = 'https'
                    for header in request['request_headers']:
                        try:
                            index = header.find(u':', 1)
                            if index > 0:
                                key = header[:index].strip(u': ').lower()
                                value = header[index + 1:].strip(u': ')
                                if key == u'scheme':
                                    scheme = unicode(value)
                                elif key == u'host':
                                    origin = unicode(value)
                                elif key == u'authority':
                                    origin = unicode(value)
                                elif key == u'path':
                                    path = unicode(value)
                        except Exception:
                            logging.exception("Error generating url from request headers")
                    if scheme and origin and path:
                        request['url'] = scheme + u'://' + origin + path

                # TODO (AD) What's the purpose of the check for 192.168.10.x?        
                if 'url' in request and not request['url'].startswith('http://127.0.0.1') and \
                        not request['url'].startswith('http://192.168.10.'):
                    request_host = urlparse(request['url']).hostname
                    if request_host not in known_hosts:
                        known_hosts.append(request_host)
                    # Match orphaned request streams with their h2 sessions
                    if 'stream_id' in request and 'h2_session' not in request and 'url' in request:
                        for h2_session_id in self.netlog['h2_session']:
                            h2_session = self.netlog['h2_session'][h2_session_id]
                            if 'host' in h2_session:
                                session_host = h2_session['host'].split(':')[0]
                                if 'stream' in h2_session and \
                                        request['stream_id'] in h2_session['stream'] and \
                                        session_host == request_host and \
                                        'request_headers' in request and \
                                        'request_headers' in h2_session['stream'][request['stream_id']]:
                                    # See if the path header matches
                                    stream = h2_session['stream'][request['stream_id']]
                                    request_path = None
                                    stream_path = None
                                    for header in request['request_headers']:
                                        if header.startswith(':path:'):
                                            request_path = header
                                            break
                                    for header in stream['request_headers']:
                                        if header.startswith(':path:'):
                                            stream_path = header
                                            break
                                    if request_path is not None and request_path == stream_path:
                                        request['h2_session'] = h2_session_id
                                        break
                    # Copy any http/2 info over
                    if 'h2_session' in self.netlog and \
                            'h2_session' in request and \
                            request['h2_session'] in self.netlog['h2_session']:
                        h2_session = self.netlog['h2_session'][request['h2_session']]
                        if 'socket' not in request and 'socket' in h2_session:
                            request['socket'] = h2_session['socket']
                        if 'stream_id' in request and \
                                'stream' in h2_session and \
                                request['stream_id'] in h2_session['stream']:
                            stream = h2_session['stream'][request['stream_id']]
                            if 'request_headers' in stream:
                                request['request_headers'] = stream['request_headers']
                            if 'response_headers' in stream:
                                request['response_headers'] = stream['response_headers']
                            if 'exclusive' in stream:
                                request['exclusive'] = 1 if stream['exclusive'] else 0
                            if 'parent_stream_id' in stream:
                                request['parent_stream_id'] = stream['parent_stream_id']
                            if 'weight' in stream:
                                request['weight'] = stream['weight']
                                if 'priority' not in request:
                                    if request['weight'] >= 256:
                                        request['priority'] = 'HIGHEST'
                                    elif request['weight'] >= 220:
                                        request['priority'] = 'MEDIUM'
                                    elif request['weight'] >= 183:
                                        request['priority'] = 'LOW'
                                    elif request['weight'] >= 147:
                                        request['priority'] = 'LOWEST'
                                    else:
                                        request['priority'] = 'IDLE'
                            if 'first_byte' not in request and 'first_byte' in stream:
                                request['first_byte'] = stream['first_byte']
                            if 'end' not in request and 'end' in stream:
                                request['end'] = stream['end']
                            if stream['bytes_in'] > request['bytes_in']:
                                request['bytes_in'] = stream['bytes_in']
                                request['chunks'] = stream['chunks']
                    if 'phantom' not in request and 'request_headers' in request:
                        requests.append(request)
            # See if there were any connections for hosts that we didn't know about that timed out
            if 'urls' in self.netlog:
                failed_hosts = {}
                if 'stream_job' in self.netlog:
                    for stream_job_id in self.netlog['stream_job']:
                        stream_job = self.netlog['stream_job'][stream_job_id]
                        if 'group' in stream_job and 'socket_start' in stream_job and 'socket' not in stream_job:
                            matches = re.match(r'^.*/([^:]+)\:\d+$', stream_job['group'])
                            if matches:
                                group_hostname = matches.group(1)
                                if group_hostname not in known_hosts and group_hostname not in failed_hosts:
                                    failed_hosts[group_hostname] = {'start': stream_job['socket_start']}
                                    if 'socket_end' in stream_job:
                                        failed_hosts[group_hostname]['end'] = stream_job['socket_end']
                                    else:
                                        failed_hosts[group_hostname]['end'] = max(stream_job['socket_start'], last_time)
                if failed_hosts:
                    for url in self.netlog['urls']:
                        host = urlparse(url).hostname
                        if host in failed_hosts:
                            request = {'url': url,
                                       'created': failed_hosts[host]['start'],
                                       'start': failed_hosts[host]['start'],
                                       'end': failed_hosts[host]['end'],
                                       'connect_start': failed_hosts[host]['start'],
                                       'connect_end': failed_hosts[host]['end'],
                                       'fromNet': True,
                                       'status': 12029}
                            requests.append(request)
            if len(requests):
                # Sort the requests by the start time
                requests.sort(key=lambda x: x['start'] if 'start' in x else x['created'])
                # Assign the socket connect time to the first request on each socket
                if 'socket' in self.netlog:
                    for request in requests:
                        if 'socket' in request and request['socket'] in self.netlog['socket']:
                            socket = self.netlog['socket'][request['socket']]
                            if 'address' in socket:
                                request['server_address'] = socket['address']
                            if 'source_address' in socket:
                                request['client_address'] = socket['source_address']
                            if 'group' in socket:
                                request['socket_group'] = socket['group']
                            if 'claimed' not in socket:
                                socket['claimed'] = True
                                if 'connect_start' in socket:
                                    request['connect_start'] = socket['connect_start']
                                if 'connect_end' in socket:
                                    request['connect_end'] = socket['connect_end']
                                if 'ssl_start' in socket:
                                    request['ssl_start'] = socket['ssl_start']
                                if 'ssl_end' in socket:
                                    request['ssl_end'] = socket['ssl_end']
                                if 'certificates' in socket:
                                    request['certificates'] = socket['certificates']
                                if 'h2_session' in request and request['h2_session'] in self.netlog['h2_session']:
                                    h2_session = self.netlog['h2_session'][request['h2_session']]
                                    if 'server_settings' in h2_session:
                                        request['http2_server_settings'] = h2_session['server_settings']
                                if 'tls_version' in socket:
                                    request['tls_version'] = socket['tls_version']
                                if 'tls_resumed' in socket:
                                    request['tls_resumed'] = socket['tls_resumed']
                                if 'tls_next_proto' in socket:
                                    request['tls_next_proto'] = socket['tls_next_proto']
                                if 'tls_cipher_suite' in socket:
                                    request['tls_cipher_suite'] = socket['tls_cipher_suite']

                # Assign the DNS lookup to the first request that connected to the DocumentSetDomain
                if 'dns' in self.netlog:
                    # Build a mapping of the DNS lookups for each domain
                    dns_lookups = {}
                    for dns_id in self.netlog['dns']:
                        dns = self.netlog['dns'][dns_id]
                        if 'host' in dns and 'start' in dns and 'end' in dns \
                                and dns['end'] >= dns['start'] and 'address_list' in dns:
                            hostname = dns['host']
                            separator = hostname.find(':')
                            if separator > 0:
                                hostname = hostname[:separator]
                            dns['elapsed'] = dns['end'] - dns['start']
                            if hostname not in dns_lookups:
                                dns_lookups[hostname] = dns
                            # collect all of the times for all of the DNS lookups for that host
                            if 'times' not in dns_lookups[hostname]:
                                dns_lookups[hostname]['times'] = []
                            dns_lookups[hostname]['times'].append({
                                'start': dns['start'],
                                'end': dns['end'],
                                'elapsed': dns['elapsed'],
                            })
                    # Go through the requests and assign the DNS lookups as needed
                    for request in requests:
                        if 'connect_start' in request:
                            hostname = urlparse(request['url']).hostname
                            if hostname in dns_lookups and 'claimed' not in dns_lookups[hostname]:
                                dns = dns_lookups[hostname]
                                dns['claimed'] = True
                                # Find the longest DNS time that completed before connect_start
                                if 'times' in dns_lookups[hostname]:
                                    elapsed = None
                                    for dns in dns_lookups[hostname]['times']:
                                        dns['end'] = min(dns['end'], request['connect_start'])
                                        if dns['end'] >= dns['start']:
                                            dns['elapsed'] = dns['end'] - dns['start']
                                            if elapsed is None or dns['elapsed'] > elapsed:
                                                elapsed = dns['elapsed']
                                                request['dns_start'] = dns['start']
                                                request['dns_end'] = dns['end']
                    # Make another pass for any DNS lookups that didn't establish a connection (HTTP/2 coalescing)
                    for request in requests:
                        hostname = urlparse(request['url']).hostname
                        if hostname in dns_lookups and 'claimed' not in dns_lookups[hostname]:
                            dns = dns_lookups[hostname]
                            dns['claimed'] = True
                            # Find the longest DNS time that completed before the request start
                            if 'times' in dns_lookups[hostname]:
                                elapsed = None
                                for dns in dns_lookups[hostname]['times']:
                                    dns['end'] = min(dns['end'], request['start'])
                                    if dns['end'] >= dns['start']:
                                        dns['elapsed'] = dns['end'] - dns['start']
                                        if elapsed is None or dns['elapsed'] > elapsed:
                                            elapsed = dns['elapsed']
                                            request['dns_start'] = dns['start']
                                            request['dns_end'] = dns['end']

                # Find the start timestamp if we didn't have one already
                times = ['dns_start', 'dns_end',
                         'connect_start', 'connect_end',
                         'ssl_start', 'ssl_end',
                         'start', 'created', 'first_byte', 'end']
                for request in requests:
                    for time_name in times:
                        if time_name in request and self.marked_start_time is None:
                            if self.start_time is None or request[time_name] < self.start_time:
                                self.start_time = request[time_name]
                # Go through and adjust all of the times to be relative in ms
                if self.start_time is not None:
                    for request in requests:
                        for time_name in times:
                            if time_name in request:
                                request[time_name] = \
                                        float(request[time_name] - self.start_time) / 1000.0
                        for key in ['chunks', 'chunks_in', 'chunks_out']:
                            if key in request:
                                for chunk in request[key]:
                                    if 'ts' in chunk:
                                        chunk['ts'] = float(chunk['ts'] - self.start_time) / 1000.0
                else:
                    requests = []
        if not len(requests):
            requests = None
        self.netlog_requests = requests
        return requests

    def ProcessNetlogConnectJobEvent(self, event):
        """Connect jobs link sockets to DNS lookups/group names"""
        if 'connect_job' not in self.netlog:
            self.netlog['connect_job'] = {}
        request_id = event['source']['id']
        if request_id not in self.netlog['connect_job']:
            self.netlog['connect_job'][request_id] = {'created': event['time']}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['connect_job'][request_id]
        name = event['name']
        if name == 'TRANSPORT_CONNECT_JOB_CONNECT' and event['phase'] == 'PHASE_BEGIN':
            entry['connect_start'] = event['time']
        if name == 'TRANSPORT_CONNECT_JOB_CONNECT' and event['phase'] == 'PHASE_END':
            entry['connect_end'] = event['time']
        if 'source_dependency' in params and 'id' in params['source_dependency']:
            if name == 'CONNECT_JOB_SET_SOCKET':
                socket_id = params['source_dependency']['id']
                entry['socket'] = socket_id
                if 'socket' in self.netlog and socket_id in self.netlog['socket']:
                    if 'group' in entry:
                        self.netlog['socket'][socket_id]['group'] = entry['group']
                    if 'dns' in entry:
                        self.netlog['socket'][socket_id]['dns'] = entry['dns']
        if 'group_name' in params:
            entry['group'] = params['group_name']
        if 'group_id' in params:
            entry['group'] = params['group_id']

    def ProcessNetlogStreamJobEvent(self, event):
        """Stream jobs link requests to sockets"""
        if 'stream_job' not in self.netlog:
            self.netlog['stream_job'] = {}
        request_id = event['source']['id']
        if request_id not in self.netlog['stream_job']:
            self.netlog['stream_job'][request_id] = {'created': event['time']}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['stream_job'][request_id]
        name = event['name']
        if 'group_name' in params:
            entry['group'] = params['group_name']
        if 'group_id' in params:
            entry['group'] = params['group_id']
        if name == 'HTTP_STREAM_REQUEST_STARTED_JOB':
            entry['start'] = event['time']
        if name == 'TCP_CLIENT_SOCKET_POOL_REQUESTED_SOCKET':
            entry['socket_start'] = event['time']
        if 'source_dependency' in params and 'id' in params['source_dependency']:
            if name == 'SOCKET_POOL_BOUND_TO_SOCKET':
                socket_id = params['source_dependency']['id']
                entry['socket_end'] = event['time']
                entry['socket'] = socket_id
                if 'url_request' in entry and entry['urlrequest'] in self.netlog['urlrequest']:
                    self.netlog['urlrequest'][entry['urlrequest']]['socket'] = socket_id
                    if 'group' in entry:
                        self.netlog['urlrequest'][entry['urlrequest']]['group'] = entry['group']
            if name == 'HTTP_STREAM_JOB_BOUND_TO_REQUEST':
                url_request_id = params['source_dependency']['id']
                entry['url_request'] = url_request_id
                if 'socket_end' not in entry:
                    entry['socket_end'] = event['time']
                if url_request_id in self.netlog['url_request']:
                    url_request = self.netlog['url_request'][url_request_id]
                    if 'group' in entry:
                        url_request['group'] = entry['group']
                    if 'socket' in entry:
                        url_request['socket'] = entry['socket']
                    if 'h2_session' in entry:
                        url_request['h2_session'] = entry['h2_session']
            if name == 'HTTP2_SESSION_POOL_IMPORTED_SESSION_FROM_SOCKET' or \
                    name == 'HTTP2_SESSION_POOL_FOUND_EXISTING_SESSION' or \
                    name == 'HTTP2_SESSION_POOL_FOUND_EXISTING_SESSION_FROM_IP_POOL':
                h2_session_id = params['source_dependency']['id']
                entry['h2_session'] = h2_session_id
                if 'socket_end' not in entry:
                    entry['socket_end'] = event['time']
                if h2_session_id in self.netlog['h2_session'] and 'socket' in self.netlog['h2_session'][h2_session_id]:
                    entry['socket'] = self.netlog['h2_session'][h2_session_id]['socket']
                if 'url_request' in entry and entry['urlrequest'] in self.netlog['urlrequest']:
                    self.netlog['urlrequest'][entry['urlrequest']]['h2_session'] = h2_session_id

    def ProcessNetlogHttp2SessionEvent(self, event):
        """Raw H2 session information (linked to sockets and requests)"""
        if 'h2_session' not in self.netlog:
            self.netlog['h2_session'] = {}
        session_id = event['source']['id']
        if session_id not in self.netlog['h2_session']:
            self.netlog['h2_session'][session_id] = {'stream': {}}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['h2_session'][session_id]
        name = event['name']
        if 'source_dependency' in params and 'id' in params['source_dependency']:
            if name == 'HTTP2_SESSION_INITIALIZED':
                socket_id = params['source_dependency']['id']
                entry['socket'] = socket_id
                if 'socket' in self.netlog and socket_id in self.netlog['socket']:
                    self.netlog['socket']['h2_session'] = session_id
        if 'host' not in entry and 'host' in params:
            entry['host'] = params['host']
        if 'protocol' not in entry and 'protocol' in params:
            entry['protocol'] = params['protocol']
        if 'stream_id' in params:
            stream_id = params['stream_id']
            if stream_id not in entry['stream']:
                entry['stream'][stream_id] = {'bytes_in': 0, 'chunks': []}
            stream = entry['stream'][stream_id]
            if 'exclusive' in params:
                stream['exclusive'] = params['exclusive']
            if 'parent_stream_id' in params:
                stream['parent_stream_id'] = params['parent_stream_id']
            if 'weight' in params:
                stream['weight'] = params['weight']
            if 'url' in params:
                stream['url'] = params['url'].split('#', 1)[0]
                if 'url_request' in stream:
                    request_id = stream['url_request']
                    if 'url_request' in self.netlog and request_id in self.netlog['url_request']:
                        request = self.netlog['url_request'][request_id]
                        request['url'] = params['url'].split('#', 1)[0]
            if name == 'HTTP2_SESSION_RECV_DATA' and 'size' in params:
                stream['end'] = event['time']
                if 'first_byte' not in stream:
                    stream['first_byte'] = event['time']
                stream['bytes_in'] += params['size']
                stream['chunks'].append({'ts': event['time'], 'bytes': params['size']})
            if name == 'HTTP2_SESSION_SEND_HEADERS':
                if 'start' not in stream:
                    stream['start'] = event['time']
                if 'headers' in params:
                    stream['request_headers'] = params['headers']
            if name == 'HTTP2_SESSION_RECV_HEADERS':
                if 'first_byte' not in stream:
                    stream['first_byte'] = event['time']
                stream['end'] = event['time']
                if 'headers' in params:
                    stream['response_headers'] = params['headers']
            if name == 'HTTP2_STREAM_ADOPTED_PUSH_STREAM' and 'url' in params and \
                    'url_request' in self.netlog:
                # Find the phantom request with the matching url and mark it
                url = params['url'].split('#', 1)[0]
                for request_id in self.netlog['url_request']:
                    request = self.netlog['url_request'][request_id]
                    if 'url' in request and url == request['url'] and 'start' not in request:
                        request['phantom'] = True
                        break
        if name == 'HTTP2_SESSION_RECV_PUSH_PROMISE' and 'promised_stream_id' in params:
            # Create a fake request to match the push
            if 'url_request' not in self.netlog:
                self.netlog['url_request'] = {}
            request_id = self.netlog['next_request_id']
            self.netlog['next_request_id'] += 1
            self.netlog['url_request'][request_id] = {'bytes_in': 0,
                                                      'chunks': [],
                                                      'created': event['time']}
            request = self.netlog['url_request'][request_id]
            stream_id = params['promised_stream_id']
            if stream_id not in entry['stream']:
                entry['stream'][stream_id] = {'bytes_in': 0, 'chunks': []}
            stream = entry['stream'][stream_id]
            if 'headers' in params:
                stream['request_headers'] = params['headers']
                # synthesize a URL from the request headers
                scheme = None
                authority = None
                path = None
                for header in params['headers']:
                    match = re.search(r':scheme: (.+)', header)
                    if match:
                        scheme = match.group(1)
                    match = re.search(r':authority: (.+)', header)
                    if match:
                        authority = match.group(1)
                    match = re.search(r':path: (.+)', header)
                    if match:
                        path = match.group(1)
                if scheme is not None and authority is not None and path is not None:
                    url = '{0}://{1}{2}'.format(scheme, authority, path).split('#', 1)[0]
                    request['url'] = url
                    stream['url'] = url
            request['protocol'] = 'HTTP/2'
            request['h2_session'] = session_id
            request['stream_id'] = stream_id
            request['start'] = event['time']
            request['pushed'] = True
            stream['pushed'] = True
            stream['url_request'] = request_id
            if 'socket' in entry:
                request['socket'] = entry['socket']
        if name == 'HTTP2_SESSION_RECV_SETTING' and 'id' in params and 'value' in params:
            setting_id = None
            match = re.search(r'\d+ \((.+)\)', params['id'])
            if match:
                setting_id = match.group(1)
                if 'server_settings' not in entry:
                    entry['server_settings'] = {}
                entry['server_settings'][setting_id] = params['value']

    def ProcessNetlogQuicSessionEvent(self, event):
        """Raw QUIC session information (linked to sockets and requests)"""
        if 'quic_session' not in self.netlog:
            self.netlog['quic_session'] = {}
        session_id = event['source']['id']
        if session_id not in self.netlog['quic_session']:
            self.netlog['quic_session'][session_id] = {'stream': {}}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['quic_session'][session_id]
        name = event['name']
        if 'host' not in entry and 'host' in params:
            entry['host'] = params['host']
        if 'port' not in entry and 'port' in params:
            entry['port'] = params['port']
        if 'version' not in entry and 'version' in params:
            entry['version'] = params['version']
        if 'peer_address' not in entry and 'peer_address' in params:
            entry['peer_address'] = params['peer_address']
        if 'self_address' not in entry and 'self_address' in params:
            entry['self_address'] = params['self_address']
        if name == 'QUIC_SESSION_PACKET_SENT' and 'connect_start' not in entry:
            entry['connect_start'] = event['time']
        if name == 'QUIC_SESSION_VERSION_NEGOTIATED' and 'connect_end' not in entry:
            entry['connect_end'] = event['time']
        if name == 'CERT_VERIFIER_REQUEST' and 'connect_end' in entry:
            if 'tls_start' not in entry:
                entry['tls_start'] = entry['connect_end']
            if 'tls_end' not in entry:
                entry['tls_end'] = event['time']
        if 'quic_stream_id' in params:
            stream_id = params['quic_stream_id']
            if stream_id not in entry['stream']:
                entry['stream'][stream_id] = {'bytes_in': 0, 'chunks': []}
            stream = entry['stream'][stream_id]
            if name == 'QUIC_CHROMIUM_CLIENT_STREAM_SEND_REQUEST_HEADERS':
                if 'start' not in stream:
                    stream['start'] = event['time']
                if 'headers' in params:
                    stream['request_headers'] = params['headers']
            if name == 'QUIC_CHROMIUM_CLIENT_STREAM_READ_RESPONSE_HEADERS':
                if 'first_byte' not in stream:
                    stream['first_byte'] = event['time']
                stream['end'] = event['time']
                if 'headers' in params:
                    stream['response_headers'] = params['headers']

    def ProcessNetlogDnsEvent(self, event):
        if 'dns' not in self.netlog:
            self.netlog['dns'] = {}
        request_id = event['source']['id']
        if request_id not in self.netlog['dns']:
            self.netlog['dns'][request_id] = {}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['dns'][request_id]
        name = event['name']
        if 'source_dependency' in params and 'id' in params['source_dependency']:
            parent_id = params['source_dependency']['id']
            if 'connect_job' in self.netlog and parent_id in self.netlog['connect_job']:
                self.netlog['connect_job'][parent_id]['dns'] = request_id
        if name == 'HOST_RESOLVER_IMPL_REQUEST' and 'phase' in event:
            if event['phase'] == 'PHASE_BEGIN':
                if 'start' not in entry or event['time'] < entry['source']['start']:
                    entry['start'] = event['time']
            if event['phase'] == 'PHASE_END':
                if 'end' not in entry or event['time'] > entry['end']:
                    entry['end'] = event['time']
        if 'start' not in entry and name == 'HOST_RESOLVER_IMPL_ATTEMPT_STARTED':
            entry['start'] = event['time']
        if name == 'HOST_RESOLVER_IMPL_ATTEMPT_FINISHED':
            entry['end'] = event['time']
        if name == 'HOST_RESOLVER_IMPL_CACHE_HIT':
            if 'end' not in entry or event['time'] > entry['end']:
                entry['end'] = event['time']
        if 'host' not in entry and 'host' in params:
            entry['host'] = params['host']
        if 'address_list' in params:
            entry['address_list'] = params['address_list']

    def ProcessNetlogSocketEvent(self, event):
        if 'socket' not in self.netlog:
            self.netlog['socket'] = {}
        request_id = event['source']['id']
        if request_id not in self.netlog['socket']:
            self.netlog['socket'][request_id] = {'bytes_out': 0, 'bytes_in': 0,
                                                 'chunks_out': [], 'chunks_in': []}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['socket'][request_id]
        name = event['name']
        if 'address' in params:
            entry['address'] = params['address']
        if 'source_address' in params:
            entry['source_address'] = params['source_address']
        if 'connect_start' not in entry and name == 'TCP_CONNECT_ATTEMPT' and \
                event['phase'] == 'PHASE_BEGIN':
            entry['connect_start'] = event['time']
        if name == 'TCP_CONNECT_ATTEMPT' and event['phase'] == 'PHASE_END':
            entry['connect_end'] = event['time']
        if name == 'SSL_CONNECT':
            if 'connect_end' not in entry:
                entry['connect_end'] = event['time']
            if 'ssl_start' not in entry and event['phase'] == 'PHASE_BEGIN':
                entry['ssl_start'] = event['time']
            if event['phase'] == 'PHASE_END':
                entry['ssl_end'] = event['time']
            if 'version' in params:
                entry['tls_version'] = params['version']
            if 'is_resumed' in params:
                entry['tls_resumed'] = params['is_resumed']
            if 'next_proto' in params:
                entry['tls_next_proto'] = params['next_proto']
            if 'cipher_suite' in params:
                entry['tls_cipher_suite'] = params['cipher_suite']
        if name == 'SOCKET_BYTES_SENT' and 'byte_count' in params:
            if 'connect_end' not in entry:
                entry['connect_end'] = event['time']
            entry['bytes_out'] += params['byte_count']
            entry['chunks_out'].append({'ts': event['time'], 'bytes': params['byte_count']})
        if name == 'SOCKET_BYTES_RECEIVED' and 'byte_count' in params:
            entry['bytes_in'] += params['byte_count']
            entry['chunks_in'].append({'ts': event['time'], 'bytes': params['byte_count']})
        if name == 'SSL_CERTIFICATES_RECEIVED' and 'certificates' in params:
            if 'certificates' not in entry:
                entry['certificates'] = []
            entry['certificates'].extend(params['certificates'])

    def ProcessNetlogUdpSocketEvent(self, event):
        if 'socket' not in self.netlog:
            self.netlog['socket'] = {}
        request_id = event['source']['id']
        if request_id not in self.netlog['socket']:
            self.netlog['socket'][request_id] = {'bytes_out': 0, 'bytes_in': 0,
                                                 'chunks_out': [], 'chunks_in': []}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['socket'][request_id]
        name = event['name']
        if name == 'UDP_CONNECT' and 'address' in params:
            entry['address'] = params['address']
        if name == 'UDP_LOCAL_ADDRESS' and 'address' in params:
            entry['source_address'] = params['address']
        if 'connect_start' not in entry and name == 'UDP_CONNECT' and \
                event['phase'] == 'PHASE_BEGIN':
            entry['connect_start'] = event['time']
        if name == 'UDP_CONNECT' and event['phase'] == 'PHASE_END':
            entry['connect_end'] = event['time']
        if name == 'UDP_BYTES_SENT' and 'byte_count' in params:
            entry['bytes_out'] += params['byte_count']
            entry['chunks_out'].append({'ts': event['time'], 'bytes': params['byte_count']})
        if name == 'UDP_BYTES_RECEIVED' and 'byte_count' in params:
            entry['bytes_in'] += params['byte_count']
            entry['chunks_in'].append({'ts': event['time'], 'bytes': params['byte_count']})

    def ProcessNetlogUrlRequestEvent(self, event):
        if 'url_request' not in self.netlog:
            self.netlog['url_request'] = {}
        request_id = event['source']['id']
        if request_id not in self.netlog['url_request']:
            self.netlog['url_request'][request_id] = {'bytes_in': 0,
                                                      'chunks': [],
                                                      'created': event['time']}
        params = event['params'] if 'params' in event else {}
        entry = self.netlog['url_request'][request_id]
        name = event['name']
        if 'priority' in params:
            entry['priority'] = params['priority']
        if 'method' in params:
            entry['method'] = params['method']
        if 'url' in params:
            entry['url'] = params['url'].split('#', 1)[0]
        if 'start' not in entry and name == 'HTTP_TRANSACTION_SEND_REQUEST':
            entry['start'] = event['time']
        if 'headers' in params and name == 'HTTP_TRANSACTION_SEND_REQUEST_HEADERS':
            entry['request_headers'] = params['headers']
            if 'line' in params:
                entry['line'] = params['line']
            if 'start' not in entry:
                entry['start'] = event['time']
        if 'headers' in params and name == 'HTTP_TRANSACTION_HTTP2_SEND_REQUEST_HEADERS':
            if isinstance(params['headers'], dict):
                entry['request_headers'] = []
                for key in params['headers']:
                    entry['request_headers'].append('{0}: {1}'.format(key, params['headers'][key]))
            else:
                entry['request_headers'] = params['headers']
            entry['protocol'] = 'HTTP/2'
            if 'line' in params:
                entry['line'] = params['line']
            if 'start' not in entry:
                entry['start'] = event['time']
        if 'headers' in params and name == 'HTTP_TRANSACTION_QUIC_SEND_REQUEST_HEADERS':
            if isinstance(params['headers'], dict):
                entry['request_headers'] = []
                for key in params['headers']:
                    entry['request_headers'].append('{0}: {1}'.format(key, params['headers'][key]))
            else:
                entry['request_headers'] = params['headers']
            if 'line' in params:
                entry['line'] = params['line']
            entry['protocol'] = 'QUIC'
            if 'start' not in entry:
                entry['start'] = event['time']
        if 'headers' in params and name == 'HTTP_TRANSACTION_READ_RESPONSE_HEADERS':
            entry['response_headers'] = params['headers']
            if 'first_byte' not in entry:
                entry['first_byte'] = event['time']
            entry['end'] = event['time']
        if 'headers' in params and name =='HTTP_TRANSACTION_READ_EARLY_HINTS_RESPONSE_HEADERS':
            entry['early_hints_headers'] = params['headers']
            entry['end'] = event['time']
        if 'byte_count' in params and name == 'URL_REQUEST_JOB_BYTES_READ':
            entry['has_raw_bytes'] = True
            entry['end'] = event['time']
            entry['bytes_in'] += params['byte_count']
            entry['chunks'].append({'ts': event['time'], 'bytes': params['byte_count']})
        if 'byte_count' in params and name == 'URL_REQUEST_JOB_FILTERED_BYTES_READ':
            entry['end'] = event['time']
            if 'uncompressed_bytes_in' not in entry:
                entry['uncompressed_bytes_in'] = 0
            entry['uncompressed_bytes_in'] += params['byte_count']
            if 'has_raw_bytes' not in entry or not entry['has_raw_bytes']:
                entry['bytes_in'] += params['byte_count']
                entry['chunks'].append({'ts': event['time'], 'bytes': params['byte_count']})
        if 'stream_id' in params:
            entry['stream_id'] = params['stream_id']
        if name == 'URL_REQUEST_REDIRECTED':
            new_id = self.netlog['next_request_id']
            self.netlog['next_request_id'] += 1
            self.netlog['url_request'][new_id] = entry
            del self.netlog['url_request'][request_id]
    
    def ProcessNetlogDiskCacheEvent(self, event):
        """Disk cache events"""
        if 'params' in event and 'key' in event['params']:
            url = event['params']['key']
            if 'urls' not in self.netlog:
                self.netlog['urls'] = {}
            if url not in self.netlog['urls']:
                self.netlog['urls'][url] = {'start': event['time']}

    ##########################################################################
    #   Output Logging
    ##########################################################################
    def write_json(self, out_file, json_data):
        """Write out one of the internal structures as a json blob"""
        try:
            _, ext = os.path.splitext(out_file)
            if ext.lower() == '.gz':
                with gzip.open(out_file, GZIP_TEXT) as f:
                    json.dump(json_data, f)
            else:
                with open(out_file, 'w') as f:
                    json.dump(json_data, f)
        except BaseException:
            logging.exception("Error writing to " + out_file)

    def write_netlog_requests(self, out_file):
        out = self.post_process_netlog_events()
        if out is not None:
            self.write_json(out_file, out)


##########################################################################
#   Main Entry Point
##########################################################################
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Chrome NetLog parser.',
                                     prog='netlog-parser')
    parser.add_argument('-v', '--verbose', action='count',
                        help="Increase verbosity (specify multiple times for more). -vvvv for full debug output.")
    parser.add_argument('-n', '--netlog', help="Input netlog details file.")
    parser.add_argument('-o', '--out', help="Output requests json file.")
    options, _ = parser.parse_known_args()

    # Set up logging
    log_level = logging.CRITICAL
    if options.verbose == 1:
        log_level = logging.ERROR
    elif options.verbose == 2:
        log_level = logging.WARNING
    elif options.verbose == 3:
        log_level = logging.INFO
    elif options.verbose >= 4:
        log_level = logging.DEBUG
    logging.basicConfig(
        level=log_level, format="%(asctime)s.%(msecs)03d - %(message)s", datefmt="%H:%M:%S")

    if not options.netlog: 
        parser.error("Input NetLog file is not specified.")

    if not options.out: 
        parser.error("Output requests json file is not specified.")

    start = time.time()

    netlog = NetLog()
    netlog.process_netlog(options.netlog) ## what happens if this fails?
    netlog.write_netlog_requests(options.out)
    pass

    end = time.time()
    elapsed = end - start
    logging.debug("Elapsed Time: {0:0.4f}".format(elapsed))

if '__main__' == __name__:
    #import cProfile
    #cProfile.run('main()', None, 2)
    main()
