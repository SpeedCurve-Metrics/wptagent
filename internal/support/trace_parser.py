#!/usr/bin/env python3
"""
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
import math
import os
import re
import time
from urllib.parse import urlparse # pylint: disable=import-error

# try a fast json parser if it is installed
try:
    import ujson as json
except BaseException:
    import json

##########################################################################
#   Trace processing
##########################################################################
class Trace():
    """Main class"""
    def __init__(self):
        self.thread_stack = {}
        self.ignore_threads = {}
        self.threads = {}
        self.user_timing = []
        self.event_names = {}
        self.event_name_lookup = {}
        self.scripts = None
        self.timeline_events = []
        self.trace_events = []
        self.interactive = []
        self.long_tasks = []
        self.interactive_start = 0
        self.interactive_end = None
        self.start_time = None
        self.marked_start_time = None
        self.end_time = None
        self.cpu = {'main_thread': None, 'main_threads':[], 'subframes': []}
        self.feature_usage = None
        self.feature_usage_start_time = None
        self.v8stats = None
        self.v8stack = {}
        return

    ##########################################################################
    #   Output Logging
    ##########################################################################
    def write_json(self, out_file, json_data):
        """Write out one of the internal structures as a json blob"""
        try:
            _, ext = os.path.splitext(out_file)
            if ext.lower() == '.gz':
                with gzip.open(out_file, 'wt') as f:
                    json.dump(json_data, f)
            else:
                with open(out_file, 'w') as f: # TODO (AD) Should this be wt?
                    json.dump(json_data, f)
        except BaseException:
            logging.exception("Error writing to " + out_file)

    def WriteUserTiming(self, out_file):
        out = self.post_process_user_timing()
        if out is not None:
            self.write_json(out_file, out)

    def WriteCPUSlices(self, out_file):
        self.write_json(out_file, self.cpu)

    def WriteScriptTimings(self, out_file):
        if self.scripts is not None:
            self.write_json(out_file, self.scripts)

    def WriteFeatureUsage(self, out_file):
        pass
#        out = self.post_process_feature_usage()
#        if out is not None:
#            self.write_json(out_file, out)

    def WriteInteractive(self, out_file):
        # Generate the interactive periods from the long-task data
        if self.end_time and self.start_time:
            interactive = []
            end_time = int(math.ceil(float(self.end_time - self.start_time) / 1000.0))
            if not self.long_tasks:
                interactive.append([0, end_time])
            else:
                last_end = 0
                for task in self.long_tasks:
                    elapsed = task[0] - last_end
                    if elapsed > 0:
                        interactive.append([last_end, task[0]])
                    last_end = task[1]
                elapsed = end_time - last_end
                if elapsed > 0:
                    interactive.append([last_end, end_time])
            self.write_json(out_file, interactive)
    
    def WriteLongTasks(self, out_file):
        self.write_json(out_file, self.long_tasks)

    def WriteV8Stats(self, out_file):
        if self.v8stats is not None:
            self.v8stats["main_thread"] = self.cpu['main_thread']
            self.v8stats["main_threads"] = self.cpu['main_threads']
            self.write_json(out_file, self.v8stats)

    ##########################################################################
    #   Top-level processing
    ##########################################################################
    def Process(self, trace):
        f = None
        line_mode = False
        self.__init__()
        logging.debug("Loading trace: %s", trace)
        try:
            _, ext = os.path.splitext(trace)
            if ext.lower() == '.gz':
                f = gzip.open(trace, 'rt')
            else:
                f = open(trace, 'r') # TODO (AD) Should this be rt?
            for line in f:
                try:
                    trace_event = json.loads(line.strip("\r\n\t ,"))
                    if not line_mode and 'traceEvents' in trace_event:
                        for sub_event in trace_event['traceEvents']:
                            self.FilterTraceEvent(sub_event)
                    else:
                        line_mode = True
                        self.FilterTraceEvent(trace_event)
                except BaseException:
                    logging.exception('Error processing trace line')
        except BaseException:
            logging.exception("Error processing trace " + trace)
        if f is not None:
            f.close()
        self.ProcessTraceEvents()

    def ProcessTimeline(self, timeline):
        self.__init__()
        self.cpu['main_thread'] = '0'
        self.threads['0'] = {}
        events = None
        f = None
        try:
            _, ext = os.path.splitext(timeline)
            if ext.lower() == '.gz':
                f = gzip.open(timeline, 'rt')
            else:
                f = open(timeline, 'r') # TODO (AD) Should this be rt?
            events = json.load(f)
            if events:
                # convert the old format timeline events into our internal
                # representation
                for event in events:
                    if 'method' in event and 'params' in event:
                        if self.start_time is None:
                            if event['method'] == 'Network.requestWillBeSent' and \
                                    'timestamp' in event['params']:
                                self.start_time = event['params']['timestamp'] * 1000000.0
                                self.end_time = event['params']['timestamp'] * 1000000.0
                        else:
                            if 'timestamp' in event['params']:
                                t = event['params']['timestamp'] * 1000000.0
                                if t > self.end_time:
                                    self.end_time = t
                            if event['method'] == 'Timeline.eventRecorded' and \
                                    'record' in event['params']:
                                e = self.ProcessOldTimelineEvent(
                                    event['params']['record'], None)
                                if e is not None:
                                    self.timeline_events.append(e)
                self.ProcessTimelineEvents()
        except BaseException:
            logging.exception("Error processing timeline " + timeline)
        if f is not None:
            f.close()

    def FilterTraceEvent(self, trace_event):
        cat = trace_event['cat']
        if cat == 'toplevel' or cat == 'ipc,toplevel':
            return
        if cat == 'devtools.timeline' or \
                cat == '__metadata' or \
                cat.find('devtools.timeline') >= 0 or \
                cat.find('blink.feature_usage') >= 0 or \
                cat.find('blink.user_timing') >= 0 or \
                cat.find('loading') >= 0 or \
                cat.find('navigation') >= 0 or \
                cat.find('rail') >= 0 or \
                cat.find('netlog') >= 0 or \
                cat.find('v8') >= 0:
            self.trace_events.append(trace_event)

    def ProcessTraceEvents(self):
        # sort the raw trace events by timestamp and then process them
        if len(self.trace_events):
            logging.debug("Sorting %d trace events", len(self.trace_events))
            self.trace_events.sort(key=lambda trace_event: trace_event['ts'])
            logging.debug("Processing trace events")
            for trace_event in self.trace_events:
                self.ProcessTraceEvent(trace_event)
            self.trace_events = []
 
        logging.debug("Processing timeline events")
        self.ProcessTimelineEvents()
        logging.debug("Done processing trace events")      

    def ProcessTraceEvent(self, trace_event):
        cat = trace_event['cat']
        if 'ts' in trace_event:
            trace_event['ts'] = int(trace_event['ts'])
        if cat.find('blink.user_timing') >= 0 or cat.find('rail') >= 0 or \
                cat.find('loading') >= 0 or cat.find('navigation') >= 0:
            keep = False
            if 'args' in trace_event and \
                    'data' in trace_event['args'] and \
                    'inMainFrame' in trace_event['args']['data'] and \
                    trace_event['args']['data']['inMainFrame']:
                keep = True
            elif 'args' in trace_event and 'frame' in trace_event['args']:
                keep = True
            elif 'name' in trace_event and trace_event['name'] in [
                    'navigationStart', 'unloadEventStart', 'redirectStart', 'domLoading']:
                keep = True
            if keep:
                self.user_timing.append(trace_event)
            if self.marked_start_time is None and \
                    'name' in trace_event and \
                    trace_event['name'].find('navigationStart') >= 0:
                if self.start_time is None or trace_event['ts'] < self.start_time:
                    self.start_time = trace_event['ts']
            if self.cpu['main_thread'] is None and 'name' in trace_event and \
                    trace_event['name'] in ['navigationStart', 'fetchStart']:
                thread = '{0}:{1}'.format(trace_event['pid'], trace_event['tid'])
                self.cpu['main_thread'] = thread
                if thread not in self.cpu['main_threads']:
                    self.cpu['main_threads'].append(thread)
            if 'args' in trace_event and \
                    'data' in trace_event['args'] and \
                    'inMainFrame' in trace_event['args']['data'] and \
                    trace_event['args']['data']['inMainFrame']:
                thread = '{0}:{1}'.format(trace_event['pid'], trace_event['tid'])
                if thread not in self.cpu['main_threads']:
                    self.cpu['main_threads'].append(thread)
        if cat == '__metadata' and 'name' in trace_event and \
                trace_event['name'] == 'process_labels' and \
                'pid' in trace_event and 'args' in trace_event and \
                'labels' in trace_event['args'] and \
                trace_event['args']['labels'].startswith('Subframe:'):
            self.cpu['subframes'].append(str(trace_event['pid']))
        if cat == '__metadata' and 'name' in trace_event and \
                trace_event['name'] == 'thread_name' and \
                'args' in trace_event and \
                'name' in trace_event['args'] and \
                trace_event['args']['name'] == 'CrRendererMain':
            thread = '{0}:{1}'.format(trace_event['pid'], trace_event['tid'])
            if thread not in self.cpu['main_threads']:
                self.cpu['main_threads'].append(thread)
        elif cat == 'devtools.timeline' or cat.find('devtools.timeline') >= 0:
            self.ProcessTimelineTraceEvent(trace_event)
        if cat.find('v8') >= 0:
            self.ProcessV8Event(trace_event)
    
    def post_process_user_timing(self):
        out = None
        if self.user_timing is not None:
            self.user_timing.sort(key=lambda trace_event: trace_event['ts'])
            out = []
            candidates = {}
            lcp_event = None
            for event in self.user_timing:
                try:
                    consumed = False
                    if event['cat'].find('loading') >= 0 and 'name' in event:
                        if event['name'].startswith('NavStartToLargestContentfulPaint'):
                            consumed = True
                            if event['name'].find('Invalidate') >= 0:
                                lcp_event = None
                            elif event['name'].find('Candidate') >= 0:
                                lcp_event = dict(event)
                        elif event['name'].find('::') >= 0:
                            consumed = True
                            (name, trigger) = event['name'].split('::', 1)
                            name = name[:1].upper() + name[1:]
                            event['name'] = name
                            key = name
                            try:
                                if 'args' in event:
                                    if 'frame' in event['args']:
                                        key += ':' + event['args']['frame']
                                    if 'data' in event['args'] and 'candidateIndex' in event['args']['data']:
                                        if isinstance(event['args']['data']['candidateIndex'], int):
                                            key += '.{0:d}'.format(event['args']['data']['candidateIndex'])
                                        elif isinstance(event['args']['data']['candidateIndex'], str):
                                            key += '.' + event['args']['data']['candidateIndex']
                            except Exception:
                                logging.exception('Error processing user timing event key')
                            if trigger == 'Candidate':
                                candidates[key] = dict(event)
                            elif trigger == 'Invalidate' and key in candidates:
                                del candidates[key]
                    if not consumed:
                        out.append(event)
                except Exception:
                    logging.exception('Error processing user timing event')
            has_lcp = False
            for name in candidates:
                if name.startswith('LargestContentfulPaint'):
                    has_lcp = True
                    break
            if lcp_event is not None and not has_lcp:
                lcp_event['name'] = 'LargestContentfulPaint'
                out.append(lcp_event)
            for name in candidates:
                out.append(candidates[name])
            out.append({'startTime': self.start_time})
        return out

    ##########################################################################
    #   Timeline
    ##########################################################################
    def ProcessTimelineTraceEvent(self, trace_event):
        thread = '{0}:{1}'.format(trace_event['pid'], trace_event['tid'])
        if trace_event['name'] == 'thread_name' and \
                'args' in trace_event and \
                'name' in trace_event['args'] and \
                trace_event['args']['name'] == 'CrRendererMain' and \
                thread not in self.cpu['main_threads']:
            self.cpu['main_threads'].append(thread)
        
        # Watch for the marker indicating the start time
        if trace_event['name'] == 'ResourceSendRequest' and \
                'args' in trace_event and \
                'data' in trace_event['args'] and \
                'url' in trace_event['args']['data'] and \
                trace_event['args']['data']['url'] == 'http://127.0.0.1:8888/wpt-start-recording':
            self.marked_start_time = trace_event['ts']
            self.start_time = trace_event['ts']

        # Keep track of the main thread
        if 'args' in trace_event and 'data' in trace_event['args'] and \
                thread not in self.ignore_threads:
            if 'url' in trace_event['args']['data'] and \
                    trace_event['args']['data']['url'].startswith('http://127.0.0.1:8888'):
                self.ignore_threads[thread] = True
            if self.cpu['main_thread'] is None or 'isMainFrame' in trace_event['args']['data']:
                if ('isMainFrame' in trace_event['args']['data'] and \
                     trace_event['args']['data']['isMainFrame']) or \
                   (trace_event['name'] == 'ResourceSendRequest' and \
                    'url' in trace_event['args']['data']):
                    if thread not in self.threads:
                        self.threads[thread] = {}
                    if self.marked_start_time is None:
                        if self.start_time is None or trace_event['ts'] < self.start_time:
                            self.start_time = trace_event['ts']
                    self.cpu['main_thread'] = thread
                    if thread not in self.cpu['main_threads']:
                        self.cpu['main_threads'].append(thread)
                    if 'dur' not in trace_event:
                        trace_event['dur'] = 1

        # Make sure each thread has a numerical ID
        if self.cpu['main_thread'] is not None and \
                thread not in self.threads and \
                thread not in self.ignore_threads and \
                trace_event['name'] != 'Program':
            self.threads[thread] = {}

        # Build timeline events on a stack. 'B' begins an event, 'E' ends an
        # event
        if (thread in self.threads and (
                'dur' in trace_event or trace_event['ph'] == 'B' or trace_event['ph'] == 'E')):
            trace_event['thread'] = self.threads[thread]
            if thread not in self.thread_stack:
                self.thread_stack[thread] = []
            if trace_event['name'] not in self.event_names:
                self.event_names[trace_event['name']] = len(self.event_names)
                self.event_name_lookup[self.event_names[trace_event['name']]] = trace_event['name']
            if trace_event['name'] not in self.threads[thread]:
                self.threads[thread][trace_event['name']] = self.event_names[trace_event['name']]
            e = None
            if trace_event['ph'] == 'E':
                if len(self.thread_stack[thread]) > 0:
                    e = self.thread_stack[thread].pop()
                    if e['n'] == self.event_names[trace_event['name']]:
                        e['e'] = trace_event['ts']
            else:
                e = {'t': thread, 'n': self.event_names[trace_event['name']], 's': trace_event['ts']}
                if trace_event['name'] in ['EvaluateScript', 'v8.compile', 'v8.parseOnBackground'] and \
                        'args' in trace_event and 'data' in trace_event['args'] and \
                        'url' in trace_event['args']['data'] and \
                        trace_event['args']['data']['url'].startswith('http'):
                    e['js'] = trace_event['args']['data']['url']
                if trace_event['name'] == 'FunctionCall' and 'args' in trace_event and 'data' in trace_event['args']:
                    if 'scriptName' in trace_event['args']['data'] and trace_event['args']['data']['scriptName'].startswith(
                            'http'):
                        e['js'] = trace_event['args']['data']['scriptName']
                    elif 'url' in trace_event['args']['data'] and trace_event['args']['data']['url'].startswith('http'):
                        e['js'] = trace_event['args']['data']['url'].split('#', 1)[0]
                if trace_event['ph'] == 'B':
                    self.thread_stack[thread].append(e)
                    e = None
                elif 'dur' in trace_event:
                    e['e'] = e['s'] + trace_event['dur']

            if e is not None and 'e' in e and e['s'] >= self.start_time and e['e'] >= e['s']:
                if self.end_time is None or e['e'] > self.end_time:
                    self.end_time = e['e']
                # attach it to a parent event if there is one
                if len(self.thread_stack[thread]) > 0:
                    parent = self.thread_stack[thread].pop()
                    if 'c' not in parent:
                        parent['c'] = []
                    parent['c'].append(e)
                    self.thread_stack[thread].append(parent)
                else:
                    self.timeline_events.append(e)

    def ProcessOldTimelineEvent(self, event, type):
        e = None
        thread = '0'
        if 'type' in event:
            type = event['type']
        if type not in self.event_names:
            self.event_names[type] = len(self.event_names)
            self.event_name_lookup[self.event_names[type]] = type
        if type not in self.threads[thread]:
            self.threads[thread][type] = self.event_names[type]
        start = None
        end = None
        if 'startTime' in event and 'endTime' in event:
            start = event['startTime'] * 1000000.0
            end = event['endTime'] * 1000000.0
        if 'callInfo' in event:
            if 'startTime' in event['callInfo'] and 'endTime' in event['callInfo']:
                start = event['callInfo']['startTime'] * 1000000.0
                end = event['callInfo']['endTime'] * 1000000.0
        if start is not None and end is not None and end >= start and type is not None:
            if end > self.end_time:
                self.end_time = end
            e = {'t': thread,
                 'n': self.event_names[type], 's': start, 'e': end}
            if 'callInfo' in event and 'url' in event and event['url'].startswith(
                    'http'):
                e['js'] = event['url'].split('#', 1)[0]
            elif 'data' in event and 'url' in event['data'] and \
                    event['data']['url'].startswith('http'):
                e['js'] = event['data']['url'].split('#', 1)[0]
            elif 'data' in event and 'scriptName' in event['data'] and \
                    event['data']['scriptName'].startswith('http'):
                e['js'] = event['data']['scriptName'].split('#', 1)[0]
            elif 'stackTrace' in event and event['stackTrace']:
                for stack_frame in event['stackTrace']:
                    if 'url' in stack_frame and stack_frame['url'].startswith('http'):
                        e['js'] = stack_frame['url'].split('#', 1)[0]
                        break
            # Process profile child events
            if 'data' in event and 'profile' in event['data'] and 'rootNodes' in event['data']['profile']:
                for child in event['data']['profile']['rootNodes']:
                    c = self.ProcessOldTimelineEvent(child, type)
                    if c is not None:
                        if 'c' not in e:
                            e['c'] = []
                        e['c'].append(c)
            # recursively process any child events
            if 'children' in event:
                for child in event['children']:
                    c = self.ProcessOldTimelineEvent(child, type)
                    if c is not None:
                        if 'c' not in e:
                            e['c'] = []
                        e['c'].append(c)
        return e

    def ProcessTimelineEvents(self):
        if len(self.timeline_events) and self.end_time > self.start_time:
            # Figure out how big each slice should be in usecs. Size it to a
            # power of 10 where we have at least 2000 slices
            exp = 0
            last_exp = 0
            slice_count = self.end_time - self.start_time
            while slice_count > 2000:
                last_exp = exp
                exp += 1
                slice_count = int(
                    math.ceil(float(self.end_time - self.start_time) / float(pow(10, exp))))
            self.cpu['total_usecs'] = self.end_time - self.start_time
            self.cpu['slice_usecs'] = int(pow(10, last_exp))
            slice_count = int(math.ceil(
                float(self.end_time - self.start_time) / float(self.cpu['slice_usecs'])))

            # Create the empty time slices for all of the threads
            self.cpu['slices'] = {}
            for thread in list(self.threads.keys()):
                self.cpu['slices'][thread] = {'total': [0.0] * slice_count}
                for name in list(self.threads[thread].keys()):
                    self.cpu['slices'][thread][name] = [0.0] * slice_count

            # Go through all of the timeline events recursively and account for
            # the time they consumed
            for timeline_event in self.timeline_events:
                self.ProcessTimelineEvent(timeline_event, None)
            if self.interactive_end is not None and self.interactive_end - \
                    self.interactive_start > 500000:
                self.interactive.append([int(math.ceil(self.interactive_start / 1000.0)),
                                         int(math.floor(self.interactive_end / 1000.0))])

            # Go through all of the fractional times and convert the float
            # fractional times to integer usecs
            for thread in list(self.cpu['slices'].keys()):
                del self.cpu['slices'][thread]['total']
                for name in list(self.cpu['slices'][thread].keys()):
                    for slice in range(len(self.cpu['slices'][thread][name])):
                        self.cpu['slices'][thread][name][slice] =\
                            int(self.cpu['slices'][thread][name]
                                [slice] * self.cpu['slice_usecs'])

            # Pick the candidate main thread with the most activity
            main_threads = list(self.cpu['main_threads'])
            if len(main_threads) == 0:
                main_threads = list(self.cpu['slices'].keys())
            main_thread = None
            main_thread_cpu = 0
            for thread in main_threads:
                try:
                    thread_cpu = 0
                    if thread in self.cpu['slices']:
                        for name in list(self.cpu['slices'][thread].keys()):
                            for slice in range(len(self.cpu['slices'][thread][name])):
                                thread_cpu += self.cpu['slices'][thread][name][slice]
                        if main_thread is None or thread_cpu > main_thread_cpu:
                            main_thread = thread
                            main_thread_cpu = thread_cpu
                except Exception:
                    logging.exception('Error processing thread')
            if main_thread is not None:
                self.cpu['main_thread'] = main_thread

    def ProcessTimelineEvent(self, timeline_event, parent, stack=None):
        start = timeline_event['s'] - self.start_time
        end = timeline_event['e'] - self.start_time
        if stack is None:
            stack = {}
        if end > start:
            elapsed = end - start
            thread = timeline_event['t']
            name = self.event_name_lookup[timeline_event['n']]

            # Keep track of periods on the main thread where at least 500ms are
            # available with no tasks longer than 50ms
            if 'main_thread' in self.cpu and thread == self.cpu['main_thread']:
                if elapsed > 50000:
                    if start - self.interactive_start > 500000:
                        self.interactive.append(
                            [int(math.ceil(self.interactive_start / 1000.0)),
                             int(math.floor(start / 1000.0))])
                    self.interactive_start = end
                    self.interactive_end = None
                else:
                    self.interactive_end = end
            
            # Keep track of the long-duration top-level tasks
            if parent is None and elapsed > 50000 and thread in self.cpu['main_threads']:
                # make sure this isn't contained within an existing event
                ms_start = int(math.floor(start / 1000.0))
                ms_end = int(math.ceil(end / 1000.0))
                if not self.long_tasks:
                    # Empty list of long tasks
                    self.long_tasks.append([ms_start, ms_end])
                else:
                    last_start = self.long_tasks[-1][0]
                    last_end = self.long_tasks[-1][1]
                    if ms_start >= last_end:
                        # This task is entirely after the last long task we know about
                        self.long_tasks.append([ms_start, ms_end])
                    elif ms_end > last_end:
                        # task extends beyond the previous end of the long tasks but overlaps
                        del self.long_tasks[-1]
                        if ms_start >= last_start:
                            self.long_tasks.append([last_start, ms_end])
                        else:
                            self.long_tasks.append([ms_start, ms_end])

            if 'js' in timeline_event:
                script = timeline_event['js']
                js_start = start / 1000.0
                js_end = end / 1000.0
                if self.scripts is None:
                    self.scripts = {}
                if 'main_thread' not in self.scripts and 'main_thread' in self.cpu:
                    self.scripts['main_thread'] = self.cpu['main_thread']
                if thread not in self.scripts:
                    self.scripts[thread] = {}
                if script not in self.scripts[thread]:
                    self.scripts[thread][script] = {}
                if name not in self.scripts[thread][script]:
                    self.scripts[thread][script][name] = []
                if thread not in stack:
                    stack[thread] = {}
                if script not in stack[thread]:
                    stack[thread][script] = {}
                if name not in stack[thread][script]:
                    stack[thread][script][name] = []
                # make sure the script duration isn't already covered by a
                # parent event
                new_duration = True
                if len(stack[thread][script][name]):
                    for period in stack[thread][script][name]:
                        if len(period) >= 2 and js_start >= period[0] and js_end <= period[1]:
                            new_duration = False
                            break
                if new_duration:
                    self.scripts[thread][script][name].append([js_start, js_end])
                    stack[thread][script][name].append([js_start, js_end])

            slice_usecs = self.cpu['slice_usecs']
            first_slice = int(float(start) / float(slice_usecs))
            last_slice = int(float(end) / float(slice_usecs))
            for slice_number in range(first_slice, last_slice + 1):
                slice_start = slice_number * slice_usecs
                slice_end = slice_start + slice_usecs
                used_start = max(slice_start, start)
                used_end = min(slice_end, end)
                slice_elapsed = used_end - used_start
                self.AdjustTimelineSlice(
                    thread, slice_number, name, parent, slice_elapsed)

            # Recursively process any child events
            if 'c' in timeline_event:
                for child in timeline_event['c']:
                    self.ProcessTimelineEvent(child, name, dict(stack))

    # Add the time to the given slice and subtract the time from a parent event
    def AdjustTimelineSlice(self, thread, slice_number, name, parent, elapsed):
        try:
            # Don't bother adjusting if both the current event and parent are the same category
            # since they would just cancel each other out.
            if name != parent:
                fraction = min(1.0, float(elapsed) /
                               float(self.cpu['slice_usecs']))
                self.cpu['slices'][thread][name][slice_number] += fraction
                self.cpu['slices'][thread]['total'][slice_number] += fraction
                if parent is not None and \
                        self.cpu['slices'][thread][parent][slice_number] >= fraction:
                    self.cpu['slices'][thread][parent][slice_number] -= fraction
                    self.cpu['slices'][thread]['total'][slice_number] -= fraction
                # Make sure we didn't exceed 100% in this slice
                self.cpu['slices'][thread][name][slice_number] = min(
                    1.0, self.cpu['slices'][thread][name][slice_number])

                # make sure we don't exceed 100% for any slot
                if self.cpu['slices'][thread]['total'][slice_number] > 1.0:
                    available = max(0.0, 1.0 - fraction)
                    for slice_name in list(self.cpu['slices'][thread].keys()):
                        if slice_name != name:
                            self.cpu['slices'][thread][slice_name][slice_number] =\
                                min(self.cpu['slices'][thread]
                                    [slice_name][slice_number], available)
                            available = max(0.0, available - \
                                            self.cpu['slices'][thread][slice_name][slice_number])
                    self.cpu['slices'][thread]['total'][slice_number] = min(
                        1.0, max(0.0, 1.0 - available))
        except BaseException:
            logging.exception('Error adjusting timeline slice')


    #######################################################################
    #   V8 call stats
    #######################################################################
    def ProcessV8Event(self, trace_event):
        try:
            if self.start_time is not None and self.cpu['main_thread'] is not None and trace_event['ts'] >= self.start_time and \
                    "name" in trace_event:
                thread = '{0}:{1}'.format(
                    trace_event['pid'], trace_event['tid'])
                if trace_event["ph"] == "B":
                    if thread not in self.v8stack:
                        self.v8stack[thread] = []
                    self.v8stack[thread].append(trace_event)
                else:
                    duration = 0.0
                    if trace_event["ph"] == "E" and thread in self.v8stack:
                        start_event = self.v8stack[thread].pop()
                        if start_event['name'] == trace_event['name'] and 'ts' in start_event and start_event['ts'] <= trace_event['ts']:
                            duration = trace_event['ts'] - start_event['ts']
                    elif trace_event['ph'] == 'X' and 'dur' in trace_event:
                        duration = trace_event['dur']
                    if self.v8stats is None:
                        self.v8stats = {'threads': {}}
                    if thread not in self.v8stats['threads']:
                        self.v8stats['threads'][thread] = {}
                    name = trace_event["name"]
                    if name not in self.v8stats['threads'][thread]:
                        self.v8stats['threads'][thread][name] = {"dur": 0.0, "count": 0}
                    self.v8stats['threads'][thread][name]['dur'] += float(duration) / 1000.0
                    self.v8stats['threads'][thread][name]['count'] += 1
                    if 'args' in trace_event and 'runtime-call-stats' in trace_event["args"]:
                        for stat in trace_event["args"]["runtime-call-stats"]:
                            if len(trace_event["args"]["runtime-call-stats"][stat]) == 2:
                                if 'breakdown' not in self.v8stats['threads'][thread][name]:
                                    self.v8stats['threads'][thread][name]['breakdown'] = {}
                                if stat not in self.v8stats['threads'][thread][name]['breakdown']:
                                    self.v8stats['threads'][thread][name]['breakdown'][stat] = {"count": 0, "dur": 0.0}
                                self.v8stats['threads'][thread][name]['breakdown'][stat]["count"] += int(trace_event["args"]["runtime-call-stats"][stat][0])
                                self.v8stats['threads'][thread][name]['breakdown'][stat]["dur"] += float(trace_event["args"]["runtime-call-stats"][stat][1]) / 1000.0
        except BaseException:
            logging.exception('Error processing V8 event')


##########################################################################
#   Main Entry Point
##########################################################################
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Chrome trace parser.',
                                     prog='trace-parser')
    parser.add_argument('-v', '--verbose', action='count',
                        help="Increase verbosity (specify multiple times for more). -vvvv for full debug output.")
    parser.add_argument('-t', '--trace', help="Input trace file.")
    parser.add_argument('-l', '--timeline',
                        help="Input timeline file (iOS or really old Chrome).")
    parser.add_argument('-c', '--cpu', help="Output CPU time slices file.")
    parser.add_argument(
        '-j', '--js', help="Output Javascript per-script parse/evaluate/execute timings.")
    parser.add_argument('-u', '--user', help="Output user timing file.")
    parser.add_argument('-i', '--interactive',
                        help="Output list of interactive times.")
    parser.add_argument('-x', '--longtasks', help="Output list of long main thread task times.")
    parser.add_argument('-s', '--stats', help="Output v8 Call stats file.")
    options, _ = parser.parse_known_args()

    # Set up logging
    log_level = logging.CRITICAL
  
    match options.verbose:
        case 1:
            log_level = logging.ERROR
        case 2:
            log_level = logging.WARNING
        case 3:
            log_level = logging.INFO 
        case 4:
            log_level = logging.DEBUG
            
    logging.basicConfig(level=log_level, format="%(asctime)s.%(msecs)03d - %(message)s", datefmt="%H:%M:%S")

    # Check trace or timeline file is specified
    if not options.trace and not options.timeline:
        parser.error("Input trace or timeline file is not specified.")

    start = time.time()
    trace = Trace()
    if options.trace:
        trace.Process(options.trace)
    elif options.timeline:
        trace.ProcessTimeline(options.timeline)

    if options.user:
        trace.WriteUserTiming(options.user)

    if options.cpu:
        trace.WriteCPUSlices(options.cpu)

    if options.js:
        trace.WriteScriptTimings(options.js)

    if options.interactive:
        trace.WriteInteractive(options.interactive)
    
    if options.longtasks:
        trace.WriteLongTasks(options.longtasks)

    if options.stats:
        trace.WriteV8Stats(options.stats)

    end = time.time()
    elapsed = end - start
    logging.debug("Elapsed Time: {0:0.4f}".format(elapsed))

if '__main__' == __name__:
    #import cProfile
    #cProfile.run('main()', None, 2)
    main()
