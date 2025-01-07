# Copyright 2019 WebPageTest LLC.
# Copyright 2017 Google Inc.
# Use of this source code is governed by the Apache 2.0 license that can be
# found in the LICENSE file.
"""Base class support for browsers that speak the dev tools protocol"""
import glob
import gzip
import io
import logging
import os
import psutil
import re
import shutil
import subprocess
import sys
import threading
import time
if (sys.version_info >= (3, 0)):
    from time import monotonic
    from urllib.parse import urlsplit # pylint: disable=import-error
    unicode = str
    GZIP_TEXT = 'wt'
else:
    from monotonic import monotonic
    from urlparse import urlsplit # pylint: disable=import-error
    GZIP_TEXT = 'w'
try:
    import ujson as json
except BaseException:
    import json
from .optimization_checks import OptimizationChecks


class DevtoolsBrowser(object):
    """Devtools Browser base"""
    CONNECT_TIME_LIMIT = 120

    def __init__(self, options, job, use_devtools_video=True):
        self.options = options
        self.job = job
        self.devtools = None
        self.task = None
        self.event_name = None
        self.browser_version = None
        self.device_pixel_ratio = None
        self.use_devtools_video = use_devtools_video
        self.lighthouse_command = None
        self.devtools_screenshot = True
        self.support_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'support')
        self.script_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'js')

    def connect(self, task):
        """Connect to the dev tools interface"""
        ret = False
        from internal.devtools import DevTools
        self.devtools = DevTools(self.options, self.job, task, self.use_devtools_video)
        if task['running_lighthouse']:
            ret = self.devtools.wait_for_available(self.CONNECT_TIME_LIMIT)
        else:
            if self.devtools.connect(self.CONNECT_TIME_LIMIT):
                logging.debug("Devtools connected")
                ret = True
            else:
                task['error'] = "Error connecting to dev tools interface"
                logging.critical(task['error'])
                self.devtools = None
        return ret

    def disconnect(self):
        """Disconnect from dev tools"""
        if self.devtools is not None:
            # Always navigate to about:blank after finishing in case the tab is
            # remembered across sessions
            if self.task is not None and self.task['error'] is None:
                self.devtools.send_command('Page.navigate', {'url': 'about:blank'}, wait=True)
            self.devtools.close()
            self.devtools = None

    def prepare_browser(self, task):
        """Prepare the running browser (mobile emulation, UA string, etc"""
        if self.devtools is not None:
            # Figure out the native viewport size
            if not self.options.android:
                size = self.devtools.execute_js("[window.innerWidth, window.innerHeight]")
                if size is not None and len(size) == 2:
                    task['actual_viewport'] = {"width": size[0], "height": size[1]}
            # Get the native device pixel ratio
            if self.device_pixel_ratio is None:
                self.device_pixel_ratio = 1.0
                try:
                    ratio = self.devtools.execute_js('window.devicePixelRatio')
                    if ratio is not None:
                        self.device_pixel_ratio = max(1.0, float(ratio))
                except Exception:
                    pass
            # Clear the caches
            if not task['cached']:
                self.devtools.send_command("Network.clearBrowserCache", {},
                                           wait=True)
                self.devtools.send_command("Network.clearBrowserCookies", {},
                                           wait=True)

            # Mobile Emulation
            if not self.options.android and \
                    'mobile' in self.job and self.job['mobile'] and \
                    'width' in self.job and 'height' in self.job and \
                    'dpr' in self.job:
                width = int(re.search(r'\d+', str(self.job['width'])).group())
                height = int(re.search(r'\d+', str(self.job['height'])).group())
                self.devtools.send_command("Emulation.setDeviceMetricsOverride",
                                           {"width": width,
                                            "height": height,
                                            "screenWidth": width,
                                            "screenHeight": height,
                                            "scale": 1,
                                            "positionX": 0,
                                            "positionY": 0,
                                            "deviceScaleFactor": float(self.job['dpr']),
                                            "mobile": True,
                                            "screenOrientation":
                                                {"angle": 0, "type": "portraitPrimary"}},
                                           wait=True)
                self.devtools.send_command("Emulation.setTouchEmulationEnabled",
                                           {"enabled": True,
                                            "configuration": "mobile"},
                                           wait=True)
                self.devtools.send_command("Emulation.setScrollbarsHidden",
                                           {"hidden": True},
                                           wait=True)

            # DevTools-based CPU throttling for desktop and emulated mobile tests
            # This throttling should only be applied for lighthouse test runs where
            # a custom config path is not specified
            if not self.options.android and 'throttle_cpu' in self.job and\
                    (not task['running_lighthouse'] or not self.job['lighthouse_config']):
                logging.debug('DevTools CPU Throttle target: %0.3fx', self.job['throttle_cpu'])
                logging.debug('cpu_scale_multiplier: %0.3f, throttle_cpu_requested %0.3f, throttle_cpu: %0.3f', 
                    self.job['cpu_scale_multiplier'], self.job['throttle_cpu_requested'], self.job['throttle_cpu'])
                if self.job['throttle_cpu'] > 1:
                    self.devtools.send_command("Emulation.setCPUThrottlingRate",
                                                {"rate": self.job['throttle_cpu']},
                                                wait=True)

            # Location
            if 'lat' in self.job and 'lng' in self.job:
                try:
                    lat = float(str(self.job['lat']))
                    lng = float(str(self.job['lng']))
                    self.devtools.send_command(
                        'Emulation.setGeolocationOverride',
                        {'latitude': lat, 'longitude': lng,
                         'accuracy': 0})
                except Exception:
                    logging.exception('Error overriding location')

            # UA String
            ua_string = self.devtools.execute_js("navigator.userAgent")
            if ua_string is not None:
                match = re.search(r'Chrome\/(\d+\.\d+\.\d+\.\d+)', ua_string)
                if match:
                    self.browser_version = match.group(1)
            if 'uastring' in self.job:
                ua_string = self.job['uastring']
            if ua_string is not None and 'AppendUA' in task:
                ua_string += ' ' + task['AppendUA']
            if 'auto_mobile_ua' in self.job and self.job['auto_mobile_ua']:
                # Attempt to automatically convert a desktop user-agent string to mobile
                ua_string = re.sub(r'(Chrome\/\d+\.\d+\.\d+\.\d+)', r'\1 Mobile', ua_string)
            if ua_string is not None:
                self.job['user_agent_string'] = ua_string
            # Disable js
            if self.job['noscript']:
                self.devtools.send_command("Emulation.setScriptExecutionDisabled",
                                           {"value": True}, wait=True)
            self.devtools.prepare_browser()

    def on_start_recording(self, task):
        """Start recording"""
        task['page_data'] = {'date': time.time()}
        task['page_result'] = None
        task['run_start_time'] = monotonic()
        if self.browser_version is not None and 'browserVersion' not in task['page_data']:
            task['page_data']['browserVersion'] = self.browser_version
            task['page_data']['browser_version'] = self.browser_version
        if 'throttle_cpu' in self.job:
            task['page_data']['throttle_cpu_requested'] = self.job['throttle_cpu_requested']
#            if self.job['throttle_cpu'] > 1:
            task['page_data']['throttle_cpu'] = self.job['throttle_cpu']    # Save the calculated throttle (devtools clamps value to at least 1)

        # Debug data on host uptime and CPU
        # TODO (AD) Review applicability for mobile agents
        task['page_data']['debug'] = {}
        task['page_data']['debug']['uptime'] = time.time() - psutil.boot_time()
        task['page_data']['debug']['cpuFreq'] = psutil.cpu_freq(percpu=True)

        # Save count of total navigations (not just those we're recording)
        task['page_data']['debug']['rawNavigationCount'] = task['naive_navigation_count']

        if self.devtools is not None:
            self.devtools.start_recording()

    def on_stop_capture(self, task):
        """Do any quick work to stop things that are capturing data"""
        if self.devtools is not None:
            self.devtools.stop_capture()

    def on_stop_recording(self, task):
        """Stop recording"""
        if self.devtools is not None:
            self.devtools.collect_trace()
            if self.devtools_screenshot:
                if self.job['pngScreenShot']:
                    screen_shot = os.path.join(task['dir'],
                                               task['prefix'] + '_screen.png')
                    self.devtools.grab_screenshot(screen_shot, png=True)
                else:
                    screen_shot = os.path.join(task['dir'],
                                               task['prefix'] + '_screen.jpg')
                    self.devtools.grab_screenshot(screen_shot, png=False, resize=600)
            # Collect end of test data from the browser
            self.collect_browser_metrics(task)
            # Stop recording dev tools (which also collects the trace)
            self.devtools.stop_recording()

    def run_task(self, task):
        """Run an individual test"""
        if self.devtools is not None:
            self.task = task
            logging.debug("Running test")
            end_time = monotonic() + task['test_time_limit']
            task['current_step'] = 1
            recording = False
            while len(task['script']) and task['error'] is None and \
                    monotonic() < end_time:
                self.prepare_task(task)
                command = task['script'].pop(0)
                if not recording and command['record']:
                    recording = True
                    self.on_start_recording(task)
                self.process_command(command)
                if command['record']:
                    self.devtools.wait_for_page_load()
                    if not task['combine_steps'] or not len(task['script']):
                        self.on_stop_capture(task)
                        self.on_stop_recording(task)
                        recording = False
                        self.on_start_processing(task)
                        self.wait_for_processing(task)
                        self.process_devtools_requests(task)
                        self.step_complete(task) #pylint: disable=no-member
                        if task['log_data']:
                            # Move on to the next step
                            task['current_step'] += 1
                            self.event_name = None
                    task['navigated'] = True
            self.task = None

    def on_start_processing(self, task):
        """Start any processing of the captured data"""
        if task['log_data']:
            # Start the processing that can run in a background thread
            optimization = OptimizationChecks(self.job, task, self.get_requests(True))
            optimization.start()
            # Run the video post-processing
            if self.use_devtools_video and self.job['video']:
                self.process_video()
            # wait for the background optimization checks
            optimization.join()

    def wait_for_processing(self, task):
        """Wait for the background processing (if any)"""
        pass

    def execute_js(self, script):
        """Run javascipt"""
        ret = None
        if self.devtools is not None:
            ret = self.devtools.execute_js(script)
        return ret

    def prepare_task(self, task):
        """Format the file prefixes for multi-step testing"""
        if task['current_step'] == 1:
            task['prefix'] = task['task_prefix']
            task['video_subdirectory'] = task['task_video_prefix']
        else:
            task['prefix'] = '{0}_{1:d}'.format(task['task_prefix'], task['current_step'])
            task['video_subdirectory'] = '{0}_{1:d}'.format(task['task_video_prefix'],
                                                            task['current_step'])
        if task['video_subdirectory'] not in task['video_directories']:
            task['video_directories'].append(task['video_subdirectory'])
        if self.event_name is not None:
            task['step_name'] = self.event_name
        else:
            task['step_name'] = 'Step_{0:d}'.format(task['current_step'])

    def process_video(self):
        """Post process the video"""
        from internal.video_processing import VideoProcessing
        video = VideoProcessing(self.options, self.job, self.task)
        video.process()

    def process_devtools_requests(self, task):
        """Process the devtools log and pull out the requests information"""
        path_base = os.path.join(self.task['dir'], self.task['prefix'])
        devtools_file = path_base + '_devtools.json.gz'
        if os.path.isfile(devtools_file):
            from internal.support.devtools_parser import DevToolsParser
            out_file = path_base + '_devtools_requests.json.gz'
            options = {'devtools': devtools_file, 'cached': task['cached'], 'out': out_file}
            netlog = path_base + '_netlog_requests.json.gz'
            options['netlog'] = netlog if os.path.isfile(netlog) else None
            optimization = path_base + '_optimization.json.gz'
            options['optimization'] = optimization if os.path.isfile(optimization) else None
            user_timing = path_base + '_user_timing.json.gz'
            options['user'] = user_timing if os.path.isfile(user_timing) else None
            coverage = path_base + '_coverage.json.gz'
            options['coverage'] = coverage if os.path.isfile(coverage) else None
            cpu = path_base + '_timeline_cpu.json.gz'
            options['cpu'] = cpu if os.path.isfile(cpu) else None
            v8stats = path_base + '_v8stats.json.gz'
            options['v8stats'] = v8stats if os.path.isfile(v8stats) else None
            parser = DevToolsParser(options)
            parser.process()
            # Cleanup intermediate files that are not needed
            if 'debug' not in self.job or not self.job['debug']:
                if os.path.isfile(optimization):
                    os.remove(optimization)
                if os.path.isfile(coverage):
                    os.remove(coverage)
                if os.path.isfile(devtools_file):
                    os.remove(devtools_file)
            if 'page_data' in parser.result and 'result' in parser.result['page_data']:
                self.task['page_result'] = parser.result['page_data']['result']

    def run_js_file(self, file_name):
        """Execute one of our js scripts"""
        ret = None
        script = None
        script_file_path = os.path.join(self.script_dir, file_name)
        if os.path.isfile(script_file_path):
            with io.open(script_file_path, 'r', encoding='utf-8') as script_file:
                script = script_file.read()
        if script is not None:
            ret = self.devtools.execute_js(script)
        return ret

    def strip_non_text(self, data):
        """Strip any non-text fields"""
        if isinstance(data, dict):
            for key in data:
                entry = data[key]
                if isinstance(entry, dict) or isinstance(entry, list):
                    self.strip_non_text(entry)
                elif isinstance(entry, str) or isinstance(entry, unicode):
                    try:
                        if (sys.version_info >= (3, 0)):
                            entry.encode('utf-8').decode('utf-8')
                        else:
                            entry.decode('utf-8')
                    except Exception:
                        data[key] = None
                elif isinstance(entry, bytes):
                    try:
                        data[key] = str(entry.decode('utf-8'))
                    except Exception:
                        data[key] = None
        elif isinstance(data, list):
            for key in range(len(data)):
                entry = data[key]
                if isinstance(entry, dict) or isinstance(entry, list):
                    self.strip_non_text(entry)
                elif isinstance(entry, str) or isinstance(entry, unicode):
                    try:
                        if (sys.version_info >= (3, 0)):
                            entry.encode('utf-8').decode('utf-8')
                        else:
                            entry.decode('utf-8')
                    except Exception:
                        data[key] = None
                elif isinstance(entry, bytes):
                    try:
                        data[key] = str(entry.decode('utf-8'))
                    except Exception:
                        data[key] = None


    def get_sorted_requests_json(self, include_bodies):
        requests_json = None
        try:
            requests = []
            raw_requests = self.get_requests(include_bodies)
            for request_id in raw_requests:
                self.strip_non_text(raw_requests[request_id])
                requests.append(raw_requests[request_id])
            requests = sorted(requests, key=lambda request: request['sequence'])
            requests_json = json.dumps(requests)
        except Exception:
            logging.exception('Error getting json request data')
        if requests_json is None:
            requests_json = 'null'
        return requests_json

    def collect_browser_metrics(self, task):
        """Collect all of the in-page browser metrics that we need"""
        user_timing = self.run_js_file('user_timing.js')
        if user_timing is not None:
            path = os.path.join(task['dir'], task['prefix'] + '_timed_events.json.gz')
            with gzip.open(path, GZIP_TEXT, 7) as outfile:
                outfile.write(json.dumps(user_timing))
        page_data = self.run_js_file('page_data.js')
        if page_data is not None:
            task['page_data'].update(page_data)
        if 'customMetrics' in self.job:
            custom_metrics = {}
            requests = None
            bodies = None
            for name in self.job['customMetrics']:
                custom_script = unicode(self.job['customMetrics'][name])
                if custom_script.find('$WPT_REQUESTS') >= 0:
                    if requests is None:
                        requests = self.get_sorted_requests_json(False)
                    try:
                        custom_script = custom_script.replace('$WPT_REQUESTS', requests)
                    except Exception:
                        logging.exception('Error substituting request data into custom script')
                if custom_script.find('$WPT_BODIES') >= 0:
                    if bodies is None:
                        bodies = self.get_sorted_requests_json(True)
                    try:
                        custom_script = custom_script.replace('$WPT_BODIES', bodies)
                    except Exception:
                        logging.exception('Error substituting request data with bodies into custom script')
                script = 'var wptCustomMetric = function() {' + custom_script + '};try{wptCustomMetric();}catch(e){};'
                custom_metrics[name] = self.devtools.execute_js(script)
            path = os.path.join(task['dir'], task['prefix'] + '_metrics.json.gz')
            with gzip.open(path, GZIP_TEXT, 7) as outfile:
                outfile.write(json.dumps(custom_metrics))
        if 'heroElementTimes' in self.job and self.job['heroElementTimes']:
            hero_elements = None
            custom_hero_selectors = {}
            if 'heroElements' in self.job:
                custom_hero_selectors = self.job['heroElements']
            with io.open(os.path.join(self.script_dir, 'hero_elements.js'), 'r', encoding='utf-8') as script_file:
                hero_elements_script = script_file.read()
            script = hero_elements_script + '(' + json.dumps(custom_hero_selectors) + ')'
            hero_elements = self.devtools.execute_js(script)
            if hero_elements is not None:
                logging.debug('Hero Elements: %s', json.dumps(hero_elements))
                path = os.path.join(task['dir'], task['prefix'] + '_hero_elements.json.gz')
                with gzip.open(path, GZIP_TEXT, 7) as outfile:
                    outfile.write(json.dumps(hero_elements))


    def process_command(self, command):
        """Process an individual script command"""
        logging.debug("Processing script command:")
        logging.debug(command)
        if command['command'] == 'navigate':
            self.task['page_data']['URL'] = command['target']
            url = str(command['target']).replace('"', '\"')
            script = 'window.location="{0}";'.format(url)
            script = self.prepare_script_for_record(script) #pylint: disable=no-member
            # Set up permissions for the origin
            try:
                parts = urlsplit(url)
                origin = parts.scheme + '://' + parts.netloc
                self.devtools.send_command('Browser.grantPermissions',
                                        {'origin': origin,
                                        'permissions': ['geolocation',
                                                        'videoCapture',
                                                        'audioCapture',
                                                        'sensors',
                                                        'idleDetection',
                                                        'wakeLockScreen']},
                                        wait=True)
            except Exception:
                logging.exception('Error setting permissions for origin')
            self.devtools.start_navigating()
            self.devtools.execute_js(script)
        elif command['command'] == 'logdata':
            self.task['combine_steps'] = False
            if int(re.search(r'\d+', str(command['target'])).group()):
                logging.debug("Data logging enabled")
                self.task['log_data'] = True
            else:
                logging.debug("Data logging disabled")
                self.task['log_data'] = False
        elif command['command'] == 'combinesteps':
            self.task['log_data'] = True
            self.task['combine_steps'] = True
        elif command['command'] == 'seteventname':
            self.event_name = command['target']
        elif command['command'] == 'exec':
            script = command['target']
            if command['record']:
                needs_mark = True
                if self.task['combine_steps']:
                    needs_mark = False
                script = self.prepare_script_for_record(script, needs_mark) #pylint: disable=no-member
                self.devtools.start_navigating()
            result = self.devtools.execute_js(script)
            logging.debug(result)
        elif command['command'] == 'sleep':
            delay = min(60, max(0, int(re.search(r'\d+', str(command['target'])).group())))
            if delay > 0:
                time.sleep(delay)
        elif command['command'] == 'setabm':
            self.task['stop_at_onload'] = bool('target' in command and
                                               int(re.search(r'\d+',
                                                             str(command['target'])).group()) == 0)
        elif command['command'] == 'setactivitytimeout':
            if 'target' in command:
                milliseconds = int(re.search(r'\d+', str(command['target'])).group())
                self.task['activity_time'] = max(0, min(30, float(milliseconds) / 1000.0))
        elif command['command'] == 'setminimumstepseconds':
            self.task['minimumTestSeconds'] = int(re.search(r'\d+', str(command['target'])).group())
        elif command['command'] == 'setuseragent':
            self.task['user_agent_string'] = command['target']
        elif command['command'] == 'setcookie':
            if 'target' in command and 'value' in command:
                try:
                    url = command['target'].strip()
                    cookie = command['value']
                    pos = cookie.find(';')
                    if pos > 0:
                        cookie = cookie[:pos]
                    pos = cookie.find('=')
                    if pos > 0:
                        name = cookie[:pos].strip()
                        value = cookie[pos + 1:].strip()
                        if len(name) and len(value) and len(url):
                            self.devtools.send_command('Network.setCookie',
                                                    {'url': url, 'name': name, 'value': value})
                except Exception:
                    logging.exception('Error setting cookie')
        elif command['command'] == 'setlocation':
            try:
                if 'target' in command and command['target'].find(',') > 0:
                    accuracy = 0
                    if 'value' in command and re.match(r'\d+', command['value']):
                        accuracy = int(re.search(r'\d+', str(command['value'])).group())
                    parts = command['target'].split(',')
                    lat = float(parts[0])
                    lng = float(parts[1])
                    self.devtools.send_command(
                        'Emulation.setGeolocationOverride',
                        {'latitude': lat, 'longitude': lng,
                         'accuracy': accuracy})
            except Exception:
                logging.exception('Error setting location')
        elif command['command'] == 'addheader':
            self.devtools.set_header(command['target'], command['value'])
        elif command['command'] == 'setheader':
            self.devtools.set_header(command['target'], command['value'])
        elif command['command'] == 'resetheaders':
            self.devtools.reset_headers()
        elif command['command'] == 'clearcache':
            self.devtools.clear_cache()
        elif command['command'] == 'disablecache':
            disable_cache = bool('target' in command and \
                                 int(re.search(r'\d+',
                                               str(command['target'])).group()) == 1)
            self.devtools.disable_cache(disable_cache)
        elif command['command'] == 'injectscript':
            self.devtools.add_post_navigation_script(command['target'])

    def navigate(self, url):
        """Navigate to the given URL"""
        if self.devtools is not None:
            self.devtools.send_command('Page.navigate', {'url': url}, wait=True)

    def get_requests(self, include_bodies):
        """Get the request details for running an optimization check"""
        requests = None
        if self.devtools is not None:
            requests = self.devtools.get_requests(include_bodies)
        return requests

    def lighthouse_thread(self):
        """Run lighthouse in a thread so we can kill it if it times out"""
        cmd = self.lighthouse_command
        self.task['lighthouse_log'] = cmd + "\n"
        logging.debug(cmd)
        proc = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE)
        for line in iter(proc.stderr.readline, b''):
            try:
                line = unicode(line,errors='ignore')
                logging.debug(line.rstrip())
                self.task['lighthouse_log'] += line
            except Exception:
                logging.exception('Error recording lighthouse log line %s', line.rstrip())
        proc.communicate()

    def run_lighthouse_test(self, task):
        """Run a lighthouse test against the current browser session"""
        task['lighthouse_log'] = ''
        if 'url' in self.job and self.job['url'] is not None:
            output_path = os.path.join(task['dir'], 'lighthouse.json')
            json_file = os.path.join(task['dir'], 'lighthouse.report.json')
            json_gzip = os.path.join(task['dir'], 'lighthouse.json.gz')
            html_file = os.path.join(task['dir'], 'lighthouse.report.html')
            html_gzip = os.path.join(task['dir'], 'lighthouse.html.gz')
            time_limit = 120
            command = ['lighthouse',
                       '"{0}"'.format(self.job['url']),
                       '--channel', 'wpt',
                       '--enable-error-reporting',
                       '--max-wait-for-load', str(int(time_limit * 1000)),
                       '--port', str(task['port']),
                       '--output', 'html',
                       '--output', 'json',
                       '--output-path', '"{0}"'.format(output_path)]
            if self.job['lighthouse_config']:
                # When a config path is provided, delegate all emulation and throttling to the config
                try:
                    lighthouse_config_file = os.path.join(task['dir'], 'lighthouse-config.json')
                    with open(lighthouse_config_file, 'wt') as f_out:
                        json.dump(json.loads(self.job['lighthouse_config']), f_out)
                    command.extend(['--config-path', lighthouse_config_file])
                except Exception:
                    logging.exception('Error adding custom config for lighthouse test')
            else:
                if not self.options.android and ('mobile' not in self.job or not self.job['mobile']):
                    command.extend(['--preset', 'desktop'])
            if self.options.android:
                command.extend(['--form-factor', 'mobile', '--screenEmulation.disabled'])
            if self.job['keep_lighthouse_trace']:
                command.append('--save-assets')
            if not self.job['keep_lighthouse_screenshots']:
                command.extend(['--skip-audits', 'screenshot-thumbnails'])
            if 'user_agent_string' in self.job:
                sanitized_user_agent = re.sub(r'[^a-zA-Z0-9_\-.;:/()\[\] ]+', '', self.job['user_agent_string'])
                command.extend(['--emulatedUserAgent', "'{0}'".format(sanitized_user_agent)])
            if len(task['block']):
                for pattern in task['block']:
                    command.extend(['--blocked-url-patterns', "'{0}'".format(pattern.replace("'", "'\\''"))])
            if 'headers' in task:
                try:
                    headers_file = os.path.join(task['dir'], 'lighthouse-headers.json')
                    with open(headers_file, 'wt') as f_out:
                        json.dump(task['headers'], f_out)
                    command.extend(['--extra-headers', '"{0}"'.format(headers_file)])
                except Exception:
                    logging.exception('Error adding custom headers for lighthouse test')
            cmd = ' '.join(command)
            self.lighthouse_command = cmd
            # Give lighthouse up to 10 minutes to run all of the audits
            try:
                lh_thread = threading.Thread(target=self.lighthouse_thread)
                lh_thread.start()
                lh_thread.join(600)
            except Exception:
                logging.exception('Error running lighthouse audits')
            from .os_util import kill_all
            kill_all('node', True)
            # Rename and compress the trace file, delete the other assets
            if self.job['keep_lighthouse_trace']:
                try:
                    lh_trace_src = os.path.join(task['dir'], 'lighthouse-0.trace.json')
                    if os.path.isfile(lh_trace_src):
                        # read the JSON in and re-write it line by line to match the other traces
                        with io.open(lh_trace_src, 'r', encoding='utf-8') as f_in:
                            trace = json.load(f_in)
                            if trace is not None and 'traceEvents' in trace:
                                lighthouse_trace = os.path.join(task['dir'],
                                                                'lighthouse_trace.json.gz')
                            with gzip.open(lighthouse_trace, GZIP_TEXT, 7) as f_out:
                                f_out.write('{"traceEvents":[{}')
                                for trace_event in trace['traceEvents']:
                                    f_out.write(",\n")
                                    f_out.write(json.dumps(trace_event))
                                f_out.write("\n]}")
                except Exception:
                    logging.exception('Error processing lighthouse trace')
            # Delete all the left-over lighthouse assets
            files = glob.glob(os.path.join(task['dir'], 'lighthouse-*'))
            for file_path in files:
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            if os.path.isfile(json_file):
                lh_report = None
                with io.open(json_file, 'r', encoding='utf-8') as f_in:
                    lh_report = json.load(f_in)

                with open(json_file, 'rb') as f_in:
                    with gzip.open(json_gzip, 'wb', 7) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                try:
                    os.remove(json_file)
                except Exception:
                    pass
                # Extract the audit scores
                if lh_report is not None:
                    audits = {}
                    # v1.x
                    if 'aggregations' in lh_report:
                        for entry in lh_report['aggregations']:
                            if 'name' in entry and 'total' in entry and \
                                    'scored' in entry and entry['scored']:
                                name = entry['name'].replace(' ', '')
                                audits[name] = entry['total']
                    # v2.x
                    elif 'reportCategories' in lh_report:
                        for category in lh_report['reportCategories']:
                            if 'name' in category and 'score' in category:
                                category_name = category['name'].replace(' ', '')
                                score = float(category['score']) / 100.0
                                audits[category_name] = score
                                if category['name'] == 'Performance' and 'audits' in category:
                                    for audit in category['audits']:
                                        if 'id' in audit and 'group' in audit and \
                                                audit['group'] == 'perf-metric' and \
                                                'result' in audit and \
                                                'rawValue' in audit['result']:
                                            name = category_name + '.' + \
                                                audit['id'].replace(' ', '')
                                            audits[name] = audit['result']['rawValue']
                    # v3.x
                    elif 'categories' in lh_report:
                        for categoryId in lh_report['categories']:
                            category = lh_report['categories'][categoryId]
                            if 'title' not in category or 'score' not in category:
                                continue

                            category_title = category['title'].replace(' ', '')
                            audits[category_title] = category['score']

                            if categoryId != 'performance' or 'auditRefs' not in category:
                                continue

                            for auditRef in category['auditRefs']:
                                if auditRef['id'] not in lh_report['audits']:
                                    continue
                                if 'group' not in auditRef or auditRef['group'] != 'metrics':
                                    continue
                                audit = lh_report['audits'][auditRef['id']]
                                name = category_title + '.' + audit['id']
                                if 'rawValue' in audit:
                                    audits[name] = audit['rawValue']
                                elif 'numericValue' in audit:
                                    audits[name] = audit['numericValue']
                    audits_gzip = os.path.join(task['dir'], 'lighthouse_audits.json.gz')
                    with gzip.open(audits_gzip, GZIP_TEXT, 7) as f_out:
                        json.dump(audits, f_out)
            # Compress the HTML lighthouse report
            if os.path.isfile(html_file):
                try:
                    with open(html_file, 'rb') as f_in:
                        with gzip.open(html_gzip, 'wb', 7) as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    os.remove(html_file)
                except Exception:
                    logging.exception('Error compressing lighthouse report')
