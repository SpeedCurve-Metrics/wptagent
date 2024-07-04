# Copyright 2019 WebPageTest LLC.
# Copyright 2017 Google Inc.
# Use of this source code is governed by the Apache 2.0 license that can be
# found in the LICENSE file.
"""Logic for controlling a desktop Chrome browser"""
import gzip
import logging
import os
import platform
import subprocess
import shutil
import threading
import time
import sys
from .desktop_browser import DesktopBrowser
from .devtools_browser import DevtoolsBrowser
from .support.netlog_parser import NetLogParser

# try a fast json parser if it is installed
try:
    import ujson as json
except BaseException:
    import json

if (sys.version_info >= (3, 0)):
    from urllib.parse import urlparse # pylint: disable=import-error
    str = str
    GZIP_TEXT = 'wt'
    GZIP_READ_TEXT = 'rt'
else:
    from urllib.parse import urlparse # pylint: disable=import-error
    GZIP_TEXT = 'w'
    GZIP_READ_TEXT = 'r'


#
# Where possible prefer Chrome switches over blocking URLs
# e.g. disable AutofillServerCommunication over blocking content-autofill.googleapis.com
#
# Recommended flags: https://github.com/GoogleChrome/chrome-launcher/blob/main/docs/chrome-flags-for-tools.md
# Chrome CLI switches: http://peter.sh/experiments/chromium-command-line-switches/
# Chromium Feature switches: https://niek.github.io/chrome-features/
# Blink Feature switches: https://source.chromium.org/chromium/chromium/src/+/main:out/Debug/gen/third_party/blink/renderer/platform/runtime_enabled_features.cc
#
# TODO (AD) Review current switches against Paul's recommendations

CHROME_COMMAND_LINE_OPTIONS = [
    '--allow-running-insecure-content',
    '--ash-no-nudges',
    '--enable-automation',
    '--disable-background-networking',
    '--disable-backgrounding-occluded-windows',
    '--disable-background-timer-throttling',
    '--disable-breakpad',
    '--disable-client-side-phishing-detection',
    '--disable-component-extensions-with-background-pages',  # Stops Network Translate and Chat extensions
    '--disable-component-update',
    '--disable-default-apps',
    '--disable-domain-reliability',
    '--disable-fetching-hints-at-navigation-start',
    '--disable-gaia-services',
    '--disable-hang-monitor',
    '--disable-notifications',
    '--disable-prompt-on-repost',
    '--disable-renderer-backgrounding',
    '--disable-site-isolation-trials',
    '--disable-sync',
    '--load-media-router-component-extension=0',
    '--metrics-recording-only',
    '--mute-audio',
    '--net-log-capture-mode=IncludeSensitive',
    '--new-window',
    '--no-default-browser-check',
    '--no-first-run',
    '--password-store=basic'
]

HOST_RULES = [
    '"MAP cache.pack.google.com 127.0.0.1"',
    '"MAP clients1.google.com 127.0.0.1"',
    '"MAP redirector.gvt1.com 127.0.0.1"',
    '"MAP optimizationguide-pa.googleapis.com 127.0.0.1"',
    '"MAP offlinepages-pa.googleapis.com 127.0.0.1"',
    '"MAP update.googleapis.com 127.0.0.1"',
    '"MAP content-autofill.googleapis.com 127.0.0.1"'
]

ENABLE_CHROME_FEATURES = [
    'NetworkService',
    'NetworkServiceInProcess',
    'SecMetadata'
]

DISABLE_CHROME_FEATURES = [
    'AutofillServerCommunication',
    'CalculateNativeWinOcclusion',
    'ChromeWhatsNewUI',
    'HeavyAdPrivacyMitigations',
    'InterestFeedContentSuggestions',
    'MediaRouter',
    'OfflinePagesPrefetching',
    'OptimizationHints',
    'SidePanelPinning',
    'Translate'
]

ENABLE_BLINK_FEATURES = [
    'LayoutInstabilityAPI'
]

class ChromeDesktop(DesktopBrowser, DevtoolsBrowser):
    """Desktop Chrome"""
    def __init__(self, path, options, job):
        self.options = options
        DesktopBrowser.__init__(self, path, options, job)
        use_devtools_video = True if self.job['capture_display'] is None else False
        DevtoolsBrowser.__init__(self, options, job, use_devtools_video=use_devtools_video)
        self.start_page = 'http://127.0.0.1:8888/orange.html'
        self.connected = False
        self.is_chrome = True

        # TODO (AD) Review
        self.netlog_pipe = None
        self.netlog_in = None
        self.netlog_file = None
        self.netlog_out = None

        self.netlog_lock = threading.Lock()
        self.netlog_thread = None
        self.netlog = None

    def launch(self, job, task):
        """Launch the browser"""
        self.install_policy()
        args = list(CHROME_COMMAND_LINE_OPTIONS)
        features = list(ENABLE_CHROME_FEATURES)
        disable_features = list(DISABLE_CHROME_FEATURES)
        host_rules = list(HOST_RULES)
        if 'host_rules' in task:
            host_rules.extend(task['host_rules'])
        args.append('--host-resolver-rules=' + ','.join(host_rules))
        args.extend(['--window-position="0,0"',
                     '--window-size="{0:d},{1:d}"'.format(task['width'], task['height'])])
        args.append('--remote-debugging-port={0:d}'.format(task['port']))
        args.append('--remote-allow-origins=*')
        if 'ignoreSSL' in job and job['ignoreSSL']:
            args.append('--ignore-certificate-errors')

    # TODO (AD) Review

        streamed_netlog = False

        if platform.system() in ["Linux", "Darwin"]:
            self.netlog_pipe = os.path.join(task['dir'], 'netlog.pipe')
            try:            
                # Make a pipe and set it as the sink for Chrome netlog events
                os.mkfifo(self.netlog_pipe)
                args.append('--log-net-log="{0}"'.format(self.netlog_pipe))
                streamed_netlog = True

                # Process stream on a separate thread
                self.netlog_thread = threading.Thread(target=self.process_netlog_stream)
                self.netlog_thread.start()

                self.netlog = NetLogParser()

            except Exception:
                logging.exception('Error creating pipe for NetLog')

        # If we need to keep the netlog create file to write it to
        # TODO (AD) Stop doing this for lighthouse runs
        if 'netlog' in job and job['netlog']:
            self.netlog_file = os.path.join(task['dir'], task['prefix']) + '_netlog.txt'
            self.netlog_out = open(self.netlog_file, 'wb')

            if not streamed_netlog:
                args.append('--log-net-log="{0}"'.format(self.netlog_file))

        if 'profile' in task:
            args.append('--user-data-dir="{0}"'.format(task['profile']))
            self.setup_prefs(task['profile'])
        if self.options.xvfb:
            args.append('--disable-gpu')
        if self.options.dockerized:
            args.append('--no-sandbox')
        if platform.system() == "Linux":
            args.append('--disable-setuid-sandbox')
        args.append('--enable-features=' + ','.join(features))
        args.append('--enable-blink-features=' + ','.join(ENABLE_BLINK_FEATURES))

        # Disable site isolation if emulating mobile. It is disabled on
        # actual mobile Chrome (and breaks Chrome's CPU throttling)
        if 'mobile' in job and job['mobile']:
            disable_features.extend(['IsolateOrigins',
                                     'site-per-process'])
        elif 'throttle_cpu' in self.job and self.job['throttle_cpu'] > 1:
            disable_features.extend(['IsolateOrigins',
                                     'site-per-process'])
        args.append('--disable-features=' + ','.join(disable_features))

        if self.path.find(' ') > -1:
            command_line = '"{0}"'.format(self.path)
        else:
            command_line = self.path
        command_line += ' ' + ' '.join(args)
        if 'addCmdLine' in job:
            command_line += ' ' + job['addCmdLine']
        command_line += ' ' + 'about:blank'
        # re-try launching and connecting a few times if necessary
        connected = False
        count = 0
        while not connected and count < 3:
            count += 1
            DesktopBrowser.launch_browser(self, command_line)
            if DevtoolsBrowser.connect(self, task):
                connected = True
            elif count < 3:
                DesktopBrowser.stop(self, job, task)
                if 'error' in task and task['error'] is not None:
                    task['error'] = None
                # try launching the browser with no command-line options to
                # do any one-time startup initialization
                if count == 1:
                    bare_options = ['--disable-gpu']
                    if self.options.dockerized:
                        bare_options.append('--no-sandbox')
                    if platform.system() == "Linux":
                        bare_options.append('--disable-setuid-sandbox')
                    logging.debug('Launching browser with no options for configuration')
                    relaunch = '"{0}"'.format(self.path) + ' ' + ' '.join(bare_options)
                    DesktopBrowser.launch_browser(self, relaunch)
                    time.sleep(30)
                    DesktopBrowser.stop(self, job, task)
                time.sleep(10)
        if connected:
            self.connected = True
            DesktopBrowser.wait_for_idle(self)
            DevtoolsBrowser.prepare_browser(self, task)
            DevtoolsBrowser.navigate(self, self.start_page)
            # When throttling the CPU, Chrome sits in a busy loop so ony apply a short idle wait
            DesktopBrowser.wait_for_idle(self, 2)

    def run_task(self, task):
        """Run an individual test"""
        if self.connected:
            DevtoolsBrowser.run_task(self, task)

    def execute_js(self, script):
        """Run javascipt"""
        return DevtoolsBrowser.execute_js(self, script)

# TODO (AD) Review
    def process_netlog_stream(self):
        """Read the netlog pipe in a background thread"""

        logging.debug('process_netlog_stream entry')

        with self.netlog_lock:
            self.netlog_in = open(self.netlog_pipe, 'r')

        if self.netlog_in:
            logging.debug('Netlog pipe connected...')

# TODO (AD) This is a variation of the code in netlog_parser, is it possible to merge them?
            processing_events = False
            for line in self.netlog_in:

                # Save a copy of the netlog if we need to
                with self.netlog_lock:
                    if self.netlog_out:
                        self.netlog_out.write(line)

                try:
                    line = line.strip(', \r\n')
                    with self.netlog_lock:
                        if processing_events:
                            if self.recording and line.startswith('{'):
                                if self.netlog:
                                    event = json.loads(line)
                                    self.netlog.process_event(event)
                        elif line.startswith('{"constants":'):
                            if self.netlog:
                                raw = json.loads(line + '}')
                                if raw and 'constants' in raw:
                                    self.netlog.process_constants(raw['constants'])
                        elif line.startswith('"events": ['):
                            processing_events = True
                except Exception as error:
                    logging.exception('Error processing netlog: ' + line)
                    logging.exception(error)

        logging.debug('process_netlog_stream exit')


# Called at end of each run
    def stop(self, job, task):
        if self.connected:
            DevtoolsBrowser.disconnect(self)

        # Stop processing NetLog and clean up
        if self.netlog_thread is not None:
            try:
                self.netlog_thread.join(60)
            except Exception:
                logging.exception('Error terminating NetLog Parsing thread')
        self.netlog_thread = None

        # Close file that reads pipe when the netlog thread has completed
        with self.netlog_lock:
            try:
                if self.netlog_in is not None:
                    self.netlog_in.close()
            except Exception:
                logging.exception('Error closing NetLog file')
            self.netlog_in = None
            

        if self.netlog_pipe is not None:
            try:
                os.unlink(self.netlog_pipe)
            except Exception:
                logging.debug('Error closing netlog pipe')
            self.netlog_pipe = None

        if self.netlog_file and os.path.isfile(self.netlog_file):
            logging.debug('Compressing netlog')
            netlog_gzip = self.netlog_file + '.gz'
            with open(self.netlog_file, 'rb') as f_in:
                with gzip.open(netlog_gzip, 'wb', 7) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            if os.path.isfile(netlog_gzip):
                os.remove(self.netlog_file)

        self.netlog = None

        # Stop the browser after the netlog thread completes to prevent netlog truncation
        DesktopBrowser.stop(self, job, task)

        # Make SURE the chrome processes are gone 
        # TODO (AD) add Darwin check here too?
        if platform.system() == "Linux":
            subprocess.call(['killall', '-9', 'chrome'])


        self.remove_policy()

    def setup_prefs(self, profile_dir):
        """Install our base set of preferences"""
        src = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                           'support', 'chrome', 'prefs.json')
        dest_dir = os.path.join(profile_dir, 'Default')
        try:
            os.makedirs(dest_dir)
            shutil.copy(src, os.path.join(dest_dir, 'Preferences'))
        except Exception:
            logging.exception('Error copying prefs file')

    def install_policy(self):
        """Install the required policy list (Linux only right now)"""
        if platform.system() == "Linux":
            subprocess.call(['sudo', 'mkdir', '-p', '/etc/opt/chrome/policies/managed'])
            subprocess.call(['sudo', 'chmod', '-w', '/etc/opt/chrome/policies/managed'])
            subprocess.call(['sudo', 'mkdir', '-p', '/etc/chromium/policies/managed'])
            subprocess.call(['sudo', 'chmod', '-w', '/etc/chromium/policies/managed'])
            src = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                               'support', 'chrome', 'wpt_policy.json')
            subprocess.call(['sudo', 'cp', src,
                             '/etc/opt/chrome/policies/managed/wpt_policy.json'])
            subprocess.call(['sudo', 'cp', src,
                             '/etc/chromium/policies/managed/wpt_policy.json'])

    def remove_policy(self):
        """Remove the installed policy"""
        if platform.system() == "Linux":
            subprocess.call(['sudo', 'rm', '/etc/opt/chrome/policies/managed/wpt_policy.json'])
            subprocess.call(['sudo', 'rm', '/etc/chromium/policies/managed/wpt_policy.json'])

    def on_start_recording(self, task):
        """Notification that we are about to start an operation that needs to be recorded"""
        DesktopBrowser.on_start_recording(self, task)

        # Remove exisiting requests in NetLog Parser (need to keep constants for parsing future events)
        with self.netlog_lock:
            self.netlog.clear_requests();

        DevtoolsBrowser.on_start_recording(self, task)

    def on_stop_capture(self, task):
        """Do any quick work to stop things that are capturing data"""
        DesktopBrowser.on_stop_capture(self, task)
        DevtoolsBrowser.on_stop_capture(self, task)

    def on_stop_recording(self, task):
        """Notification that we are about to start an operation that needs to be recorded"""

        logging.debug('on_stop_recording')

        DesktopBrowser.on_stop_recording(self, task)

        # Write out the netlog requests for this step
        with self.netlog_lock:
            if self.netlog:
                netlog_requests = os.path.join(task['dir'], task['prefix']) + '_netlog_requests.json.gz'
                logging.debug('Writing ' + netlog_requests)
                self.netlog.write_netlog_requests(netlog_requests)

        DevtoolsBrowser.on_stop_recording(self, task)

    def on_start_processing(self, task):
        """Start any processing of the captured data"""
        DesktopBrowser.on_start_processing(self, task)
        DevtoolsBrowser.on_start_processing(self, task)

    def wait_for_processing(self, task):
        """Wait for any background processing threads to finish"""
        DevtoolsBrowser.wait_for_processing(self, task)
        DesktopBrowser.wait_for_processing(self, task)
