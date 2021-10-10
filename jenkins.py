#!/usr/bin/env python3
# Run Jenkins job, retrieve build artifacts and save them to local file system

__author__ = "Mads Meisner-Jensen"
import os
import sys
import argparse
import time
import datetime
import requests
import threading
import traceback
import configparser
import xml.dom.minidom as minidom
import urllib
from requests.auth import HTTPBasicAuth
from pathlib import Path
from pprint import pprint, pformat


#####################################################################
# Helpers
#####################################################################

import collections

Color = collections.namedtuple('Color', "reset black red green yellow blue magenta cyan white grey ired igreen iyellow iblue imagenta icyan iwhite")
Color.__new__.__defaults__ = ("",) * len(Color._fields)
Style = collections.namedtuple('Color', "bold dim under inv")
Style.__new__.__defaults__ = ("",) * len(Style._fields)
fg = Color()
style = Style()

ColorLog = collections.namedtuple('ColorLog', "send recv info note progress error warn")
ColorLog.__new__.__defaults__ = ("",) * len(ColorLog._fields)
color = ColorLog()

def color_enable(force=False):
    global fg, style, color
    if force or (sys.stdout.isatty() and os.name != 'nt'):
        fg = Color(reset="\033[0m",black="\033[30m",red="\033[31m",green="\033[32m",yellow="\033[33m",blue="\033[34m",magenta="\033[35m",cyan="\033[36m",white="\033[37m",
                   grey="\033[90m",ired="\033[91m",igreen="\033[92m",iyellow="\033[93m",iblue="\033[94m",imagenta="\033[95m",icyan="\033[96m",iwhite="\033[97m")
        style = Style(bold="\033[1m", dim="\033[2m", under="\033[4m", inv="\033[7m")

        color = ColorLog(
            send = fg.igreen,
            recv = fg.green,
            info = fg.white + style.bold,
            note=fg.iyellow,
            progress = fg.white + style.dim,
            error=fg.ired,
            warn=fg.iyellow,
        )

def xml_get_first_child_node_of_tag(dom, tag):
    """
    See https://docs.python.org/3.6/library/xml.dom.minidom.html
    See https://docs.python.org/3.6/library/xml.dom.html

    :param dom: result of minidom.parseString(config_xml)
    :param tag: name of XML tag
    :return:
    """
    node = dom.getElementsByTagName(tag)
    if node:
        node = node[0].firstChild
        if node.nodeType == minidom.Node.TEXT_NODE:
            return node
    else:
        return None

def is_posix():
    try:
        import posix
        return True
    except ImportError:
        return False

def key_value_str_to_dict(s):
    d = {}
    kv_list = s.split(",")
    for kv in kv_list:
        k, v = kv.split("=")
        d[k] = v
    return d

def deltatimeToHumanStr(deltaTime, decimalPlaces=0, separator=' '):
    """
    Format number of seconds or a datetime.deltatime object into a short human readable string

    >>> deltatimeToHumanStr(datetime.timedelta(seconds=1))
    '1s'
    >>> deltatimeToHumanStr(datetime.timedelta(seconds=1.750), 1)
    '1.8s'
    >>> deltatimeToHumanStr(datetime.timedelta(seconds=1.750), 3)
    '1.750s'
    >>> deltatimeToHumanStr(datetime.timedelta(hours=3, seconds=1.2), 1)
    '3h 0m 1.2s'
    >>> deltatimeToHumanStr(datetime.timedelta(days=6, hours=14, minutes=44, seconds=55))
    '6d 14h 44m 55s'
    >>> deltatimeToHumanStr(123)
    '2m 3s'

    :param deltaTime:      Either number of seconds or a deltatime object
    :param decimalPlaces:  Number of decimal places for the seconds part
    :param separator:      Separator between each part
    :return:
    """
    if not isinstance(deltaTime, datetime.timedelta):
        deltaTime = datetime.timedelta(seconds=deltaTime)

    d = deltaTime.days
    h, s = divmod(deltaTime.seconds, 3600)
    m, s = divmod(s, 60)
    s = float(s) + float(deltaTime.microseconds) / 1000000
    #print("FOO", s, deltaTime.microseconds, float(deltaTime.microseconds)/1000000)

    dhms = ""
    if d > 0:
        dhms += str(d) + 'd' + separator
    if h > 0 or len(dhms) > 0:
        dhms += str(h) + 'h' + separator
    if m > 0 or len(dhms) > 0:
        dhms += str(m) + 'm' + separator
    if s > 0 or len(dhms) > 0:
        dhms += ('{:.%df}s' % decimalPlaces).format(s)

    return dhms

def timestamp_ms_to_datetime(ts_ms):
    t = datetime.datetime.fromtimestamp(int(ts_ms) / 1000)
    return t.strftime("%Y-%m-%d %H:%M:%S")

def timestamp_ms_to_deltatime(ts_ms):
    t = datetime.datetime.fromtimestamp(int(ts_ms) / 1000)
    dt = datetime.datetime.now() - t
    return deltatimeToHumanStr(dt)

def timestamp_ms_to_datetime_and_deltatime(ts_ms):
    abstime = timestamp_ms_to_datetime(ts_ms)
    dts = timestamp_ms_to_deltatime(ts_ms)
    return f"{abstime} ({dts} ago)"


#####################################################################
# Jenkins
#####################################################################

class JenkinsException(Exception):
    pass

class Config(object):
    """
        - `build_params_default` are the default parameters used for
           parameterized builds.
           - See https://wiki.jenkins.io/display/JENKINS/Parameterized+Build
           - Jenkins only allows remotely triggered builds if job config
             contains `authToken` thus resulting in REST API request:
             `http://server/job/myjob/buildWithParameters?token=TOKEN&PARAMETER=Value`

    """
    FILENAME = os.path.expanduser("~/.jenkins.ini")

    def __init__(self):
        self.server_url = "https://jenkins.url.not.set"
        self.check_certificate = True
        self.auth_user = ""
        self.auth_password = ""
        self.build_params_default = "delay=0"
        self.console_poll_interval = 2
        self.console_log_dir = "/tmp/jenkins-log"
        self.stop_job_on_user_abort = True

    def read(self, obj, filename=None):
        """

        :param filename:  path to configfile
        :return:          The filepath of the file that was read
        """
        if not filename:
            filename = Config.FILENAME
        if not os.path.exists(filename):
            return

        # ConfigParser stores values as strings, so you have to convert them yourself
        cfg = configparser.ConfigParser()
        cfg.read(filename)

        # Read the global section (which are the instance variables of this class)
        section = "global"
        for name in self.__dict__.keys():
            cur_value = getattr(self, name)
            if isinstance(cur_value, bool):
                value = cfg.getboolean(section, name, fallback=cur_value)
            elif isinstance(cur_value, int):
                value = cfg.getint(section, name, fallback=cur_value)
            elif isinstance(cur_value, float):
                value = cfg.getfloat(section, name, fallback=cur_value)
            else:
                value = cfg.get(section, name, fallback=cur_value)
                # strip quotes from config value is string
                value = value.strip('"')

            if value is not None:
                setattr(self, name, value)
                if not hasattr(obj, name):
                    raise RuntimeError(f"{obj} does no have attr '{name}'")
                setattr(obj, name, value)
                #print(f"setattr {name} = {value}")

        obj.config_was_read_ok = True
        return filename

    def write(self):
        d = { name:getattr(self, name) for name in self.__dict__.keys() }
        cfg = configparser.ConfigParser()
        cfg["global"] = d
        cfg.write(sys.stdout)
        print("# note that the username is without the email domain, e.g. 'foo' instead of 'foo@bla.org'")

class Jenkins(object):
    """
    Jenkins Commandline Client that can:

      - Start a build job, optionally with parameters
        - Wait for completion
        - Print console output on the fly
      - Fetch artifacts of build job (latestSuccessful or specific build number)
      - Get project info
      - Fetch full console log of given project (last build or specific build number)

    [Remote Access API](https://www.jenkins.io/doc/book/using/remote-access-api/)

    You need to set two class variables to make the class work:

        - `JENKINS_URL` is the URL for the Jenkins server


    https://javadoc.jenkins-ci.org/hudson/model/FreeStyleProject.html

    Python Jenkins Modules
      - https://python-jenkins.readthedocs.io/en/latest
        - https://opendev.org/jjb/python-jenkins
      - https://jenkinsapi.readthedocs.io/en/latest
        - https://github.com/pycontribs/jenkinsapi

    Other jenkins CLI implementations:
      - https://github.com/jenkins-zh/jenkins-cli (go)
      - https://github.com/m-sureshraj/jenni
        Jenkins personal assistant - CLI tool to interact with Jenkins server (nodejs)

    """
    BUILD_WAIT_TIMEOUT = 7200
    BUILD_NAMES = (
        'lastBuild', 'lastCompletedBuild', 'lastFailedBuild', 'lastSuccessfulBuild',
        # Following three are typically not that interesting
        'lastStableBuild', 'lastUnstableBuild', 'lastUnsuccessfulBuild'
    )

    def __init__(self, verbose=1):
        # disable InsecureRequestWarning: "Unverified HTTPS request" warnings
        requests.packages.urllib3.disable_warnings(requests.urllib3.exceptions.InsecureRequestWarning)

        # Configurable settings (read form config file)
        self.config_was_read_ok = False
        self.server_url = None
        self.check_certificate = True
        self.auth_user = ""
        self.auth_password = ""
        self.console_poll_interval = 2
        self.console_log_dir = "/tmp/jenkins-log"
        self.stop_job_on_user_abort = False

        self._conn_ok = False

        self.job_name = ""
        self.job_id = ""
        self.job_id_low = 0
        self.job_id_high = 0
        self.job_started = None
        self.artifacts = None

        self.build_params_default = ""

        self.console_output_file = True

        self.verbose = verbose
        self.log_progress = True

        self.log_req = False
        self.log_resp_status = False
        self.log_resp_headers = False
        self.log_resp_text = False
        self.log_resp_json = False

    def __str__(self):
        return f"<Jenkins {self.server_url} auth={self.auth_user}>"

    def log_enable(self, flags):
        self.log_req = 's' in flags
        self.log_resp_status = 'r' in flags
        self.log_resp_headers = 'h' in flags or 'rr' in flags
        self.log_resp_text = 't' in flags
        self.log_resp_json = 'j' in flags

    @staticmethod
    def get_log_help():
        return "s = send, r = response status, h = response headers, t = response text, j = response pretty json"

    def echo_progress(self, s):
        if self.log_progress:
            print(f"{color.progress}{s}{fg.reset}")

    def echo_note(self, s, level=0):
        if self.verbose >= level:
            print(f"{color.note}{s}{fg.reset}")

    def echo_info(self, s, level=0):
        if self.verbose >= level:
            print(f"{color.info}{s}{fg.reset}")

    def echo_verb(self, s, level=1):
        if self.verbose >= level:
            print(f"{color.info}{s}{fg.reset}")

    def log_response(self, response, force=False):
        # if self.log_req or force:
        #     print(f"{color.send}{response.request.method} {response.url}{fg.reset}")
        if self.log_resp_headers or force:
            print(f"{color.send}Request headers: {response.request.headers}{fg.reset}")
            #print(f"{color.send}Auth: {response.request.auth}{fg.reset}")
            print(f"{color.recv}Response: {response.status_code} {response.reason}\n{response.headers}{fg.reset}")
        elif self.log_resp_status:
            print(f"{color.recv}Response: {response.status_code} {response.reason}{fg.reset}")

        return response

    def job_id_iter(self):
        """
        Iterator over all job_id's if user supplied something like `foobaz/23..28
        """
        if self.job_id_low > 0 and self.job_id_high > 0:
            for job_id in range(self.job_id_low, self.job_id_high + 1):
                yield job_id
        else:
            yield self.job_id

    def set_job_name_and_id(self, job_name, job_id='lastSuccessfulBuild'):
        if not job_name:
            return
        parts = job_name.split("/")
        if len(parts) == 2:
            job_name, job_id = parts

        if ".." in job_id:
            parts = job_id.split("..")
            if len(parts) == 2:
                lo, hi = int(parts[0]), int(parts[1])
                if lo > hi:
                    lo, hi = hi, lo
                self.job_id_low, self.job_id_high = lo, hi
                job_id = str(lo)
                #print(f"job_id_low={self.job_id_low} job_id_high={self.job_id_high}")
                #sys.exit(0)

        self.job_name = job_name
        self.job_id = job_id
        if all([x in '0123456789' for x in job_id]):
            return
        if job_id == "last":
            self.job_id = Jenkins.BUILD_NAMES[0]
            return

        m = []
        for b in Jenkins.BUILD_NAMES:
            if job_id.lower() in b.lower():
                m.append(b)
        if len(m) > 1:
            raise ValueError(f"job_id matches several build types: {m}")
        if len(m) == 0:
            bts = ",".join(Jenkins.BUILD_NAMES)
            raise ValueError(f"Bad job_id: '{job_id}'\nAllowed job_id is numeric or one of: {bts}")

        self.job_id = m[0]

    def assert_auth_is_valid(self):
        s = "Add it to the jenkins config file or supply it with --auth option"
        if not self.auth_user:
            raise ValueError(f"Jenkins username is not set: {s}")
        if not self.auth_password:
            raise ValueError(f"Jenkins password/API-token is not set: {s}")

    def request(self, url, method="GET", params=None, auth=None, **kwargs):
        """
        see https://stackoverflow.com/questions/16907684/fetching-a-url-from-a-basic-auth-protected-jenkins-server-with-urllib2
        and https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/

        :param url: URL of the form "http://jenkins.lan/job/{name}"
        :return:    requests.Response object from requests.get()
        """
        if auth is True:
            auth = HTTPBasicAuth(username=self.auth_user, password=self.auth_password)

        if self.log_req:
            q = "?" + urllib.parse.urlencode(params) if params else ""
            auth_str = f"with HTTPBasicAuth(username={self.auth_user})" if auth else ""
            print(f"{color.send}{method} {url}{q}{fg.reset} {auth_str}")

        response = requests.request(method, url, params=params, verify=self.check_certificate, auth=auth, **kwargs)

        if not auth and response.status_code == 403 and self.auth_user and self.auth_password:
            self.log_response(response)
            self.echo_progress("Retrying with HTTPBasicAuth")
            auth = HTTPBasicAuth(username=self.auth_user, password=self.auth_password)
            response = requests.request(method, url, params=params, verify=self.check_certificate, auth=auth, **kwargs)

        self.log_response(response)

        if response.status_code >= 400:
            if not self.log_req:
                print(f"{color.send}{response.request.method} {response.url}{fg.reset}")
            response.raise_for_status()

        return response

    def request_api_json(self, url, params=None, **kwargs):
        """
        Send request and return response as JSON

        :param url: URL of the form "http://some.server.loc/job/{name}/api/json"
        :return:    JSON response object
        """
        if not url.endswith("/api/json"):
            url += "/api/json"
        response = self.request(url, params=params, **kwargs)

        if self.log_resp_text:
            print(response.text)

        jr = response.json()
        if self.log_resp_json:
            pprint(jr)

        return jr


    def assert_connectivity(self):
        # NOTE: we could also use requests.get(..., cert=FILEPATH) to pass in the CA certificate

        self.echo_info(f"Checking Jenkins connectivity: {self.server_url}")
        try:
            requests.get(self.server_url, verify=False)
            self._conn_ok = True
        except requests.exceptions.SSLError:
            error_msg_cacert = """
It seems you don't have the Jenkins (self-signed) CA certificate installed
or the certificate has expired. 
"""
            raise JenkinsException(error_msg_cacert)


    def get_job_url(self, name=None):
        if not name:
            name = self.job_name
        else:
            self.job_name = name
        if not name:
            raise ValueError("JOB name argument mssing")
        return f"{self.server_url}/job/{name}"

    def get_job_id_url(self, name=None, job_id=None):
        if not job_id:
            job_id = self.job_id
        else:
            self.job_id = job_id
        if not job_id:
            raise ValueError(f"Missing job ID. Try again with something like: {prog} ... {jen.job_name}/last")
        return self.get_job_url(name) + f"/{job_id}"

    def list_projects(self):
        url = f"{self.server_url}"
        jr = jen.request_api_json(url, {'tree': "jobs[name]"})
        jobs = jr.get('jobs')
        for job in jobs:
            _class = job.get('_class')
            if _class:
                _class = _class.split(".")[-1]
            name = job.get('name')
            if self.verbose:
                print(name, _class)
            else:
                print(name)

    def list_queue(self):
        w = 13
        def print_queue_item(i, j):
            _class = j.get('_class')
            if not _class:
                return

            print(f"{i:3d} {_class:{w}} '{j['name']}' {j.get('id')}")

            # 'blocked', 'buildableStartMilliseconds',
            #for k in ('name', 'id', 'inQueueSince', 'timestamp', 'why'):
            for k in ('inQueueSince', 'timestamp', 'why'):
                if k not in j:
                    continue
                print(f"    {k:{w}} {j.get(k)}")

        for i, item in enumerate(self.get_queue()):
            if self.job_name and self.job_name != item['name']:
                continue
            print_queue_item(i, item)

    def get_queue(self):
        def fixup_queue_item(j):
            _class = j.get('_class')
            if _class:
                _class = _class.split(".")[-1].replace("Queue$", "").replace("Item", "")
                j['_class'] = _class

            if _class not in ("Waiting", "Blocked", "Buildable"):
                return

            for k in ('inQueueSince', ): #, 'buildableStartMilliseconds'
                if k in j:
                    j[k] = timestamp_ms_to_datetime_and_deltatime(j[k])
            timestamp = j.get('timestamp')
            if timestamp:
                j['timestamp'] = timestamp_ms_to_datetime(timestamp)

            task = j.get('task')
            if task:
                j['name'] = task.get('name')

            why = j.get('why', "")
            toolong = len(why) - 70
            if toolong > 0:
                if toolong < 12:
                    j['why'] = why
                else:
                    j['why'] = why[:60] + f" ... [{toolong} more]"

            return j

        url = f"{self.server_url}/queue"
        jr = jen.request_api_json(url)
        for item in jr.get('items'):
            yield fixup_queue_item(item)

    def get_queue_by_job(self, name):
        self.echo_info("Getting Jenkins queue")
        for item in self.get_queue():
            if item['name'] == name:
                yield item

    def list_nodes(self, oneline=True):
        w = 13
        def print_computer(i, j):
            _class = j.get('_class')
            if not _class:
                return

            displayName = j['displayName']
            desc = j.get('description')
            labels = j.get('labels')
            numExecutors = j.get('numExecutors')
            idle_busy = "idle" if j.get('idle') is True else "busy"
            on_offline = "offline" if j.get('offline') is True else "online"

            if oneline:
                print(f"{i:3d} {_class} {idle_busy} {numExecutors} {on_offline} '{displayName}' labels='{labels}' desc='{desc}'")
            else:
                print(f"{i:3d} {_class:{w}} '{displayName}' {desc}")
                for k in ('labels', 'idle', 'numExecutors'):
                    print(f"    {k:{w}} {j.get(k)}")

        # if oneline:
        #     print("num Class  Idle  Executors online name labels desc")

        for i, item in enumerate(self.get_nodes(search=self.job_name)):
            print_computer(i, item)

    def get_nodes(self, search=None):
        def fixup_computer(j):
            _class = j.get('_class')
            _class = _class.split(".")[-1].replace("Hudson$", "").replace("Computer", "")
            j['_class'] = _class

            j['labels'] = " ".join(x['name'] for x in j['assignedLabels'])
            return j

        url = f"{self.server_url}/computer"
        jr = jen.request_api_json(url)
        for item in jr.get('computer'):
            c = fixup_computer(item)
            if not search:
                yield c
            elif search in c['labels'] or search in c['displayName']:
                yield c


    @staticmethod
    def job_get_param_definition(jr):
        props = jr.get('property')
        job_params = []
        for prop in props:
            if len(prop) == 1:
                continue
            if prop.get('_class') != "hudson.model.ParametersDefinitionProperty":
                continue

            params = prop.get('parameterDefinitions')
            for param in params:
                job_param = {
                    'name': param.get('name'),
                    'default': param.get('defaultParameterValue', {}).get('value'),
                    'description': param.get('description'),
                }
                job_params.append(job_param)

        return job_params

    def print_project(self, name=None, all_builds=False):
        """

        :param name:
        """
        url = self.get_job_url(name)
        jr = self.request_api_json(url)

        _class = jr.get('_class')
        if _class:
            _class = _class.split(".")[-1]
            jr['class'] = _class

        # Make dictionary of symbolic build names to build number,
        # e.g. { 'last': 94, 'lastSuccessful': 94, 'lastFailed': 92, ... }
        name_to_number = {}
        for b in Jenkins.BUILD_NAMES[:4]:
            sym_build_name = jr.get(b)
            if sym_build_name:
                number = "None" if sym_build_name is None else sym_build_name.get('number')
                name = b.replace("Build", "")
                name_to_number[name] = number

        if all_builds:
            jr = self.build_get(job_id="all")
            for jr_build in reversed(jr.get('builds')):
                self.build_print(jr_build, oneline=True, name_to_number=name_to_number)
            return

        w = 16
        # 'inQueue' is apparently always False?
        for name in ('fullName', 'description', 'class'):
            value = jr.get(name)
            print(f"{name:{w}} {value}")

        props = jr.get('property')
        # Project has properties only if there are more than the '_class'
        # item in any of the arrays dictionaries
        # has_props = max(len(p) for p in props) > 1
        # if has_props:
        #     print("property:")

        def printProperty():
            _class = prop.get('_class')
            if _class == "hudson.model.ParametersDefinitionProperty":
                params = prop.get('parameterDefinitions')
                print("parameterDefinitions:")
                name_width = max([len(p.get('name')) for p in params]) + 1
                for param in params:
                    name = param.get('name')
                    defval = param.get('defaultParameterValue', {}).get('value')
                    print(f"    {name:{name_width}} {defval}")
            else:
                print(f"  {_class}: No handler for printing this class")

        for prop in props:
            if len(prop) > 1:
                printProperty()

        # Iterate only over distinct/unique build numbers
        numbers = set(name_to_number.values())
        for number in sorted(numbers):
            jr_build = self.build_get(job_id=number)
            self.build_print(jr_build, name_to_number=name_to_number)

        if self.verbose:
            queue = list(self.get_queue_by_job(self.job_name))
            if queue:
                print(f"{len(queue)} build jobs queued for {self.job_name}")
            else:
                print(f"No build jobs queued for {self.job_name}")


    def build_print(self, jr, oneline=False, name_to_number=dict()):

        number = jr.get('number')
        result = jr.get('result')
        building = jr.get('building')
        timestamp = timestamp_ms_to_datetime_and_deltatime(jr.get('timestamp'))
        duration = deltatimeToHumanStr(jr.get('duration') / 1000)
        estDuration = deltatimeToHumanStr(jr.get('estimatedDuration') / 1000)

        sym_names = [ name for name,num in name_to_number.items() if num == number ]
        sym_names = " ".join(sym_names) if sym_names else ""
        if oneline:
            print(f"{number:4} {result:10} {duration:>10}  {timestamp}  {sym_names}")
        else:
            w = 12
            print(f"build {number:{w - 2}} {sym_names}")
            for name in ('result', 'building'):
                value = jr.get(name)
                if value:
                    print(f"    {name:{w}} {value}")

            for name, value in (('timestamp', timestamp), ('duration', duration), ('estDuration', estDuration)):
                print(f"    {name:{w}} {value}")


    def build_get(self, name=None, job_id=None):
        """
        Get Jenkins job result

        For example, to get artifacts::

            jr = jenkins.get_job()
            artifacts = jr.get('artifacts', [])
            >>> [{'displayPath': 'foo.zip', 'fileName': 'foo.zip', 'relativePath': 'foo.zip'}],

        See https://stackoverflow.com/questions/54119863/get-build-details-for-all-builds-of-all-jobs-from-jenkins-rest-api

        :param name:   Jenkins job name
        :param job_id: Jenkins job ID
        :return:       JSON response object of request "{self.server_url}/job/{name}/{job_id}"
        """
        url = self.get_job_id_url(name=name, job_id=job_id)
        params = {}
        if self.job_id == "all":
            url = self.get_job_url()
            params = {'tree': 'jobs[name]'}
            params = {'tree': 'jobs[name,url,builds[number,result,duration,url]]'}
            params = {'tree': 'builds[number,result,timestamp,duration,estimatedDuration]'}
            #url = f"{self.server_url}"
        return self.request_api_json(url, params=params)

    def get_config_as_xml_and_dom(self, name=None):
        """
        Get Jenkins job config XML

        :param name:  Jenkins job name
        :return:      XML text, xml.dom.minidom.Document object
        """
        job_url = self.get_job_url(name=name)
        url = f"{job_url}/config.xml"
        response = self.request(url, auth=True)
        if not response.text.startswith('<?xml version=') \
            or not '<flow-definition plugin="workflow-job@' in response.text:
            self.echo_note("""Content of response is not exactly as expected ...
Please check the output to see if it really is config.xml""")

        return response.text, minidom.parseString(response.text)

    def get_system_log(self):
        url = f"{self.server_url}/api/system/logs"
        response = self.request(url, method="GET", auth=True)
        print(response.content)

    def post_config_xml(self, xml_text=None, filename=None, name=None):
        """
        Post config.xml to Jenkins job

        :param xml_text:
        :param filename:
        :param name:
        :return:
        """
        job_url = self.get_job_url(name=name)
        url = f"{job_url}/config.xml"

        if filename and xml_text:
            raise ValueError("Ambiguous arguments: both xml_text and filename supplied")
        if not xml_text:
            xml_text = open(filename, "r").read()
        else:
            filename = "new config"
        try:
            response = self.request(url, method="POST", data=xml_text, auth=True)
            self.echo_info(f"Posted {filename} to {self.job_name} config.xml")
        except requests.exceptions.HTTPError as e:
            r = e.response
            if r.status_code == 500:
                new_config_msg = ""
                if filename:
                    new_config_msg = f"New config.xml was saved to {filename}\n"
                print(f"""
POST of config.xml was refused on server.
{new_config_msg}
You can inspect the Jenkins server logs for the exact cause here:
    {self.server_url}/log/all
""")
            raise

    def get_groovy_script(self):
        xml, dom = self.get_config_as_xml_and_dom()
        node = xml_get_first_child_node_of_tag(dom, "script")
        return node.nodeValue if node else ""

    def get_config_replace_script_and_post(self, filename):
        xml, dom = self.get_config_as_xml_and_dom()

        ts = datetime.datetime.fromtimestamp(time.time())
        backup_file, _ = self.make_output_filename_and_symlink(with_job_id=False)
        backup_file += ts.strftime("-config.xml.%Y%m%d-%H%M%S")
        open(backup_file, "w").write(xml)
        self.echo_info(f"Wrote backup of config.xml to {backup_file}")

        node = xml_get_first_child_node_of_tag(dom, "script")
        if not node:
            raise ValueError("<script> element not found in config")

        script_text = open(filename, "r").read()
        node.nodeValue = script_text
        self.echo_info(f"Replaced config.xml <script> with file '{filename}'")

        new_config, _ = self.make_output_filename_and_symlink(with_job_id=False)
        new_config += ts.strftime("-new-config.xml")
        open(new_config, "wb").write(dom.toxml('utf-8'))
        self.echo_info(f"Wrote new version of config.xml to {new_config}")
        self.post_config_xml(filename=new_config)

    def make_output_filename_and_symlink(self, with_job_id=True):
        logpath_job = f"{self.console_log_dir}/{self.job_name}"
        symlink = f"{logpath_job}-latest" if is_posix() else ""
        logfile = f"{logpath_job}"
        if with_job_id:
            logfile += f"-{self.job_id}"
        os.makedirs(os.path.dirname(logpath_job), exist_ok=True)
        return logfile, symlink

    def get_console_output_for_job(self, name, job_id, fout, stdout):

        job_url = self.get_job_id_url(name=name, job_id=job_id)
        text_size = 0
        started_at = time.time()
        last_output_at = started_at
        last_progress_at = last_output_at

        while True:
            url = f"{job_url}/logText/progressiveText?start={text_size}"
            r = self.request(url)
            if r.text:
                last_output_at = time.time()
                last_progress_at = last_output_at
                if stdout:
                    sys.stdout.write(r.text)
                if fout:
                    fout.write(r.text)
                    fout.flush()

            more_data = r.headers.get('X-More-Data')
            text_size = r.headers.get('X-Text-Size')
            if not more_data:
                break

            time.sleep(self.console_poll_interval)

            if time.time() - last_progress_at >= 10:
                last_progress_at = time.time()

                since_start = deltatimeToHumanStr(time.time() - started_at)
                since_output = deltatimeToHumanStr(time.time() - last_output_at)
                self.echo_progress(
                    f"Waiting for output: started {since_start} ago, last output {since_output} ago")

    def get_console_output(self):
        """
        https://jenkins.lan/job/openwrt/17/logText/progressiveText?start=0
        """
        # only print to stdout if we are getting log of a single job
        is_only_one_job = len(list(self.job_id_iter())) == 1

        for job_id in self.job_id_iter():
            fout = None
            if self.console_output_file:
                logfile, symlink = self.make_output_filename_and_symlink()
                self.console_output_file = f"{logfile}-console.log"
                fout = open(self.console_output_file, "w")
                if symlink and is_only_one_job:
                    symlink = f"{symlink}-console.log"
                    if os.path.islink(symlink):
                        os.remove(symlink)
                    os.symlink(os.path.basename(self.console_output_file), symlink)

            self.get_console_output_for_job(name=None, job_id=job_id, fout=fout, stdout=is_only_one_job)

            if self.console_output_file:
                self.echo_info(f"Wrote console output to {self.console_output_file}")
                if symlink and is_only_one_job:
                    self.echo_info(f"Wrote symlink {symlink}")

    def req_waitfor_key_value(self, url, key, wait_msg="result", timeout=60, interval=1):
        """
        Continuously poll ``url`` (api/json) and return when JSON response object
        contains ``key`` and is non-empty

        :param url:      Jenkins job url
        :param key:      JSON key to wait for
        :param wait_msg: User meesage printed on console
        :param timeout:  Timeout
        :param interval: Poll interval
        :return:         JSON response object
        """
        if not interval:
            interval = max(int(timeout / 30), 5)

        started = time.time()
        deadline = started + timeout
        elapsed = 0
        while time.time() < deadline:

            jr = self.request_api_json(url)

            # only return if key exists AND has a value
            value = jr.get(key)
            if value is not None:
                self.echo_verb(f"Got: {key}")
                return jr

            time.sleep(interval)
            elapsed = time.time() - started
            if elapsed < 20 or int(elapsed) % 5 < interval:
                self.echo_progress(f"Waiting for {wait_msg}: {elapsed:.0f}s of {timeout}s")

        msg = f"TIMEOUT after {elapsed:.0f}s while waiting for {wait_msg}"
        raise JenkinsException(msg)

    def job_start(self, name=None, params=None):
        """
        :param name:    Jenkins job name
        :param params:  comma separated list of key=value pairs, e.g. 'foo=1,baz=10'
                        or dictionary of build parameters
        :return:        job_id
        """
        # See if it is a parameterized job or not
        job_url = self.get_job_url(name)
        jr = self.request_api_json(job_url)
        job_params = self.job_get_param_definition(jr)
        allparams = self.build_params_default

        if job_params:
            self.echo_info(f"Starting Jenkins parameterized job {self.job_name}")
            self.echo_info(f"Using parameters: '{self.build_params_default}' (config default) '{params}' (user supplied)")
            build = "buildWithParameters"
            if params:
                allparams += f",{params}"
        else:
            self.echo_info(f"Starting Jenkins job {self.job_name}")
            build = "build"

        if not "delay=0" in allparams:
            self.echo_info(f"Build parameters do not contain 'delay=0' although it is highly recommended")
        try:
            build_params = key_value_str_to_dict(allparams)
        except:
            raise ValueError("Invalid job PARAMS list")

        url = f"{job_url}/{build}"
        try:
            self.job_started = time.time()
            resp = self.request(url, params=build_params)
        except requests.exceptions.RequestException as e:
            if hasattr(e, 'response') and e.response.status_code == 403:
                print("""
Reason for not being able to start a build remotely, might be because
the project config does not have auth token enabled.
Check if config.xml contains somehting like <authToken>sometoken</authToken>
It can be enabled it in the web UI under
   "Build Triggers / Trigger builds remotely (e.g., from scripts)"
After that, add the "token=sometoken" as a parameter on the command line
or as build_params_default in config file.
""")
            raise JenkinsException(f"FAILED to start jenkins job {self.job_name} with {url}")

        location_url = resp.headers.get('Location')
        if not location_url:
            self.log_response(resp, force=True)
            raise JenkinsException("Location header not found in response. Is URL correct?")

        self.echo_info(f"Requested Jenkins job {self.job_name}, waiting for build number")

        url = f"{location_url}api/json"
        jr = self.req_waitfor_key_value(url, key="executable", wait_msg="job start", timeout=120)
        number = jr['executable']['number']
        self.job_id = number

        self.echo_info(f"Started Jenkins job {self.job_name}, build number {number}")
        return int(number)


    def job_cancel(self):
        """
        If the build has not started, you have the queueItem, then POST on:
        http://<Jenkins_URL>/queue/cancelItem?id=<queueItem>
        """
        self.get_job_url() # set self.job_name
        queue = list(self.get_queue_by_job(self.job_name))
        if not queue:
            self.echo_note(f"Job {self.job_name} not in queue")
            return 0

        self.echo_info(f"Cancelling {len(queue)} in queue")
        for item in queue:
            url = f"{self.server_url}/queue/cancelItem"
            params = { 'id': item['id']}
            resp = self.request(url, method="POST", params=params, auth=True)
            if resp.ok:
                self.echo_info(f"Job {item['id']} cancelled")

        return len(queue)

    def job_stop(self):
        """
        Stop build with POST on:
        http://<Jenkins_URL>/job/<Job_Name>/<Build_Number>/stop
        """
        if not self.job_id:
            self.job_id = "lastBuild"
        url = self.get_job_id_url() + "/stop"
        resp = self.request(url, method="POST", auth=True)
        if resp.ok:
                self.echo_info(f"Job {self.job_name} stopped")


    def compute_job_poll_interval(self, estDuration, elapsed):
        """
        Compute auto-adjusting interval for polling build job completion
        The longer the build, the longer the poll interval

        :param estDuration:
        :param elapsed:
        :return:
        """
        poll = int(1 + round(estDuration / 10))
        if poll > 10:
            poll = 10
        timeout = 2 * estDuration
        if estDuration > 30:
            timeout = estDuration * 1.2
        return poll, round(timeout)

    def job_get_poll_interval(self):
        url = self.get_job_id_url()
        jr = self.request_api_json(url)
        estDuration = jr.get('estimatedDuration', 60000) / 1000
        est_str = deltatimeToHumanStr(estDuration)
        self.echo_info(f"Jenkins job {self.job_name}/{self.job_id} estDuration={est_str}")
        return self.compute_job_poll_interval(estDuration, 0)


    def job_wait(self, name=None, job_id=None, build_wait=None):
        """
        :param build_wait: Seconds to wait for build completion
        :return:
        """
        if not job_id:
            job_id = self.job_id
        if not job_id:
            self.build_get(name)

        job_url = self.get_job_id_url(name=name, job_id=job_id)
        poll, timeout = self.job_get_poll_interval()
        if build_wait:
            timeout = build_wait

        jr = self.req_waitfor_key_value(job_url, key="result", wait_msg="job completion", timeout=timeout, interval=poll)
        result = jr.get('result')

        elapsed = deltatimeToHumanStr(int(jr.get('duration', 0)) / 1000)
        self.echo_info(f"Build {self.job_name}/{self.job_id} completed in {elapsed} with result={result}")

        if result != 'SUCCESS':
            raise JenkinsException(f"Jenkins job result='{result}' but expected SUCCESS")

        self.artifacts = jr.get('artifacts', [])
        return result


    def fetch_artifacts(self, dest_dir, artifacts=None):
        if not artifacts:
            artifacts = self.artifacts
        if not artifacts:
            self.echo_verb(f"Querying artifacts of job {self.job_name}/{self.job_id}")
            jr = self.build_get()
            artifacts = jr.get('artifacts', [])

        if not artifacts:
            self.echo_info(f"Job {self.job_name}/{self.job_id} has no build artifacts")
            return 0

        job_url = self.get_job_id_url()

        for item in artifacts:
            relpath = item['relativePath']
            artifact_url = f"{job_url}/artifact/{relpath}"
            response = self.request(artifact_url)

            dest_path = Path(dest_dir, item['fileName'])
            self.echo_info(f"Saving artifact {dest_path}")
            with dest_path.open('wb') as f:
                f.write(response.content)


    def workspace_wipeout(self, name=None):
        url = self.get_job_url(name=name)
        self.echo_info(f"Wiping workspace of {self.job_name}")
        url = f"{url}/doWipeOutWorkspace"
        return self.request(url, method="POST", auth=False, data="")


    class Waiter(threading.Thread):
        def __init__(self, jenkins, message):
            threading.Thread.__init__(self)
            self.jenkins = jenkins
            self.message = message
            self.started = None
            self.running = True
            self.daemon = True

        def run(self):
            # self.jenkins.echo_progress(f"Waiter thread starting")
            self.started = time.time()
            while True:
                elapsed = time.time() - self.started
                interval = 1 if elapsed < 4 else 2 if elapsed < 20 else 5
                for i in range(10 * interval):
                    # Chunk the waiting so we can stop thread quickly (max 100ms latency)
                    # This only has an effect when we use thread.join()
                    time.sleep(0.1)
                    if not self.running:
                        # self.jenkins.echo_progress(f"Waiter thread stopped")
                        return
                elapsed_human = deltatimeToHumanStr(time.time() - self.started)
                self.jenkins.echo_progress(f"{self.message}: {elapsed_human} elapsed")

        def stop(self):
            self.running = False
            #self.join()

    def workspace_get_file(self, filepath):
        # There seems to be a difference in the URL used to retrieve items
        # from the workspace. Maybe it has something to do if the job is
        # configured with or without concurrent builds.
        # The two base URLs are:
        #   "{jobid_url}/execution/node/{str(i)}/ws/{filepath}" (concurrent job)
        #   "ws/{filepath}" (non-concurrent job)
        # That has to be investigated further. For now we assume the simple case
        # that there is only one workspace per job
        # TODO: maybe we should automatically retry a directory fetch so the user
        #       doesn't have to be made aware of the difference in the actual API.
        #       and maybe we should also automatically unzip the zip file?
        def post_normal():
            resp = self.request(url, method="POST", auth=True)
            # This is a quick adhoc fix for determining whether we get an HTML
            # page listing files or if we got the actual file
            if 'X-Instance-Identity' in resp.headers:
                self.echo_info(f"{filepath} seems to be a directory: fetch a directory with: --ws {filepath}/zip")
                return None

            return resp.content

        def post_chunked():
            """This takes double time compared to post_normal()"""
            resp = self.request(url, method="POST", auth=True, stream=True)
            # This is a quick adhoc fix for determining whether we get an HTML
            # page listing files or if we got the actual file
            if 'X-Instance-Identity' in resp.headers:
                self.echo_info(f"{filepath} seems to be a directory")
                return None

            length = resp.headers.get('Content-Length')
            # print(f"content-length = {length}")
            content = b""
            for i, chunk in enumerate(resp.iter_content(chunk_size=10 * 1024 * 1024)):
                #print(i)
                content += chunk

            resp.close()
            return content

        def request_transfer_and_wait():
            try:
                waiter = Jenkins.Waiter(self, "Transferring")
                waiter.start()
                content = post_normal()
                waiter.stop()
                return content

            except requests.exceptions.HTTPError as e:
                if e.response.status_code != 404:
                    raise
            finally:
                waiter.stop()

        # assume non-concurrent job
        simple_job = True
        if simple_job:
            self.echo_info("Getting workspace file ...")
            url_base = self.get_job_url()
            url = f"{url_base}/ws/{filepath}"
            return request_transfer_and_wait()
        else:
            self.echo_info("Getting workspace file (trying various URLs...)")
            url_base = self.get_job_id_url(job_id="lastBuild")
            for i in range(10):
                url = f"{url_base}/execution/node/{str(i)}/ws/{filepath}"
                return request_transfer_and_wait()
            raise ValueError("Exhausted .../execution/node/<ID>/ws/... URL attempts")


    def workspace_save_file(self, path, dest_dir="."):
        """

        :param path:     path to workspace file/dir to fetch and save
        :param dest_dir:
        :return:
        """
        if path == "/zip":
            # get entire workspace as a zip
            path = f"*zip*/{self.job_name}.zip"
        elif path.endswith("/zip"):
            path = path[:-4]
            path_base = os.path.basename(path)
            path = f"{path}/*zip*/{path_base}.zip"

        if not os.path.exists(dest_dir):
            print(f"created {dest_dir}")
            os.makedirs(dest_dir, exist_ok=True)

        path_base = os.path.basename(path)
        dest_path = f"{dest_dir}/{path_base}"
        if os.path.exists(dest_path):
            raise ValueError(f"{dest_path} already exists") # FileExistsError

        started = time.time()
        content = self.workspace_get_file(path)
        if not content:
            return

        elapsed = time.time() - started
        if elapsed > 2:
            size_kb = len(content) / 1024
            size_mb = size_kb / 1024
            size_str = f"{size_mb:.1f}MB" if size_mb > 5 else f"{size_kb:.1f}kB"
            elapsed_human = deltatimeToHumanStr(elapsed)
            self.echo_info(f"Transferred {size_str} in {elapsed_human}")

        open(dest_path, "wb").write(content)
        size_kb = len(content) / 1024
        self.echo_info(f"Wrote {size_kb:.1f}kB to {dest_path}")
        # resp = self.request(url, method="GET", auth=False, data="")
        sys.exit(0)


prog = os.path.basename(__file__)

def parser_create():
    description = f"""\
Start Jenkins jobs remotely via Jenkins REST API, retrieve build artifacts,
and much more

Configuration is read from {Config.FILENAME}
"""
    epilog = f"""
See command-line examples with: {prog} -hh
"""
    parser = argparse.ArgumentParser(
        description=description, epilog=epilog, add_help=False, formatter_class=argparse.RawDescriptionHelpFormatter)

    args_pos = parser.add_argument_group("Position arguments")
    args_pos.add_argument(dest='jobname', metavar='JOB[/ID]', type=str, default=None, nargs='?',
        help="Jenkins job name (and build ID). This is a mandatory argument for many commands")

    args_build = parser.add_argument_group("Build arguments")
    args_build.add_argument('-b', dest='do_build', default=False, action="store_true",
        help="Start build job")
    args_build.add_argument('-p', dest='params', metavar='PARAMS', type=str, default="",
        help="Job params given as comma separated list of key=value pairs, e.g. 'foo=1,baz=10'")
    args_build.add_argument('-B', dest='stop_build', action='count', default=0,
        help="Stop build job. Give option twice to cancel job")
    args_build.add_argument('-c', dest='get_console', default=False, action="store_true",
        help="Get console ouput for job")
    args_build.add_argument('-w', dest='job_wait', default=False, action="store_true",
        help="Wait for job completion. Useful when job is already running")
    args_build.add_argument('-t', dest='timeout', type=int, default=None,
        help="Build completion timeout (when -b option is given). Default is auto-computed")

    groovy_args = parser.add_argument_group("Jenkins config and groovy commands/actions")
    groovy_args.add_argument('--groovy',  dest='groovy', metavar='FILE', type=str,
        help="Get config.xml, replace groovy script with FILE and post new config")
    groovy_args.add_argument('--get-groovy',  dest='get_groovy', action="store_true",
        help="Get config.xml, extract groovy script and print it")
    groovy_args.add_argument('--get-config',  dest='get_config', action="store_true",
        help="Get config.xml and print it")
    groovy_args.add_argument('--post-config',  dest='post_config', metavar='FILE', type=str,
        help="Read FILE and post as config.xml to Jenkins job JOBNAME")

    args_other = parser.add_argument_group("Misc commands/actions")
    args_other.add_argument('--arti', dest='get_artifacts', default=False, action="store_true",
        help="Get artifacts from build and save them")
    # args_other.add_argument('-j', dest='job_id', metavar="ID", default="lastSuccessfulBuild",
    #     help="Job ID, e.g. for fetching artifacts from specific build job. Default is 'lastSuccessfulBuild'")
    args_other.add_argument('-o', dest='outdir', metavar='DIR', default=".",
        help="Output directory for build artifacts")
    args_other.add_argument('-i', dest='get_info', default=False, action="store_true",
        help="Get project info summary")
    args_other.add_argument('-a', dest='all', default=False, action="store_true",
        help="List all builds of project")
    args_other.add_argument('--list', dest='list', default=False, action="store_true",
        help=f"List all projects")
    args_other.add_argument('--que', dest='list_queue', default=False, action="store_true",
        help=f"List Jenkins queue")
    args_other.add_argument('--nodes', dest='list_nodes', default=False, action="store_true",
        help=f"List Jenkins build nodes/machines")
    args_other.add_argument('--ws', dest='ws_get', metavar="PATH", default="", type=str,
        help=f"Get file PATH from workspace. Use 'some/sub/dir/zip' to get zip of directory")
    args_other.add_argument('--wipews', dest='wipe_workspace', default=False, action="store_true",
        help=f"Wipe out (delete) workspace of JOB_NAME")

    option_args = parser.add_argument_group("Misc options")
    option_args.add_argument('-d', dest='log_http', metavar='srhtj', default="",
        help='Log HTTP transactions: ' + Jenkins.get_log_help())
    option_args.add_argument('--no-progress', dest='log_progress', default=True, action="store_false",
        help="Suppress wait progress messages")
    option_args.add_argument('--url', dest='server_url', metavar="URL", default=None,
        help=f"Jenkins server URL. Default is {Config().server_url} or JENKINS_URL from environment")
    option_args.add_argument('--auth', dest='auth', metavar="NAME_TOK", default=None,
        help=f"Username and API token, separated by colon. Usually required for --get-config, --post-config")
    option_args.add_argument('--makeconf', dest='write_config', action='store_true',
        help='Write a configuration file template')
    option_args.add_argument('-v', dest='verbose', action='count', default=0,
        help='Be more verbose')
    option_args.add_argument('-h', dest='help', action='count', default=0,
        help='Show usage. Give option twice to see usage examples')
    return parser

def print_examples():
    names = [ x.replace("Build", "") for x in Jenkins.BUILD_NAMES[1:] ]
    bn = ", ".join(names)
    print(f"""\
{prog} command-line examples:

Write default/template configuration:
  {prog} --makeconf > ${{HOME}}/.jenkins.ini
build 'sandbox' project:
  {prog} -b sandbox
Get information for 'sandbox' project:
  {prog} -i sandbox
Build 'house' project with parameters and save artifacts to /tmp:
  {prog} -b house -p doors=2,windows=8 --arti -o /tmp
Save artifacts from last successful build:
  {prog} house/lastsucc --arti -o /tmp
Wait for 'longwinded' project to complete build while showing console output:
  {prog} longwinded -w -c
Stop last started build:
  {prog} longwinded -B
Replace groovy script for 'foobaz' project, then build while showing console output:
  {prog} foobaz --groovy newscript -bc
Get config.xml for 'foobaz' project:
  {prog} foobaz --get-config=foobaz.config.xml
Get file from workspace of last build of 'foobaz' project:
  {prog} foobaz --ws build/output.log
Get zipped directory of workspace of last build of 'foobaz' project:
  {prog} foobaz --ws build/zip
Get console logs for build jobs 42 through 50:
  {prog} foobaz/42..50 -c

JOB/ID is the Jenkins job name and ID where ID is numeric ID or a possibly
abbreviated (and unique) substring of one of following build names:
last, {bn}
""")

if __name__ == "__main__":
    parser = parser_create()
    opt = parser.parse_args()
    if opt.help:
        if opt.help == 2:
            print_examples()
        else:
            parser.print_help()
        sys.exit(0)
    elif opt.write_config:
        Config().write()
        sys.exit(0)

    def print_traceback_tip():
        if 'd' in opt.log_http:
            traceback.print_exc()
        else:
            print(f"{fg.yellow}Tip: add -dd command-line option to see traceback{fg.reset}")

    jen = Jenkins(verbose=opt.verbose)

    # Order of preference is from highest to lowest: commandline, environment, config
    conffile = Config().read(jen)

    color_enable()

    env_auth = os.environ.get("JENKINS_AUTH")
    auth = opt.auth or env_auth or f"{jen.auth_user}:{jen.auth_password}"
    if auth:
        user_passwd = auth.split(":")
        if len(user_passwd) != 2:
            raise ValueError("User name and API token must be separated by colon")
        jen.auth_user, jen.auth_password = user_passwd

    if opt.verbose >= 2:
        jen.log_enable("srr")
    jen.log_enable(opt.log_http)
    jen.log_progress = opt.log_progress

    if jen.config_was_read_ok:
        jen.echo_verb(f"Read config from {conffile}")
    else:
        print(f"{color.warn}WARNING: Config file not found{fg.reset}")

    try:
        url = os.environ.get("JENKINS_URL")
        jen.server_url = opt.server_url or url or jen.server_url
        if not jen.server_url:
            raise ValueError(f"Jenkins URL not set")
        if not jen.server_url.startswith("http"):
            raise ValueError(f"Jenkins URL invalid")

        job_id = getattr(opt, 'job_id', "")
        jen.set_job_name_and_id(opt.jobname, job_id)
        if not jen.job_id:
            jen.job_id = "lastBuild"

        if opt.list:
            jen.list_projects()

        if getattr(opt, 'wipe_workspace', None):
            # not working, Response: 404 Not Found (method was POST)
            jen.workspace_wipeout()
            sys.exit(0)

        if opt.get_config:
            jen.assert_auth_is_valid()
            xml, _ = jen.get_config_as_xml_and_dom()
            print(xml)

        if opt.post_config:
            jen.assert_auth_is_valid()
            jen.post_config_xml(filename=opt.post_config)

        if opt.groovy or opt.get_groovy:
            jen.assert_auth_is_valid()
            if opt.get_groovy:
                text = jen.get_groovy_script()
                print(text)
            if opt.groovy:
                jen.get_config_replace_script_and_post(filename=opt.groovy)

        if opt.stop_build:
            if opt.stop_build == 1:
                jen.job_stop()
            else:
                jen.job_cancel()

        elif opt.do_build:
            jen.job_start(params=opt.params)
            if opt.get_console:
                jen.get_console_output()
            jen.job_wait(build_wait=opt.timeout)

        elif opt.job_wait:
            if opt.get_console:
                # Get job ID/number of (currently running) lastBuild job
                url = jen.get_job_url()
                jr = jen.request_api_json(url)
                last = jr['lastBuild']
                if last:
                    jen.job_id = last.get('number')
                    jen.get_console_output()
            jen.job_wait(build_wait=opt.timeout)

        elif opt.get_console:
            jen.get_console_output()

        elif opt.ws_get:
            jen.workspace_save_file(opt.ws_get, dest_dir=opt.outdir)

        if opt.get_artifacts:
            jr = jen.build_get()
            artifacts = jr.get('artifacts', [])
            jen.fetch_artifacts(opt.outdir, artifacts)

        if opt.get_info:
            jen.print_project(all_builds=opt.all)
        elif opt.all:
            jen.print_project(all_builds=opt.all)

        if opt.list_queue:
            jen.list_queue()

        if opt.list_nodes:
            jen.list_nodes()

        sys.exit(0)

    except requests.exceptions.HTTPError as e:
        r = e.response
        print(f"{color.error}{r.status_code} {r.reason} for {r.url}{fg.reset}")
        print_traceback_tip()
        sys.exit(4 if r.status_code < 500 else 5)
    except (requests.exceptions.RequestException, JenkinsException, ValueError) as e:
        print(f"{color.error}{e}{fg.reset}")
        print_traceback_tip()
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"{color.error}User abort{fg.reset}")
        if opt.do_build:
            if jen.stop_job_on_user_abort:
                jen.job_stop()
                print(f"""stopped job because {Config.FILENAME} contains 'stop_job_on_user_abort=yes'""")
            else:
                print(f"""Not stopping job because
{Config.FILENAME} deos not contain 'stop_job_on_user_abort=yes'""")
        sys.exit(1)
